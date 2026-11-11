"""API del roster operativo (dominio independiente de la ficha del empleado).

GET  /roster/attributes/                         definiciones activas (dibujan la sección en React)
GET  /roster/dimensions/                         catálogos: clientes, marcas, líneas, sub-líneas...
GET  /roster/employees/{ID}/?as_of=&include=employee   roster vigente a una fecha (+ ficha, cruzado)
GET  /roster/employees/{ID}/history/?attribute=&include_superseded=1   intervalos (auditoría)
POST /roster/employees/{ID}/changes/             registrar cambios con fecha efectiva
POST /roster/employees/{ID}/changes/validate/    lo mismo sin guardar
GET  /roster/report/?from=&to=&country=&attribute=&value=&export=csv   empleados + asignaciones en un rango
"""

import csv

from django.db.models import Exists, OuterRef, Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasActionPermission, PasswordChangeNotRequired, user_permissions
from apps.accounts.roles import Perm
from apps.employees.serializers import EmployeeSerializer
from apps.hcm.models import Employee
from apps.roster import services
from apps.roster.models import RosterAssignment, RosterAttribute, RosterDimension, RosterDimensionItem
from apps.roster.serializers import RosterAttributeSerializer, RosterDimensionSerializer
from apps.system.audit import Category, record

PERMISSIONS = [IsAuthenticated, PasswordChangeNotRequired, HasActionPermission]
NO_STORE = {"Cache-Control": "no-store"}
EMPLOYEE_CODE = r"[A-Za-z0-9]+-\d{4}-\d{6}-\d"
CSV_ROW_LIMIT = 100_000


def _date_param(request, name: str, default=None):
    raw = request.query_params.get(name, "").strip()
    if not raw:
        return default
    if raw.lower() in {"today", "hoy"}:
        return timezone.localdate()
    parsed = services.parse_any_date(raw)
    if parsed is None:
        raise ValidationError({name: "Use el formato AAAA-MM-DD."})
    return parsed


class _RosterView(APIView):
    permission_classes = PERMISSIONS


class AttributeListView(_RosterView):
    action = "attributes"
    action_permissions = {"attributes": Perm.ROSTER_VIEW}

    def get(self, request):
        qs = RosterAttribute.objects.select_related("dimension", "depends_on")
        if request.query_params.get("include_inactive") not in {"1", "true"}:
            qs = qs.filter(is_active=True)
        return Response(RosterAttributeSerializer(qs, many=True).data)


class DimensionListView(_RosterView):
    action = "dimensions"
    action_permissions = {"dimensions": Perm.ROSTER_VIEW}

    def get(self, request):
        include_inactive = request.query_params.get("include_inactive") in {"1", "true"}
        qs = RosterDimension.objects.select_related("parent").prefetch_related(
            Prefetch("items", queryset=RosterDimensionItem.objects.select_related("parent", "country").order_by("name"))
        )
        if not include_inactive:
            qs = qs.filter(is_active=True)
        return Response(RosterDimensionSerializer(qs, many=True, context={"include_inactive": include_inactive}).data)


class EmployeeRosterView(_RosterView):
    action = "employee_roster"
    action_permissions = {"employee_roster": Perm.ROSTER_VIEW}

    def get(self, request, code: str):
        employee = get_object_or_404(Employee.objects.select_related("country", "cost_center"), employee_code=code.upper())
        on = _date_param(request, "as_of", timezone.localdate())
        body = {
            "employee_code": employee.employee_code,
            "full_name": employee.full_name,
            "country": employee.country.country_code,
            "hire_date": employee.hire_date,
            "termination_date": employee.termination_date,
            "as_of": on,
            "attributes": services.snapshot(employee, on),
            "can_manage": Perm.ROSTER_MANAGE in _perms(request),
        }
        if "employee" in request.query_params.get("include", "").split(","):
            if Perm.HCM_VIEW not in _perms(request):
                raise ValidationError({"include": "Su rol no puede consultar la ficha del empleado."})
            body["employee"] = EmployeeSerializer(employee, context={"request": request}).data
        return Response(body, headers=NO_STORE)


class EmployeeRosterHistoryView(_RosterView):
    action = "employee_roster_history"
    action_permissions = {"employee_roster_history": Perm.ROSTER_VIEW}

    def get(self, request, code: str):
        employee = get_object_or_404(Employee, employee_code=code.upper())
        qs = RosterAssignment.objects.filter(employee=employee).select_related("attribute", "item", "item__parent")
        if request.query_params.get("include_superseded") not in {"1", "true"}:
            qs = qs.current()
        if attribute := request.query_params.get("attribute"):
            qs = qs.filter(attribute__code=attribute)
        rows = qs.order_by("attribute__display_order", "attribute__name", "-effective_start", "-recorded_at")
        return Response(
            {
                "employee_code": employee.employee_code,
                "results": [
                    {"attribute": r.attribute.code, "attribute_name": r.attribute.name, **services.interval_payload(r)} for r in rows
                ],
            },
            headers=NO_STORE,
        )


