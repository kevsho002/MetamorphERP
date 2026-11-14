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

Fase 17 — planificación estilo IEX:
GET    /adherence/grid/filters/                               Management Units, clientes / marcas, líderes por nivel, metadatos
GET    /adherence/grid/?date=&group=&client=&brand=&director=&manager=&supervisor=&team_manager=&search=
                                                              grilla multi-agente: pre-contenedor, segmentos, real, adherencia
GET    /adherence/grid/agent/?employee=&from=&to=             vista histórica del agente (desde su contratación, ≤ 31 días)
GET    /adherence/grid/settings/?group=  ·  PUT               intervalo, ajuste al soltar y margen de la grilla
Fase 18:
GET    /adherence/grid/audit/?employee=&date=                 audit trail de la línea (agente + fecha): cambios del plan con
                                                              antes / después, AP y firmas, roster, sesiones ACD, cálculo
Fase 19:
POST   /adherence/segments/{id}/replace/                      reemplaza un Lateness / ausencia BLOQUEADO con un segmento
                                                              respaldado por AP {activity, folio, start?, end?, scope?}
POST   /adherence/attendance/reconcile/                       {date, filtros de la grilla}: Lateness y Unjustified Absence
GET    /adherence/day/?employee=&date=                        ventana flotante del día (WFM, el agente o su cadena de mando)
GET    /adherence/requests/?status=  ·  POST                  cola de aprobación de WFM (correcciones de segmentos)
POST   /adherence/requests/{id}/decide/  ·  /cancel/          WFM aprueba / rechaza; quien la pidió la anula
GET    /adherence/my-plan/?date=                              autoservicio (lectura): mi día y el de mi equipo
Los tiempos aceptan HH:MM:SS (granularidad al segundo).
Los POST / PATCH / DELETE de segmentos devuelven `refresh`: adherencia en vivo del día y, si ese día ya estaba
guardado para nómina y calidad, se vuelve a guardar con el plan nuevo.
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
from apps.adherence import attendance, audit_trail, change_requests, grid, services
from apps.adherence.models import (
    ICONS, REVIEW_AREAS, ActivityStatusRule, ActivityType, AdherenceException, ChangeRequest, ScheduleSegment,
)
from apps.hcm.models import Employee
from apps.operations.models import Client
from apps.scheduling.services import parse_any_date

