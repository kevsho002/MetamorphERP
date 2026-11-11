"""API de General IDs (independiente del roster y de la ficha).

GET   /general-ids/catalogs/                              herramientas, tipos (con restricciones) y clientes/marcas
GET   /general-ids/employees/{ID}/?as_of=&history=1       IDs del empleado (vigentes a una fecha, o todo el historial)
POST  /general-ids/employees/{ID}/                        registrar un ID {id_type, value, client, brand, effective_start, effective_end, notes}
POST  /general-ids/employees/{ID}/validate/               lo mismo sin guardar
PATCH /general-ids/employees/{ID}/{pk}/                   corregir (valor, cliente/marca, vigencia, notas)
POST  /general-ids/employees/{ID}/{pk}/close/             cerrar la vigencia {effective_end}
GET   /general-ids/lookup/?type=ACD_ID&value=123&date=    ¿a quién pertenece este ID en esa fecha? (JOIN)
GET   /general-ids/report/?from=&to=&type=&tool=&client=&brand=&country=&search=&export=csv
"""

import csv

from django.db.models import Prefetch, Q
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
from apps.general_ids import services
from apps.general_ids.models import EmployeeGeneralId, GeneralIdType, SourceTool
from apps.hcm.models import Employee
from apps.operations.models import Brand, Client

PERMISSIONS = [IsAuthenticated, PasswordChangeNotRequired, HasActionPermission]
NO_STORE = {"Cache-Control": "no-store"}
CSV_ROW_LIMIT = 100_000


def _date_param(request, name: str, default=None):
    raw = request.query_params.get(name, "").strip()
    if not raw:
        return default
    parsed = services.parse_any_date(raw)
    if parsed is None:
        raise ValidationError({name: "Use el formato AAAA-MM-DD."})
    return parsed


def _employee(code: str) -> Employee:
    return get_object_or_404(Employee.objects.select_related("country"), employee_code=code.upper())


def _rows(qs):
    return qs.select_related("id_type__tool", "client", "brand")


class _View(APIView):
    permission_classes = PERMISSIONS


class CatalogsView(_View):
    action = "catalogs"
    action_permissions = {"catalogs": Perm.GENERAL_IDS_VIEW}

    def get(self, request):
        include_inactive = request.query_params.get("include_inactive") in {"1", "true"}
        tools = SourceTool.objects.all() if include_inactive else SourceTool.objects.filter(is_active=True)
        types = GeneralIdType.objects.select_related("tool").prefetch_related("client_scopes__client", "brand_scopes__brand")
        if not include_inactive:
            types = types.filter(is_active=True, tool__is_active=True)
        clients = Client.objects.prefetch_related(Prefetch("brands", queryset=Brand.objects.order_by("name"))).order_by("name")
        return Response(
            {
                "tools": [
                    {"code": t.code, "name": t.name, "category": t.category, "category_label": t.get_category_display(),
                     "vendor": t.vendor, "is_active": t.is_active}
                    for t in tools
                ],
                "types": [
                    {
                        "code": t.code, "name": t.name, "tool": t.tool.code, "tool_name": t.tool.name,
                        "description": t.description, "scope_level": t.scope_level, "scope_level_label": t.get_scope_level_display(),
                        "allow_multiple_active": t.allow_multiple_active, "unique_value": t.unique_value,
                        "pattern": t.pattern or None, "pattern_message": t.pattern_message or None, "example": t.example or None,
                        "max_length": t.max_length, "transform": t.transform, "is_active": t.is_active,
                        "applies_to": {
                            "all": not t.client_scopes.all() and not t.brand_scopes.all(),
                            "clients": [s.client.code for s in t.client_scopes.all()],
                            "brands": [s.brand.code for s in t.brand_scopes.all()],
                        },
                    }
                    for t in types
                ],
                "clients": [
                    {
                        "code": c.code, "name": c.name, "country": c.country_id, "is_active": c.is_active,
                        "brands": [{"code": b.code, "name": b.name, "is_active": b.is_active} for b in c.brands.all()],
                    }
                    for c in clients
                    if include_inactive or c.is_active
                ],
            }
        )


