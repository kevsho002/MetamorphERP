"""API de la Fase 16: segmentos de actividad, justificaciones por AP y adherencia (WFM).

GET    /adherence/catalogs/                                   actividades, categorías, roles, estados / auxiliares ACD y grupos
GET    /adherence/activities/  ·  POST                        tipos de actividad (segmentos preconfigurados) con sus estados ACD
PATCH  /adherence/activities/{code}/                          nombre, color, pagada, facturable, predeterminada, reglas…
GET    /adherence/planner/?date=&group=&employee=             contenedores del turno, segmentos y plan resultante por agente
POST   /adherence/segments/                                   {employee_code, shift_date, start, end, activity, notes}
POST   /adherence/segments/bulk/                              {employee_codes[] | group, date_from, date_to, start, end, activity}
PATCH  /adherence/segments/{id}/  ·  DELETE                   mover / cambiar actividad / eliminar
GET    /adherence/exceptions/?employee=&from=&to=  ·  POST    justificaciones respaldadas por una AP aprobada
DELETE /adherence/exceptions/{id}/
GET    /adherence/report/?from=&to=&group=&employee=          adherencia, pago válido, billing y excesos por agente y día
GET    /adherence/detail/?employee=&date=                     línea de tiempo plan vs real con desviaciones
POST   /adherence/compute/                                    {from, to, group?, employee?}: guarda el cálculo (nómina / calidad)
"""

from datetime import timedelta

from django.db import DatabaseError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasActionPermission, PasswordChangeNotRequired, user_permissions
from apps.accounts.roles import Perm
from apps.acd.models import AgentGroup, AuxCode, PrimaryStatus
from apps.adherence import services
from apps.adherence.models import ActivityStatusRule, ActivityType, AdherenceException, ScheduleSegment
from apps.hcm.models import Employee
from apps.scheduling.services import parse_any_date

PERMISSIONS = [IsAuthenticated, PasswordChangeNotRequired, HasActionPermission]
NO_STORE = {"Cache-Control": "no-store"}
SQL_ERRORS = (
    ("50070", "SQL Server rechazó el segmento: se traslapa con otro segmento del agente."),
    ("50071", "SQL Server rechazó la justificación: la AP debe estar aprobada y ser del mismo empleado."),
    ("uq_adh_activity_default", "Solo puede haber una actividad predeterminada."),
)


class _View(APIView):
    permission_classes = PERMISSIONS
    method_permissions: dict = {}

    @property
    def action(self):
        return self.request.method.lower()

    @property
    def action_permissions(self):
        return self.method_permissions

    def handle_exception(self, exc):
        if isinstance(exc, services.AdhError):
            return Response({"detail": exc.message, "code": exc.code}, status=exc.status)
        if isinstance(exc, services.AdhErrors):
            return Response({"detail": str(exc), "errors": exc.errors, "code": "invalid"}, status=status.HTTP_400_BAD_REQUEST)
        if isinstance(exc, DatabaseError):
            text = str(exc)
            for number, message in SQL_ERRORS:
                if number in text:
                    return Response({"detail": message, "code": f"sql_{number}"}, status=status.HTTP_409_CONFLICT)
        return super().handle_exception(exc)


def _data(request) -> dict:
    return request.data if isinstance(request.data, dict) else {}


def _employee(code) -> Employee:
    code = str(code or "").strip().upper()
    if not code:
        raise services.AdhErrors({"employee_code": "Indique el ID corporativo del agente."})
    return get_object_or_404(Employee.objects.select_related("country"), employee_code=code)


def _employees(params) -> list[Employee]:
    employees = services.select_employees(group=str(params.get("group") or "").strip(),
                                          employee=str(params.get("employee") or "").strip(),
                                          search=str(params.get("search") or "").strip())
    if len(employees) > services.MAX_EMPLOYEES:
        raise services.AdhError(f"Demasiados agentes (máx. {services.MAX_EMPLOYEES}): filtre por grupo o agente.", "too_many")
    return employees


def _range(params, default_to_from=True):
    date_from = parse_any_date(params.get("from"))
    date_to = parse_any_date(params.get("to")) or (date_from if default_to_from else None)
    return date_from, date_to


class CatalogsView(_View):
    method_permissions = {"get": Perm.WFM_VIEW}

    def get(self, request):
        statuses = PrimaryStatus.objects.filter(is_logged_in=True).order_by("sort_order")
        auxes = AuxCode.objects.select_related("primary_status", "parent").order_by("primary_status__sort_order", "sort_order", "name")
        return Response({
            "activities": [services.activity_dict(a) for a in services._activity_qs()],
            "categories": [{"value": v, "label": label} for v, label in ActivityType.Category.choices],
            "roles": [{"value": v, "label": label} for v, label in ActivityStatusRule.Role.choices],
            "primary_statuses": [{"code": s.code, "label": s.label, "name": s.name_es, "color": s.color, "is_paid": s.is_paid} for s in statuses],
            "aux_codes": [{"code": a.code, "name": a.full_name, "primary_status": a.primary_status.code, "is_paid": a.paid,
                           "parent": a.parent.code if a.parent_id else None, "is_active": a.is_active} for a in auxes],
            "groups": [{"code": g.code, "name": g.name} for g in AgentGroup.objects.filter(is_active=True).order_by("name")],
            "can_manage": Perm.WFM_MANAGE in user_permissions(request.user),
        }, headers=NO_STORE)


class ActivitiesView(_View):
    method_permissions = {"get": Perm.WFM_VIEW, "post": Perm.WFM_MANAGE}

    def get(self, request):
        return Response({"results": [services.activity_dict(a) for a in services._activity_qs()]}, headers=NO_STORE)

    def post(self, request):
        a = services.save_activity(_data(request), user=request.user, request=request)
        return Response({"activity": services.activity_dict(a), "feedback": f"Actividad {a.code} creada."}, status=status.HTTP_201_CREATED)