PERMISSIONS = [IsAuthenticated, PasswordChangeNotRequired, HasActionPermission]
NO_STORE = {"Cache-Control": "no-store"}
SQL_ERRORS = (
    ("50070", "El sistema rechazó el segmento: se traslapa con otro segmento del agente."),
    ("50071", "El sistema rechazó la justificación: la AP debe estar aprobada y ser del mismo empleado."),
    ("50072", "El sistema rechazó el segmento: la actividad o el cambio exige una AP aprobada del mismo empleado."),
    ("50073", "El sistema rechazó el cambio: el Lateness o la ausencia no se elimina ni se mueve; solo se reemplaza con AP."),
    ("50074", "El sistema rechazó el segmento: las actividades de asistencia solo las inserta el sistema."),
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
            "icons": [{"value": v, "label": label} for v, label in ICONS],
            "utilization_categories": grid.categories(),
            "client_paid": [{"value": v, "label": label} for v, label in ActivityType.ClientPaid.choices],
            "review_areas": [{"value": v, "label": label} for v, label in REVIEW_AREAS],
            "clients": [{"code": c.code, "name": c.name} for c in Client.objects.filter(is_active=True).order_by("name")],
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
        return Response({"segment": services.segment_dict(seg), "refresh": services.refresh_after_plan_change(employee, seg.shift_date, user=request.user),
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
        return Response({"segment": services.segment_dict(seg), "refresh": services.refresh_after_plan_change(seg.employee, seg.shift_date, user=request.user),
                         "feedback": f"{seg.activity.name} movido a {services.hm(seg.start_at)}–{services.hm(seg.end_at)}."})

    def delete(self, request, pk: int):
        seg = self._get(pk)
        employee, d = seg.employee, seg.shift_date
        services.delete_segment(seg, user=request.user, request=request)
        return Response({"feedback": "Segmento eliminado.", "refresh": services.refresh_after_plan_change(employee, d, user=request.user)})


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
        employees = _employees(data)
        if data.get("reconcile", True) and date_from:
            # Fase 19: antes de guardar, la asistencia (Lateness / Unjustified Absence) de los días terminados.
            last = min(date_to or date_from, services.now_local().date() - timedelta(days=1))
            day = date_from
            while day <= last and (day - date_from).days < services.MAX_RANGE_DAYS:
                attendance.reconcile(employees, day, user=request.user, request=request)
                day += timedelta(days=1)
        result = services.compute_and_store(employees, date_from, date_to, user=request.user, request=request)
        return Response({**result, "feedback": f"Adherencia guardada: {result['stored']} días-agente hasta el {result['until']}."})


# ================================================================ Fase 17: planificación estilo IEX
class GridFiltersView(_View):
    method_permissions = {"get": Perm.WFM_VIEW}

    def get(self, request):
        return Response({**grid.filters_payload(), "can_manage": Perm.WFM_MANAGE in user_permissions(request.user)}, headers=NO_STORE)


class GridView(_View):
    method_permissions = {"get": Perm.WFM_VIEW}

    def get(self, request):
        p = request.query_params
        d = parse_any_date(p.get("date"))
        if d is None:
            raise services.AdhErrors({"date": "Indique la fecha del turno (AAAA-MM-DD)."})
        employees, paging = grid.grid_page(p, d)
        data = grid.grid_day(employees, d, p)
        return Response({**data, "paging": paging, "can_manage": Perm.WFM_MANAGE in user_permissions(request.user)},
                        headers=NO_STORE)


class AgentHistoryView(_View):
    method_permissions = {"get": Perm.WFM_VIEW}

    def get(self, request):
        p = request.query_params
        date_from, date_to = _range(p, default_to_from=False)
        data = grid.agent_history(_employee(p.get("employee")), date_from, date_to)
        return Response({**data, "can_manage": Perm.WFM_MANAGE in user_permissions(request.user)}, headers=NO_STORE)


class AuditTrailView(_View):
    method_permissions = {"get": Perm.WFM_VIEW}

    def get(self, request):
        p = request.query_params
        d = parse_any_date(p.get("date"))
        if d is None:
            raise services.AdhErrors({"date": "Indique la fecha del turno (AAAA-MM-DD)."})
        return Response(audit_trail.audit_trail(_employee(p.get("employee")), d), headers=NO_STORE)


class GridSettingView(_View):
    method_permissions = {"get": Perm.WFM_VIEW, "put": Perm.WFM_MANAGE}

    def get(self, request):
        return Response(grid.setting_dict(grid.grid_setting(str(request.query_params.get("group") or ""))), headers=NO_STORE)

    def put(self, request):
        s = grid.save_setting(_data(request), user=request.user)
        return Response({**grid.setting_dict(s), "feedback": "Configuración de la grilla guardada."})


# ================================================================ Fase 19: asistencia, ventana del día y cola de WFM
class _OpenView(_View):
    """Autenticado; el acceso fino (WFM / el propio agente / su cadena de mando) lo decide el servicio."""

    permission_classes = [IsAuthenticated, PasswordChangeNotRequired]


class SegmentReplaceView(_View):
    method_permissions = {"post": Perm.WFM_MANAGE}

    def post(self, request, pk: int):
        seg = get_object_or_404(ScheduleSegment.objects.select_related("employee", "activity"), pk=pk)
        employee, d = seg.employee, seg.shift_date
        new = services.replace_segment(seg, _data(request), user=request.user, request=request)
        return Response({"segment": services.segment_dict(new), "refresh": services.refresh_after_plan_change(employee, d, user=request.user),
                         "feedback": f"Reemplazado por {new.activity.name} {services.hm(new.start_at)}–{services.hm(new.end_at)} "
                                     f"con la AP {new.personnel_action.folio}."})


class ReconcileView(_View):
    method_permissions = {"post": Perm.WFM_MANAGE}

    def post(self, request):
        data = _data(request)
        d = parse_any_date(data.get("date"))
        if d is None:
            raise services.AdhErrors({"date": "Indique la fecha del turno (AAAA-MM-DD)."})
        if data.get("employee"):
            employees = services.select_employees(employee=str(data["employee"]))
        else:
            employees = grid.select_grid_employees(data, d)
        if len(employees) > services.MAX_EMPLOYEES:
            raise services.AdhError(f"Demasiados agentes (máx. {services.MAX_EMPLOYEES}): filtre la grilla.", "too_many")
        out = attendance.reconcile(employees, d, user=request.user, request=request)
        return Response({**out, "feedback": f"Asistencia del {services.fmt(d)}: {out['lateness']} lateness y {out['absences']} "
                                            f"ausencias nuevas; {out['on_leave']} con permiso y {out['inactive']} inactivos separados."})


class DayView(_OpenView):
    def get(self, request):
        p = request.query_params
        d = parse_any_date(p.get("date"))
        if d is None:
            raise services.AdhErrors({"date": "Indique la fecha del turno (AAAA-MM-DD)."})
        return Response(change_requests.day_detail(request.user, _employee(p.get("employee")), d), headers=NO_STORE)


class RequestsView(_OpenView):
    def get(self, request):
        return Response(change_requests.list_requests(request.user, request.query_params), headers=NO_STORE)

    def post(self, request):
        data = _data(request)
        r = change_requests.create_request(request.user, _employee(data.get("employee_code")), data, request=request)
        return Response({"request": change_requests.request_dict(r),
                         "feedback": f"Solicitud #{r.pk} enviada a la cola de aprobación de WFM."}, status=status.HTTP_201_CREATED)


class RequestDecideView(_View):
    method_permissions = {"post": Perm.WFM_MANAGE}

    def post(self, request, pk: int):
        r = get_object_or_404(ChangeRequest, pk=pk)
        out = change_requests.decide(r, _data(request), user=request.user, request=request)
        verb = "aprobada y aplicada" if out["request"]["status"] == "APPROVED" else "rechazada"
        return Response({**out, "feedback": f"Solicitud #{pk} {verb}."})


class RequestCancelView(_OpenView):
    def post(self, request, pk: int):
        r = get_object_or_404(ChangeRequest.objects.select_related("employee"), pk=pk)
        r = change_requests.cancel(r, user=request.user, request=request)
        return Response({"request": change_requests.request_dict(r), "feedback": f"Solicitud #{pk} anulada."})


class MyPlanView(_OpenView):
    def get(self, request):
        d = parse_any_date(request.query_params.get("date")) or services.now_local().date()
        return Response(change_requests.my_plan(request.user, d), headers=NO_STORE)