class EmployeeRosterChangeView(_RosterView):
    action = "employee_roster_change"
    action_permissions = {"employee_roster_change": Perm.ROSTER_MANAGE}
    dry_run = False

    def post(self, request, code: str):
        if not isinstance(request.data, dict):
            raise ValidationError({"detail": "Envíe {effective_date, reason, values: {código: valor}}."})
        employee = get_object_or_404(Employee, employee_code=code.upper())
        if not self.dry_run:
            employee = Employee.objects.select_for_update().get(pk=employee.pk)  # serializa cambios concurrentes
        plan = services.plan_changes(employee, request.data)
        body = {
            "valid": plan.ok,
            "saved": False,
            "feedback": services.feedback(plan, dry_run=self.dry_run),
            "changes": [c.as_dict() for c in plan.changes],
            "errors": plan.errors,
            "warnings": plan.warnings,
        }
        if not plan.ok:
            body["detail"] = body["feedback"]
            return Response(body, status=status.HTTP_400_BAD_REQUEST)
        if not self.dry_run and plan.effective_changes:
            change_id = services.apply_plan(plan, actor=request.user.username)
            body["saved"] = True
            body["change_id"] = str(change_id)
            record(
                "roster_changed", Category.ROSTER, body["feedback"][:500],
                request=request, target=employee,
                details={"change_id": str(change_id), "effective_date": plan.effective_date, "reason": plan.reason,
                         "changes": [c.as_dict() for c in plan.effective_changes]},
            )
        body["attributes"] = services.snapshot(employee, plan.effective_date)
        return Response(body, headers=NO_STORE)


class EmployeeRosterValidateView(EmployeeRosterChangeView):
    dry_run = True


def _perms(request):
    return user_permissions(request.user)


class ReportPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500


class RosterReportView(_RosterView):
    """Consulta cruzada ficha + roster: empleados y sus asignaciones que se cruzan con [from, to]."""

    action = "roster_report"
    action_permissions = {"roster_report": Perm.ROSTER_VIEW}

    def get(self, request):
        start = _date_param(request, "from", timezone.localdate())
        end = _date_param(request, "to", start)
        if end < start:
            raise ValidationError({"to": "La fecha final es anterior a la inicial."})
        params = request.query_params
        employees = Employee.objects.select_related("country", "cost_center").order_by("employee_code")
        if country := params.get("country"):
            employees = employees.filter(country__country_code__iexact=country)
        status_ = params.get("status", "").strip().upper()
        if status_ == "NOT_ACTIVE":  # inactivos + terminados
            employees = employees.exclude(employment_status=Employee.Status.ACTIVE)
        elif status_ and status_ != "ALL":
            employees = employees.filter(employment_status=status_)
        if cost_center := params.get("cost_center"):
            employees = employees.filter(cost_center__code__iexact=cost_center)
        if search := params.get("search", "").strip():
            employees = employees.filter(
                Q(employee_code__icontains=search) | Q(first_name__icontains=search) | Q(last_name__icontains=search)
            )
        # Vigentes en el rango: ingresados antes del fin y no terminados antes del inicio.
        employees = employees.filter(hire_date__lte=end).filter(Q(termination_date__isnull=True) | Q(termination_date__gte=start))
        in_range = RosterAssignment.objects.current().overlapping(start, end)
        if attribute := params.get("attribute"):
            value = params.get("value", "").strip()
            matching = in_range.filter(employee=OuterRef("pk"), attribute__code=attribute)
            if value:
                matching = matching.filter(value__iexact=value)
            employees = employees.filter(Exists(matching))
        if params.get("assigned") in {"1", "true"}:
            employees = employees.filter(Exists(in_range.filter(employee=OuterRef("pk"))))

        attributes = services.active_attributes()
        if params.get("export") == "csv":  # «format» lo reserva DRF
            return self._csv(employees, in_range, attributes, start, end)

        paginator = ReportPagination()
        page = paginator.paginate_queryset(employees, request, view=self)
        rows = (
            in_range.filter(employee__in=page, attribute__is_active=True)
            .select_related("attribute", "item", "item__parent")
            .order_by("employee_id", "attribute__display_order", "effective_start")
        )
        by_employee: dict[int, dict[str, list]] = {}
        for row in rows:
            by_employee.setdefault(row.employee_id, {}).setdefault(row.attribute.code, []).append(
                {k: v for k, v in services.interval_payload(row).items() if k in {"value", "label", "effective_start", "effective_end", "is_now"}}
            )
        results = [
            {
                "employee": {
                    "employee_code": e.employee_code,
                    "full_name": e.full_name,
                    "country": e.country.country_code,
                    "cost_center": e.cost_center.code if e.cost_center else None,
                    "employment_status": e.employment_status,
                    "employment_status_label": e.get_employment_status_display(),
                    "hire_date": e.hire_date,
                    "termination_date": e.termination_date,
                },
                "assignments": by_employee.get(e.employee_id, {}),
            }
            for e in page
        ]
        response = paginator.get_paginated_response(results)
        response.data["range"] = {"from": start, "to": end}
        response.data["attributes"] = RosterAttributeSerializer(attributes, many=True).data
        return response

    def _csv(self, employees, in_range, attributes, start, end):
        """Formato largo (una fila por intervalo): directo para Excel / Power BI."""
        codes = {a.pk for a in attributes}
        rows = (
            in_range.filter(employee__in=employees, attribute_id__in=codes)
            .select_related("attribute", "item", "employee", "employee__country", "employee__cost_center")
            .order_by("employee__employee_code", "attribute__display_order", "effective_start")[:CSV_ROW_LIMIT]
        )
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="roster_{start:%Y%m%d}_{end:%Y%m%d}.csv"'
        response.write("﻿")
        writer = csv.writer(response)
        writer.writerow([
            "id_corporativo", "nombre", "pais", "centro_costos", "estado", "fecha_ingreso", "atributo", "atributo_nombre",
            "valor", "valor_descripcion", "vigente_desde", "vigente_hasta",
        ])
        for r in rows:
            e = r.employee
            writer.writerow([
                e.employee_code, e.full_name, e.country.country_code, e.cost_center.code if e.cost_center else "",
                e.employment_status, e.hire_date.isoformat(), r.attribute.code, r.attribute.name, r.value,
                services.label_of(r), r.effective_start.isoformat(), r.effective_end.isoformat() if r.effective_end else "Now",
            ])
        return response

