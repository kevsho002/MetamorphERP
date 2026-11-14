"""API del calendario de feriados (Fase 21).

GET    /holidays/?country=SV&year=2026            feriados del año con sus Holiday Segments generados
POST   /holidays/                                  {country, date, name, kind, premium_percent, legal_reference}
PATCH  /holidays/{id}/  ·  DELETE /holidays/{id}/  (un feriado con Holiday Segments no cambia su fecha ni se elimina)
GET    /holidays/segments/?from=&to=&search=       Holiday Segments (feriados laborados) por colaborador
POST   /holidays/segments/generate/ {from, to}     regenera los contenedores del rango (idempotente)
"""

from django.db import DatabaseError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasActionPermission, PasswordChangeNotRequired, user_permissions
from apps.accounts.roles import Perm
from apps.common.models import Country
from apps.hcm.models import Employee
from apps.holidays import services
from apps.holidays.models import Holiday, HolidaySegment
from apps.personnel_actions.services import parse_date

NO_STORE = {"Cache-Control": "no-store"}


class _View(APIView):
    permission_classes = [IsAuthenticated, PasswordChangeNotRequired, HasActionPermission]
    method_permissions: dict = {}

    @property
    def action(self):
        return self.request.method.lower()

    @property
    def action_permissions(self):
        return self.method_permissions

    def handle_exception(self, exc):
        if isinstance(exc, services.HolidayError):
            return Response({"detail": exc.message, "code": exc.code}, status=exc.status)
        if isinstance(exc, DatabaseError) and "50097" in str(exc):
            return Response({"detail": "El sistema rechazó el cambio: el feriado ya generó Holiday Segments.", "code": "sql_50097"},
                            status=status.HTTP_409_CONFLICT)
        return super().handle_exception(exc)


def _data(request) -> dict:
    return request.data if isinstance(request.data, dict) else {}


class HolidaysView(_View):
    method_permissions = {"get": Perm.SCHEDULES_VIEW, "post": Perm.PAYROLL_MANAGE}

    def get(self, request):
        p = request.query_params
        try:
            year = int(p.get("year") or timezone.localdate().year)
        except ValueError:
            year = timezone.localdate().year
        qs = Holiday.objects.filter(date__year=year).annotate(n=Count("segments"))
        if p.get("country"):
            qs = qs.filter(country__country_code=p["country"].upper())
        countries = {c.pk: c.country_code for c in Country.objects.all()}
        rows = []
        for h in qs.order_by("date"):
            row = services.holiday_dict(h, h.n)
            row["country_code"] = countries.get(h.country_id)
            rows.append(row)
        return Response({
            "year": year, "results": rows, "can_manage": Perm.PAYROLL_MANAGE in user_permissions(request.user),
            "countries": [{"code": c.country_code, "name": c.country_name}
                          for c in Country.objects.filter(is_active=True).order_by("country_name")],
            "kinds": [{"value": v, "label": label} for v, label in Holiday.Kind.choices],
        }, headers=NO_STORE)

    def post(self, request):
        h = services.save_holiday(_data(request), user=request.user, request=request)
        return Response(services.holiday_dict(h, 0), status=status.HTTP_201_CREATED)


class CopyYearView(_View):
    """Fase 23 — POST /holidays/copy-year/ {country, from_year, to_year}."""

    method_permissions = {"post": Perm.PAYROLL_MANAGE}

    def post(self, request):
        d = _data(request)
        try:
            src, dst = int(d.get("from_year")), int(d.get("to_year"))
        except (TypeError, ValueError):
            return Response({"detail": "Indique los años de origen y destino.", "code": "invalid"}, status=status.HTTP_400_BAD_REQUEST)
        rows = services.copy_year(d.get("country"), src, dst, user=request.user, request=request)
        n = len(rows)
        return Response({"created": rows, "feedback": (f"{n} feriado(s) copiados a {dst} (Semana Santa recalculada con la Pascua de {dst}). "
                                                       "Revise los feriados de fecha móvil o por decreto." if n else
                                                       f"No había feriados nuevos que copiar a {dst}.")},
                        status=status.HTTP_201_CREATED if n else status.HTTP_200_OK)


class HolidayDetailView(_View):
    method_permissions = {"patch": Perm.PAYROLL_MANAGE, "delete": Perm.PAYROLL_MANAGE}

    def patch(self, request, pk: int):
        h = services.save_holiday(_data(request), holiday=get_object_or_404(Holiday, pk=pk), user=request.user, request=request)
        return Response(services.holiday_dict(h, h.segments.count()))

    def delete(self, request, pk: int):
        services.delete_holiday(get_object_or_404(Holiday, pk=pk), user=request.user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SegmentsView(_View):
    method_permissions = {"get": Perm.SCHEDULES_VIEW}

    def get(self, request):
        p = request.query_params
        today = timezone.localdate()
        lo = parse_date(p.get("from")) or today.replace(month=1, day=1)
        hi = parse_date(p.get("to")) or today.replace(month=12, day=31)
        qs = HolidaySegment.objects.filter(shift_date__range=(lo, hi)).select_related("holiday", "employee").order_by("shift_date", "employee_id")
        for term in p.get("search", "").split():
            qs = qs.filter(Q(employee__employee_code__icontains=term) | Q(employee__first_name__icontains=term)
                           | Q(employee__last_name__icontains=term) | Q(holiday__name__icontains=term))
        rows = [services.segment_dict(s) for s in qs[:2000]]
        return Response({"from": lo, "to": hi, "count": len(rows), "results": rows,
                         "can_generate": bool({Perm.PAYROLL_MANAGE, Perm.WFM_MANAGE} & user_permissions(request.user)),
                         "totals": {"worked_seconds": sum(r["worked_seconds"] for r in rows),
                                    "night_seconds": sum(r["night_seconds"] for r in rows)}}, headers=NO_STORE)


class GenerateView(_View):
    method_permissions = {"post": Perm.SCHEDULES_VIEW}

    def post(self, request):
        if not ({Perm.PAYROLL_MANAGE, Perm.WFM_MANAGE} & user_permissions(request.user)):
            return Response({"detail": "Requiere administrar planillas o WFM."}, status=status.HTTP_403_FORBIDDEN)
        data = _data(request)
        lo, hi = parse_date(data.get("from")), parse_date(data.get("to"))
        if not lo or not hi or hi < lo or (hi - lo).days > 400:
            return Response({"detail": "Indique un rango válido (máximo 400 días)."}, status=status.HTTP_400_BAD_REQUEST)
        employees = Employee.objects.filter(hire_date__lte=hi).filter(Q(termination_date__isnull=True) | Q(termination_date__gte=lo))
        out = services.generate_segments(employees, lo, hi, user=request.user, request=request)
        return Response({**out, "feedback": f"Holiday Segments: {out['created']} nuevos, {out['updated']} actualizados, "
                                            f"{out['removed']} retirados ({out['holidays']} feriados en el rango)."})