class EmployeeGeneralIdsView(_View):
    """GET lista / POST alta."""

    action_permissions = {"get": Perm.GENERAL_IDS_VIEW, "post": Perm.GENERAL_IDS_MANAGE}
    dry_run = False

    @property
    def action(self):  # HasActionPermission resuelve el permiso por método
        return self.request.method.lower()

    def get(self, request, code: str):
        employee = _employee(code)
        on = _date_param(request, "as_of", timezone.localdate())
        qs = _rows(EmployeeGeneralId.objects.filter(employee=employee))
        if request.query_params.get("history") not in {"1", "true"}:
            qs = qs.as_of(on)
        rows = qs.order_by("id_type__display_order", "id_type__name", "-effective_start")
        perms = user_permissions(request.user)
        return Response(
            {
                "employee_code": employee.employee_code,
                "full_name": employee.full_name,
                "country": employee.country.country_code,
                "hire_date": employee.hire_date,
                "termination_date": employee.termination_date,
                "employment_status": employee.employment_status,
                "as_of": on,
                "results": [services.serialize(g, on) for g in rows],
                "can_manage": Perm.GENERAL_IDS_MANAGE in perms and employee.employment_status != Employee.Status.TERMINATED,
            },
            headers=NO_STORE,
        )

    def post(self, request, code: str):
        if not isinstance(request.data, dict):
            raise ValidationError({"detail": "Envíe {id_type, value, client, brand, effective_start, effective_end, notes}."})
        employee = _employee(code)
        check = services.validate(employee, dict(request.data))
        body = {"valid": check.ok, "errors": check.errors, "warnings": check.warnings, "feedback": check.feedback()}
        if self.dry_run or not check.ok:
            if not check.ok:
                body["detail"] = body["feedback"]
            return Response(body, status=status.HTTP_200_OK if self.dry_run else status.HTTP_400_BAD_REQUEST)
        g = services.create(employee, check, user=request.user, request=request)
        body["general_id"] = services.serialize(g)
        body["feedback"] = f"General ID registrado: {g.id_type.name} «{g.value}»." + (
            " " + " ".join(w["message"] for w in check.warnings) if check.warnings else ""
        )
        return Response(body, status=status.HTTP_201_CREATED)


class EmployeeGeneralIdValidateView(EmployeeGeneralIdsView):
    dry_run = True
    action_permissions = {"post": Perm.GENERAL_IDS_MANAGE}


class EmployeeGeneralIdDetailView(_View):
    """PATCH corrección / POST close."""

    close = False

    @property
    def action(self):
        return "close" if self.close else "patch"

    action_permissions = {"patch": Perm.GENERAL_IDS_MANAGE, "close": Perm.GENERAL_IDS_MANAGE}

    def _get(self, code: str, pk: int):
        employee = _employee(code)
        g = get_object_or_404(_rows(EmployeeGeneralId.objects.select_for_update()), pk=pk, employee=employee)
        return employee, g

    def _respond(self, employee, g, data, action):
        check = services.validate(employee, data, instance=g)
        body = {"valid": check.ok, "errors": check.errors, "warnings": check.warnings,
                "feedback": check.feedback("cerrar" if self.close else "corregir")}
        if not check.ok:
            body["detail"] = body["feedback"]
            return Response(body, status=status.HTTP_400_BAD_REQUEST)
        if request_dry_run(self.request):
            return Response(body)
        g = services.update(g, check, user=self.request.user, request=self.request, action=action)
        body["general_id"] = services.serialize(g)
        body["feedback"] = "General ID cerrado." if self.close else "General ID corregido."
        return Response(body)

    def patch(self, request, code: str, pk: int):
        if not isinstance(request.data, dict):
            raise ValidationError({"detail": "Envíe los campos a corregir."})
        employee, g = self._get(code, pk)
        allowed = {"value", "client", "brand", "effective_start", "effective_end", "notes", "id_type"}
        data = {k: v for k, v in request.data.items() if k in allowed}
        return self._respond(employee, g, data, "general_id_updated")

    def post(self, request, code: str, pk: int):
        employee, g = self._get(code, pk)
        end = request.data.get("effective_end") if isinstance(request.data, dict) else None
        if end in (None, ""):
            raise ValidationError({"effective_end": "Indique hasta qué fecha estuvo vigente el ID."})
        data = {"effective_end": end}
        if isinstance(request.data, dict) and request.data.get("notes"):
            data["notes"] = request.data["notes"]
        return self._respond(employee, g, data, "general_id_closed")