class ActivityDetailView(_View):
    method_permissions = {"patch": Perm.WFM_MANAGE}

    def patch(self, request, code: str):
        a = get_object_or_404(ActivityType, code=code.upper())
        a = services.save_activity(_data(request), activity=a, user=request.user, request=request)
        return Response({"activity": services.activity_dict(a), "feedback": f"Actividad {a.code} actualizada."})


class PlannerView(_View):
    method_permissions = {"get": Perm.WFM_VIEW}

    def get(self, request):
        p = request.query_params
        d = parse_any_date(p.get("date"))
        if d is None:
            raise services.AdhErrors({"date": "Indique la fecha del turno (AAAA-MM-DD)."})
        if not p.get("group") and not p.get("employee"):
            raise services.AdhErrors({"group": "Elija un grupo de agentes o un agente."})
        data = services.planner_day(_employees(p), d)
        return Response({**data, "can_manage": Perm.WFM_MANAGE in user_permissions(request.user)}, headers=NO_STORE)


class SegmentsView(_View):
    method_permissions = {"post": Perm.WFM_MANAGE}

    def post(self, request):
        data = _data(request)
        employee = _employee(data.get("employee_code"))
        seg = services.save_segment(employee, data, user=request.user, request=request)
        return Response({"segment": services.segment_dict(seg),
                         "feedback": f"{seg.activity.name} {seg.start_at:%H:%M}–{seg.end_at:%H:%M} programado para {employee.employee_code}."},
                        status=status.HTTP_201_CREATED)


class SegmentsBulkView(_View):
    method_permissions = {"post": Perm.WFM_MANAGE}

    def post(self, request):
        data = _data(request)
        codes = data.get("employee_codes") or []
        if isinstance(codes, list) and codes:
            employees = services.select_employees(employee=",".join(str(c) for c in codes))
        elif data.get("group"):
            employees = services.select_employees(group=str(data["group"]))
        else:
            raise services.AdhErrors({"employee_codes": "Elija los agentes o un grupo."})
        date_from = parse_any_date(data.get("date_from"))
        date_to = parse_any_date(data.get("date_to")) or date_from
        result = services.bulk_segments(employees, date_from, date_to, data, user=request.user, request=request)
        return Response({**result, "feedback": f"{result['created']} segmentos programados"
                         + (f"; {len(result['skipped'])} omitidos" if result["skipped"] else "") + "."},
                        status=status.HTTP_201_CREATED)


class SegmentDetailView(_View):
    method_permissions = {"patch": Perm.WFM_MANAGE, "delete": Perm.WFM_MANAGE}

    def _get(self, pk):
        return get_object_or_404(ScheduleSegment.objects.select_related("employee", "activity"), pk=pk)

    def patch(self, request, pk: int):
        seg = self._get(pk)
        seg = services.save_segment(seg.employee, _data(request), segment=seg, user=request.user, request=request)
        return Response({"segment": services.segment_dict(seg), "feedback": "Segmento actualizado."})

    def delete(self, request, pk: int):
        services.delete_segment(self._get(pk), user=request.user, request=request)
        return Response({"feedback": "Segmento eliminado."})


class ExceptionsView(_View):
    method_permissions = {"get": Perm.WFM_VIEW, "post": Perm.WFM_MANAGE}

    def get(self, request):
        p = request.query_params
        qs = AdherenceException.objects.select_related("employee", "personnel_action__action_type").order_by("-start_at")
        if p.get("employee"):
            qs = qs.filter(employee__employee_code=str(p["employee"]).strip().upper())
        date_from, date_to = _range(p, default_to_from=False)
        if date_from:
            qs = qs.filter(end_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(start_at__date__lt=date_to + timedelta(days=1))
        return Response({"results": [services.exception_dict(x) for x in qs[:500]],
                         "can_manage": Perm.WFM_MANAGE in user_permissions(request.user)}, headers=NO_STORE)

    def post(self, request):
        data = _data(request)
        employee = _employee(data.get("employee_code"))
        x = services.save_exception(employee, data, user=request.user, request=request)
        return Response({"exception": services.exception_dict(x), "feedback": f"Justificación registrada con la AP {x.personnel_action.folio}."},
                        status=status.HTTP_201_CREATED)


class ExceptionDetailView(_View):
    method_permissions = {"delete": Perm.WFM_MANAGE}

    def delete(self, request, pk: int):
        x = get_object_or_404(AdherenceException.objects.select_related("employee", "personnel_action"), pk=pk)
        services.delete_exception(x, user=request.user, request=request)
        return Response({"feedback": "Justificación eliminada."})


class ReportView(_View):
    method_permissions = {"get": Perm.WFM_VIEW}

    def get(self, request):
        date_from, date_to = _range(request.query_params)
        return Response(services.report(_employees(request.query_params), date_from, date_to), headers=NO_STORE)


class DetailView(_View):
    method_permissions = {"get": Perm.WFM_VIEW}

    def get(self, request):
        p = request.query_params
        d = parse_any_date(p.get("date"))
        if d is None:
            raise services.AdhErrors({"date": "Indique la fecha del turno (AAAA-MM-DD)."})
        return Response(services.detail(_employee(p.get("employee")), d), headers=NO_STORE)


class ComputeView(_View):
    method_permissions = {"post": Perm.WFM_MANAGE}

    def post(self, request):
        data = _data(request)
        date_from, date_to = _range(data)
        result = services.compute_and_store(_employees(data), date_from, date_to, user=request.user, request=request)
        return Response({**result, "feedback": f"Adherencia guardada: {result['stored']} días-agente hasta el {result['until']}."})
