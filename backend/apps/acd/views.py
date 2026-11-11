"""API del módulo ACD (Fase 11): estados y auxiliares de agentes estilo Genesys Cloud.

GET    /acd/catalogs/                                estados primarios, auxiliares / sub-auxiliares, grupos y divisiones
GET    /acd/me/                                      estado actual del agente, opciones permitidas por su grupo y su día
POST   /acd/me/login/  ·  /acd/me/logout/            iniciar / cerrar sesión (Available / Offline)
POST   /acd/me/status/                               {primary_status, aux_code?}: On Queue, Break, Meal…
GET    /acd/agents/?group=&division=&status=&search= tablero en vivo de agentes (supervisión)
POST   /acd/agents/{ID}/logout/                      cierre de sesión forzado por un supervisor
GET    /acd/report/?from=&to=&interval=&tz=&group=&division=&employee=&status=&export=csv
                                                     reporte de estados con las columnas de Genesys Cloud
GET    /acd/groups/  ·  POST                         grupos / perfiles de agentes
GET    /acd/groups/{code}/  ·  PATCH                 nombre, división, activo y auxiliares permitidos (aux_codes)
POST   /acd/groups/{code}/members/                   {employee_code}: asigna el agente (lo mueve si estaba en otro grupo)
DELETE /acd/groups/{code}/members/{ID}/              lo retira del grupo
"""

import csv

from django.db import DatabaseError
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasActionPermission, PasswordChangeNotRequired, user_permissions
from apps.accounts.roles import Perm
from apps.acd import services
from apps.acd.models import AgentGroup, AuxCode, Division, PrimaryStatus, Source
from apps.hcm.models import Employee
from apps.scheduling.services import parse_any_date

PERMISSIONS = [IsAuthenticated, PasswordChangeNotRequired, HasActionPermission]
NO_STORE = {"Cache-Control": "no-store"}


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
        if isinstance(exc, services.AcdError):
            return Response({"detail": exc.message, "code": exc.code}, status=exc.status)
        if isinstance(exc, services.AcdErrors):
            return Response({"detail": str(exc), "errors": exc.errors, "code": "invalid"}, status=status.HTTP_400_BAD_REQUEST)
        if isinstance(exc, DatabaseError):
            text = str(exc)
            for number, message in (
                ("50060", "SQL Server rechazó el estado: se traslapa con otro segmento del agente."),
                ("50061", "SQL Server rechazó el estado: el auxiliar no pertenece a ese estado primario."),
                ("50062", "SQL Server rechazó el auxiliar: un sub-auxiliar tiene un solo nivel y el estado de su padre."),
                ("uq_acd_segment_open", "El agente ya tiene un estado abierto (cambio simultáneo): vuelva a intentarlo."),
                ("uq_acd_session_open", "El agente ya tiene una sesión abierta (inicio simultáneo)."),
            ):
                if number in text:
                    return Response({"detail": message, "code": f"sql_{number}"}, status=status.HTTP_409_CONFLICT)
        return super().handle_exception(exc)


def _me(request) -> Employee:
    code = getattr(request.user, "employee_id", None)
    employee = Employee.objects.select_related("country").filter(employee_code=code).first() if code else None
    if employee is None:
        raise services.AcdError("Su cuenta no está vinculada a un empleado: no puede usar la consola de agente.", "no_employee", 403)
    return employee


def _employee(code: str) -> Employee:
    return get_object_or_404(Employee.objects.select_related("country"), employee_code=code.upper())