def request_dry_run(request) -> bool:
    return request.query_params.get("dry_run") in {"1", "true"}


class LookupView(_View):
    """Resuelve un ID a su empleado en una fecha: la operación que hace un JOIN de reportería."""

    action = "lookup"
    action_permissions = {"lookup": Perm.GENERAL_IDS_VIEW}

    def get(self, request):
        type_code = request.query_params.get("type", "").strip()
        value = request.query_params.get("value", "").strip()
        if not type_code or not value:
            raise ValidationError({"detail": "Indique type (código del tipo de ID) y value."})
        id_type = GeneralIdType.objects.filter(code__iexact=type_code).first()
        if id_type is None:
            raise ValidationError({"type": f"No existe el tipo de ID «{type_code}»."})
        on = _date_param(request, "date", timezone.localdate())
        normalized = services.normalize_value(id_type, value)
        rows = _rows(EmployeeGeneralId.objects.filter(id_type=id_type, value__iexact=normalized).select_related("employee__country"))
        current = [g for g in rows if g.effective_start <= on <= (g.effective_end or services.FAR_FUTURE)]
        return Response(
            {
                "type": id_type.code,
                "value": normalized,
                "date": on,
                "matches": [
                    {**services.serialize(g, on), "employee_code": g.employee.employee_code, "full_name": g.employee.full_name,
                     "country": g.employee.country.country_code}
                    for g in current
                ],
                "history": [
                    {"employee_code": g.employee.employee_code, "effective_start": g.effective_start, "effective_end": g.effective_end}
                    for g in rows.order_by("effective_start")
                ],
            },
            headers=NO_STORE,
        )


class ReportPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500


class ReportView(_View):
    action = "report"
    action_permissions = {"report": Perm.GENERAL_IDS_VIEW}

    def get(self, request):
        start = _date_param(request, "from", timezone.localdate())
        end = _date_param(request, "to", start)
        if end < start:
            raise ValidationError({"to": "La fecha final es anterior a la inicial."})
        p = request.query_params
        qs = _rows(EmployeeGeneralId.objects.overlapping(start, end).select_related("employee__country"))
        if t := p.get("type"):
            qs = qs.filter(id_type__code__iexact=t)
        if tool := p.get("tool"):
            qs = qs.filter(id_type__tool__code__iexact=tool)
        if client := p.get("client"):
            qs = qs.filter(client__code__iexact=client)
        if brand := p.get("brand"):
            qs = qs.filter(brand__code__iexact=brand)
        if country := p.get("country"):
            qs = qs.filter(employee__country__country_code__iexact=country)
        if search := p.get("search", "").strip():
            qs = qs.filter(
                Q(value__icontains=search) | Q(employee__employee_code__icontains=search)
                | Q(employee__first_name__icontains=search) | Q(employee__last_name__icontains=search)
            )
        qs = qs.order_by("employee__employee_code", "id_type__display_order", "effective_start")

        def row(g):
            return {**services.serialize(g, start), "employee_code": g.employee.employee_code,
                    "full_name": g.employee.full_name, "country": g.employee.country.country_code,
                    "employment_status": g.employee.employment_status}

        if p.get("export") == "csv":
            response = HttpResponse(content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = f'attachment; filename="general_ids_{start:%Y%m%d}_{end:%Y%m%d}.csv"'
            response.write("﻿")
            writer = csv.writer(response)
            writer.writerow(["EmployeeCode", "FullName", "Country", "EmploymentStatus", "IdType", "Tool", "Value",
                             "ClientCode", "ClientName", "BrandCode", "BrandName", "EffectiveStart", "EffectiveEnd"])
            for g in qs[:CSV_ROW_LIMIT]:
                writer.writerow([
                    g.employee.employee_code, g.employee.full_name, g.employee.country.country_code, g.employee.employment_status,
                    g.id_type.code, g.id_type.tool.code, g.value, g.client.code if g.client_id else "",
                    g.client.name if g.client_id else "", g.brand.code if g.brand_id else "", g.brand.name if g.brand_id else "",
                    g.effective_start.isoformat(), g.effective_end.isoformat() if g.effective_end else "Now",
                ])
            return response
        paginator = ReportPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        response = paginator.get_paginated_response([row(g) for g in page])
        response.data["range"] = {"from": start, "to": end}
        return response