# ================================================================ catálogos
class CatalogsView(_View):
    method_permissions = {"get": Perm.ACD_VIEW}

    def get(self, request):
        perms = user_permissions(request.user)
        statuses = PrimaryStatus.objects.order_by("sort_order")
        auxes = AuxCode.objects.select_related("primary_status", "parent").order_by("primary_status__sort_order", "sort_order", "name")
        return Response({
            "primary_statuses": [{**services.primary_dict(s), "is_active": s.is_active} for s in statuses],
            "aux_codes": [services.aux_dict(a) for a in auxes],
            "divisions": [{"code": d.code, "name": d.name, "id": str(d.division_uid), "is_active": d.is_active}
                          for d in Division.objects.order_by("name")],
            "groups": [services.group_dict(g) for g in AgentGroup.objects.select_related("division").order_by("name")],
            "intervals": [{"value": "30", "label": "30 minutos"}, {"value": "60", "label": "1 hora"},
                          {"value": "1440", "label": "Día"}, {"value": "range", "label": "Todo el rango"}],
            "report_columns": services.REPORT_COLUMNS,
            "can_manage": Perm.ACD_MANAGE in perms,
        }, headers=NO_STORE)


# ================================================================ consola del agente
class MeView(_View):
    method_permissions = {"get": Perm.ACD_AGENT}

    def get(self, request):
        return Response(services.agent_state(_me(request)), headers=NO_STORE)


class MeLoginView(_View):
    method_permissions = {"post": Perm.ACD_AGENT}

    def post(self, request):
        employee = _me(request)
        services.login(employee, user=request.user)
        return Response({**services.agent_state(employee), "feedback": "Sesión iniciada: está disponible (Available)."})


class MeStatusView(_View):
    method_permissions = {"post": Perm.ACD_AGENT}

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        if not data.get("primary_status"):
            raise ValidationError({"primary_status": "Indique el estado (p. ej. ON_QUEUE, BREAK)."})
        employee = _me(request)
        seg = services.set_status(employee, data.get("primary_status"), data.get("aux_code") or None, user=request.user)
        label = seg.primary_status.label + (f" · {seg.aux_code.full_name}" if seg.aux_code_id else "")
        return Response({**services.agent_state(employee), "feedback": f"Estado: {label}."})


class MeLogoutView(_View):
    method_permissions = {"post": Perm.ACD_AGENT}

    def post(self, request):
        employee = _me(request)
        _, session = services.logout(employee, user=request.user)
        return Response({**services.agent_state(employee),
                         "feedback": f"Sesión cerrada (Offline). Tiempo real: {session.sync_message}",
                         "sync_status": session.sync_status})


# ================================================================ supervisión
class AgentsView(_View):
    method_permissions = {"get": Perm.ACD_VIEW}

    def get(self, request):
        p = request.query_params
        rows = services.board(group=p.get("group", "").strip(), division=p.get("division", "").strip(),
                              status=p.get("status", "").strip(), search=p.get("search", "").strip())
        counts: dict[str, int] = {}
        for r in rows:
            key = r["current"]["primary_label"] if r["current"] else "Offline"
            counts[key] = counts.get(key, 0) + 1
        return Response({"results": rows, "count": len(rows), "by_status": counts,
                         "can_manage": Perm.ACD_MANAGE in user_permissions(request.user)}, headers=NO_STORE)


class AgentLogoutView(_View):
    method_permissions = {"post": Perm.ACD_MANAGE}

    def post(self, request, code: str):
        employee = _employee(code)
        reason = str((request.data or {}).get("reason") or "").strip()[:200] if isinstance(request.data, dict) else ""
        _, session = services.logout(employee, user=request.user, source=Source.SUPERVISOR,
                                     notes=f"Cierre forzado por {request.user.username}" + (f": {reason}" if reason else ""))
        return Response({"feedback": f"Sesión de {employee.employee_code} cerrada. Tiempo real: {session.sync_message}",
                         "sync_status": session.sync_status})


# ================================================================ reporte
class _Echo:
    def write(self, value):
        return value


class ReportView(_View):
    method_permissions = {"get": Perm.ACD_VIEW}

    def get(self, request):
        p = request.query_params
        date_from = parse_any_date(p.get("from"))
        date_to = parse_any_date(p.get("to")) or date_from
        if date_from is None:
            raise ValidationError({"from": "Indique la fecha inicial (AAAA-MM-DD)."})
        result = services.agent_status_report(services.ReportFilters(
            date_from=date_from, date_to=date_to, interval=p.get("interval", "1440"), tz=p.get("tz") or None,
            group=p.get("group", "").strip(), division=p.get("division", "").strip(),
            employee=p.get("employee", "").strip(), primary_status=p.get("status", "").strip(),
        ))
        if p.get("export") == "csv":
            writer = csv.writer(_Echo())

            def stream():
                yield "﻿" + writer.writerow(result["columns"])
                for row in result["rows"]:
                    yield writer.writerow([row[c] for c in result["columns"]])

            response = StreamingHttpResponse(stream(), content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = f'attachment; filename="agent_status_detail_{date_from}_{date_to}.csv"'
            return response
        try:
            page = max(1, int(p.get("page", 1)))
            size = max(1, min(int(p.get("page_size", 100)), 500))
        except ValueError:
            page, size = 1, 100
        rows = result["rows"]
        return Response({**{k: v for k, v in result.items() if k != "rows"}, "count": len(rows),
                         "page": page, "page_size": size, "results": rows[(page - 1) * size: page * size]}, headers=NO_STORE)


# ================================================================ grupos y acceso a auxiliares
class GroupsView(_View):
    method_permissions = {"get": Perm.ACD_VIEW, "post": Perm.ACD_MANAGE}

    def get(self, request):
        groups = AgentGroup.objects.select_related("division").order_by("name")
        return Response({"results": [services.group_dict(g) for g in groups]}, headers=NO_STORE)

    def post(self, request):
        group = services.save_group(request.data if isinstance(request.data, dict) else {}, user=request.user, request=request)
        return Response({"group": services.group_dict(group, with_members=True), "feedback": f"Grupo {group.code} creado."},
                        status=status.HTTP_201_CREATED)


class GroupDetailView(_View):
    method_permissions = {"get": Perm.ACD_VIEW, "patch": Perm.ACD_MANAGE}

    def get(self, request, code: str):
        group = get_object_or_404(AgentGroup.objects.select_related("division"), code=code.upper())
        return Response({"group": services.group_dict(group, with_members=True),
                         "allowed": [services.aux_dict(a) for a in services.allowed_aux_codes(group)]}, headers=NO_STORE)

    def patch(self, request, code: str):
        group = get_object_or_404(AgentGroup.objects.select_related("division"), code=code.upper())
        group = services.save_group(request.data if isinstance(request.data, dict) else {}, group=group, user=request.user, request=request)
        return Response({"group": services.group_dict(group, with_members=True), "feedback": f"Grupo {group.code} actualizado."})


class GroupMembersView(_View):
    method_permissions = {"post": Perm.ACD_MANAGE}

    def post(self, request, code: str):
        group = get_object_or_404(AgentGroup, code=code.upper())
        emp_code = str((request.data or {}).get("employee_code") or "").strip() if isinstance(request.data, dict) else ""
        if not emp_code:
            raise ValidationError({"employee_code": "Indique el ID corporativo del agente."})
        employee = _employee(emp_code)
        services.add_member(group, employee, user=request.user, request=request)
        return Response({"group": services.group_dict(group, with_members=True),
                         "feedback": f"{employee.employee_code} asignado a {group.code}."}, status=status.HTTP_201_CREATED)


class GroupMemberDetailView(_View):
    method_permissions = {"delete": Perm.ACD_MANAGE}

    def delete(self, request, code: str, employee_code: str):
        group = get_object_or_404(AgentGroup, code=code.upper())
        employee = _employee(employee_code)
        services.remove_member(group, employee, user=request.user, request=request)
        return Response({"group": services.group_dict(group, with_members=True),
                         "feedback": f"{employee.employee_code} retirado de {group.code}."})
