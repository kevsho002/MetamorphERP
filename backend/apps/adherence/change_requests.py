"""Fase 19 — Ventana de detalle de un día (agente + fecha) y cola de aprobación de WFM.

Acceso a la ventana flotante de actividad:

    WFM con «wfm.manage»            EDICIÓN: cambia el plan directamente (con AP cuando la regla lo exige)
    WFM con «wfm.view»              LECTURA + solicitud de corrección
    el propio agente                LECTURA + solicitud de corrección (autoservicio)
    su supervisor (cadena de mando  LECTURA + solicitud de corrección para los agentes bajo él en la fecha
    del roster: TM / AS / OM / OD)

Las correcciones de SEGMENTOS entran a la cola de WFM (adh_change_request) y se aplican al aprobarse. Los cambios del
DÍA COMPLETO no pasan por la cola: requieren el flujo de AP (Acciones de personal) y luego WFM los coloca con su folio.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.permissions import user_permissions
from apps.accounts.roles import Perm
from apps.adherence import attendance
from apps.adherence.models import ActivityType, ChangeRequest, ScheduleSegment
from apps.adherence.services import (
    MIN_SEGMENT_SECONDS, AdhError, AdhErrors, _activity, _closed, _containers, _parse_clock, _seg_snapshot, activity_dict, ap_reason,
    attendance_setting, backing_ap, check_duration_kind, delete_segment, employee_dict, fmt, fmt_duration, hm, is_full_day, iso,
    planner_day, refresh_after_plan_change, replace_segment, resolve_times, save_segment,
)
from apps.hcm.models import Employee
from apps.operations import hierarchy
from apps.operations.models import OperationalLeader
from apps.scheduling.services import ScheduleBook, parse_any_date
from apps.system.audit import Category, record

EDIT, REQUEST = "edit", "request"
MAX_LIST = 500


# ============================================================================ acceso
def user_employee(user) -> Employee | None:
    code = getattr(user, "employee_id", None)
    return Employee.objects.filter(employee_code=code).first() if code else None


def subordinates(user, d: date) -> set[int]:
    """Agentes bajo los roles de líder del usuario (cadena de mando del roster) en la fecha."""
    me = user_employee(user)
    if me is None:
        return set()
    out: set[int] = set()
    for lead in OperationalLeader.objects.filter(employee=me, is_active=True):
        out |= hierarchy.employees_under(lead.level, me.employee_code, d)
    return out


def access(user, employee: Employee, d: date) -> tuple[str | None, str | None]:
    """(modo, rol): modo = edit | request | None (sin acceso)."""
    perms = user_permissions(user)
    if Perm.WFM_MANAGE in perms:
        return EDIT, ChangeRequest.Requester.WFM
    if Perm.WFM_VIEW in perms:
        return REQUEST, ChangeRequest.Requester.WFM
    me = user_employee(user)
    if me is not None and me.pk == employee.pk:
        return REQUEST, ChangeRequest.Requester.AGENT
    if employee.pk in subordinates(user, d):
        return REQUEST, ChangeRequest.Requester.SUPERVISOR
    return None, None


def require_access(user, employee: Employee, d: date) -> tuple[str, str]:
    mode, role = access(user, employee, d)
    if mode is None:
        raise AdhError("Solo WFM, el propio agente o su cadena de mando (roster) pueden ver el plan de este agente.", "forbidden", 403)
    return mode, role


# ============================================================================ ventana de detalle
def request_dict(r: ChangeRequest) -> dict:
    a = r.activity
    return {
        "id": r.pk, "employee_code": r.employee.employee_code, "full_name": r.employee.full_name, "shift_date": r.shift_date.isoformat(),
        "kind": r.kind, "kind_label": r.get_kind_display(), "status": r.status, "status_label": r.get_status_display(),
        "segment_id": r.segment_id, "before": r.before,
        "activity": a.code if a else None, "activity_name": a.name if a else None, "color": a.color if a else None,
        "icon": a.icon if a else None, "start": iso(r.start_at), "end": iso(r.end_at),
        "seconds": int((r.end_at - r.start_at).total_seconds()) if r.start_at and r.end_at else None,
        "folio": r.personnel_action.folio if r.personnel_action_id else None, "notes": r.notes, "reason": r.reason,
        "requester_role": r.requester_role, "requester_role_label": r.get_requester_role_display(),
        "requested_by": r.requested_by.username if r.requested_by_id else None, "requested_at": r.requested_at.isoformat(),
        "decided_by": r.decided_by.username if r.decided_by_id else None,
        "decided_at": r.decided_at.isoformat() if r.decided_at else None, "decision_comment": r.decision_comment,
        "applied_segment_id": r.applied_segment_id,
    }


def _requests_qs():
    return ChangeRequest.objects.select_related("employee", "activity", "personnel_action", "requested_by", "decided_by")


def day_detail(user, employee: Employee, d: date) -> dict:
    """Ventana flotante: tabla del día (actividad, inicio, fin, notas / observaciones, respaldo) y la cola del día."""
    mode, role = require_access(user, employee, d)
    row = planner_day([employee], d)["rows"][0]
    segs = {s["id"]: s for s in row["segments"]}
    table = []
    for b in row["plan"]:
        s = segs.get(b["segment_id"]) if b["segment_id"] else None
        table.append({
            "kind": "segment" if s else "container", "segment_id": b["segment_id"], "activity": b["activity"],
            "activity_name": b["activity_name"], "icon": b["icon"], "color": b["color"], "start": b["start"], "end": b["end"],
            "seconds": b["seconds"], "is_paid": b["is_paid"], "notes": s["notes"] if s else "",
            "category": s["utilization_category"] if s else None, "origin": s["origin"] if s else None,
            "origin_label": s["origin_label"] if s else "Resto del turno (actividad predeterminada)",
            "folio": s["folio"] if s else None, "is_locked": s["is_locked"] if s else False,
            "system_role": s["system_role"] if s else None, "requires_ap": s["requires_ap"] if s else False,
            "created_by": s["created_by"] if s else None,
        })
    setting = attendance_setting(employee)
    pending = [request_dict(r) for r in _requests_qs().filter(employee=employee, shift_date=d).order_by("-requested_at")[:50]]
    return {
        **employee_dict(employee), "date": d.isoformat(), "mode": mode, "role": role, "role_label": ChangeRequest.Requester(role).label,
        "containers": row["containers"], "table": table, "warnings": row["warnings"],
        "attendance": attendance.day_status(row["segments"], row["containers"]),
        "requests": pending,
        "policy": {"ap_required_seconds": setting.ap_required_seconds, "lateness_grace_seconds": setting.lateness_grace_seconds},
        "activities": [activity_dict(a) for a in ActivityType.objects.select_related("utilization_category")
                       .prefetch_related("status_rules__primary_status", "status_rules__aux_code", "clients")
                       .filter(is_active=True, system_role="")],
    }


# ============================================================================ cola: solicitar
def _proposal(employee: Employee, d: date, data: dict, *, kind: str, segment: ScheduleSegment | None):
    """Valida la propuesta (actividad, horas, reglas de AP). Devuelve (actividad, inicio, fin, AP)."""
    activity = _activity(data.get("activity")) if data.get("activity") or segment is None else segment.activity
    start = _parse_clock(data.get("start"), "start") if data.get("start") or segment is None else segment.start_at.time()
    end = _parse_clock(data.get("end"), "end") if data.get("end") or segment is None else segment.end_at.time()
    if start == end:
        raise AdhErrors({"end": "El fin debe ser distinto del inicio."})
    book = ScheduleBook([employee.pk], d, d)
    containers = _containers(book, employee.pk, d, d)
    if not containers:
        raise AdhError(f"{employee.employee_code} no tiene turno el {fmt(d)}.", "no_container")
    s, e, container = resolve_times(d, start, end, containers)
    if (e - s).total_seconds() < (1 if segment is not None and segment.is_locked else MIN_SEGMENT_SECONDS):
        raise AdhErrors({"end": f"Un segmento dura al menos {fmt_duration(MIN_SEGMENT_SECONDS)}."})
    if is_full_day(s, e, container):
        raise AdhError("Los cambios del día completo no pasan por la cola de WFM: requieren el flujo de AP (Acciones de "
                       "personal). Con la AP aprobada, WFM coloca el día con su folio.", "ap_flow_required", 409)
    check_duration_kind(activity, s, e, container)
    pa = backing_ap(employee, data.get("folio")) if data.get("folio") else None
    if segment is not None and segment.is_locked:
        if not (segment.start_at <= s < e <= segment.end_at):
            raise AdhErrors({"start": f"El reemplazo debe quedar dentro de {hm(segment.start_at)}–{hm(segment.end_at)}."})
        if pa is None:
            raise AdhError(f"{segment.activity.name} solo se reemplaza con un segmento respaldado: indique el folio de la AP aprobada "
                           "(justificación).", "ap_required", 409)
    reason = ap_reason(activity, s, e, container, attendance_setting(employee))
    if reason and pa is None:
        raise AdhError(f"{reason} Indique el folio de la AP aprobada en la solicitud.", "ap_required", 409)
    return activity, s, e, pa


@transaction.atomic
def create_request(user, employee: Employee, data: dict, *, request=None) -> ChangeRequest:
    d = parse_any_date(data.get("shift_date"))
    if d is None:
        raise AdhErrors({"shift_date": "Indique la fecha del turno."})
    _, role = require_access(user, employee, d)
    kind = str(data.get("kind") or "").upper()
    if kind not in ChangeRequest.Kind.values:
        raise AdhErrors({"kind": "Tipo: ADD (agregar), CHANGE (cambiar) o DELETE (quitar)."})
    reason = str(data.get("reason") or "").strip()[:500]
    if len(reason) < 5:
        raise AdhErrors({"reason": "Describa el motivo de la corrección (observaciones para WFM)."})
    segment = None
    if kind != ChangeRequest.Kind.ADD:
        segment = (ScheduleSegment.objects.select_related("activity", "personnel_action")
                   .filter(pk=data.get("segment_id") or 0, employee=employee, shift_date=d).first())
        if segment is None:
            raise AdhErrors({"segment_id": "Elija un segmento del agente en esa fecha."})
        if _requests_qs().filter(segment=segment, status=ChangeRequest.Status.PENDING).exists():
            raise AdhError("Ya hay una solicitud pendiente para ese segmento en la cola de WFM.", "duplicate", 409)
    activity = s = e = pa = None
    if kind == ChangeRequest.Kind.DELETE:
        if segment.is_locked:
            raise AdhError(f"{segment.activity.name} no se puede quitar: solicite su REEMPLAZO con el folio de una AP aprobada.",
                           "locked", 409)
        _closed(employee, segment.start_at.date(), segment.end_at.date(), "corregir segmentos")
    else:
        activity, s, e, pa = _proposal(employee, d, data, kind=kind, segment=segment)
        _closed(employee, s.date(), e.date(), "corregir segmentos")
    r = ChangeRequest.objects.create(
        employee=employee, shift_date=d, kind=kind, segment=segment, activity=activity, start_at=s, end_at=e, personnel_action=pa,
        notes=str(data.get("notes") or "")[:200], reason=reason, before=_seg_snapshot(segment) if segment else None,
        requester_role=role, requested_by=user if getattr(user, "pk", None) else None,
    )
    what = {"ADD": f"agregar {activity.name if activity else ''} {hm(s) if s else ''}–{hm(e) if e else ''}",
            "CHANGE": f"cambiar {segment.activity.name if segment else ''} a {activity.name if activity else ''} {hm(s) if s else ''}–{hm(e) if e else ''}",
            "DELETE": f"quitar {segment.activity.name if segment else ''}"}[kind]
    record("adh_request_created", Category.WFM,
           f"Solicitud #{r.pk} a la cola de WFM ({r.get_requester_role_display().lower()}): {what.strip()} el {fmt(d)} para "
           f"{employee.employee_code}. Motivo: {reason}", request=request, actor=user, target=employee,
           details={"shift_date": d.isoformat(), "shift_dates": [d.isoformat()], "request_id": r.pk, "kind": kind,
                    "segment_id": segment.pk if segment else None, "folio": pa.folio if pa else None,
                    "before": r.before, "after": request_dict(r) if kind != "DELETE" else None})
    return r


# ============================================================================ cola: resolver
def _hms(dt) -> str:
    return f"{dt:%H:%M:%S}"


@transaction.atomic
def decide(r: ChangeRequest, data: dict, *, user=None, request=None) -> dict:
    """WFM aprueba (se aplica al plan con origen «solicitud aprobada») o rechaza con comentario."""
    r = _requests_qs().select_for_update().get(pk=r.pk)
    if r.status != ChangeRequest.Status.PENDING:
        raise AdhError(f"La solicitud #{r.pk} ya está «{r.get_status_display()}».", "not_pending", 409)
    decision = str(data.get("decision") or "").upper()
    comment = str(data.get("comment") or "").strip()[:500]
    if decision not in ("APPROVE", "REJECT"):
        raise AdhErrors({"decision": "Decisión: APPROVE o REJECT."})
    employee, d = r.employee, r.shift_date
    refresh = None
    if decision == "REJECT":
        if not comment:
            raise AdhErrors({"comment": "Indique el motivo del rechazo para el solicitante."})
        r.status = ChangeRequest.Status.REJECTED
    else:
        if r.requested_by_id and getattr(user, "pk", None) == r.requested_by_id:
            raise AdhError("No puede aprobar su propia solicitud: la aprueba otro usuario de WFM.", "self_approval", 403)
        payload = {"shift_date": d.isoformat(), "notes": r.notes or (r.before or {}).get("notes", "")}
        if r.activity_id:
            payload |= {"activity": r.activity.code, "start": _hms(r.start_at), "end": _hms(r.end_at)}
        if r.personnel_action_id:
            payload["folio"] = r.personnel_action.folio
        origin = ScheduleSegment.Origin.REQUEST
        if r.kind == ChangeRequest.Kind.ADD:
            seg = save_segment(employee, payload, user=user, request=request, origin=origin)
        else:
            seg = ScheduleSegment.objects.select_related("activity", "employee", "personnel_action").filter(pk=r.segment_id).first()
            if seg is None:
                raise AdhError("El segmento de la solicitud ya no existe (el plan cambió): rechácela.", "segment_gone", 409)
            if r.kind == ChangeRequest.Kind.DELETE:
                delete_segment(seg, user=user, request=request, via_request=True)
                seg = None
            elif seg.is_locked:
                seg = replace_segment(seg, payload, user=user, request=request, origin=origin)
            else:
                seg = save_segment(employee, payload, segment=seg, user=user, request=request, origin=origin)
        r.status, r.applied_segment_id = ChangeRequest.Status.APPROVED, seg.pk if seg else None
        refresh = refresh_after_plan_change(employee, d, user=user)
    r.decided_by, r.decided_at, r.decision_comment = (user if getattr(user, "pk", None) else None), timezone.now(), comment
    r.save(update_fields=["status", "decided_by", "decided_at", "decision_comment", "applied_segment_id"])
    verb = "aprobada y aplicada al plan" if r.status == ChangeRequest.Status.APPROVED else "rechazada"
    record(f"adh_request_{'approved' if decision == 'APPROVE' else 'rejected'}", Category.WFM,
           f"Solicitud #{r.pk} ({r.get_kind_display().lower()}) del {fmt(d)} para {employee.employee_code} {verb}"
           + (f": «{comment}»" if comment else "") + ".", request=request, actor=user, target=employee,
           details={"shift_date": d.isoformat(), "shift_dates": [d.isoformat()], "request_id": r.pk, "segment_id": r.applied_segment_id,
                    "requested_by": r.requested_by.username if r.requested_by_id else None})
    return {"request": request_dict(r), "refresh": refresh}


@transaction.atomic
def cancel(r: ChangeRequest, *, user=None, request=None) -> ChangeRequest:
    if r.status != ChangeRequest.Status.PENDING:
        raise AdhError(f"La solicitud #{r.pk} ya está «{r.get_status_display()}».", "not_pending", 409)
    if r.requested_by_id != getattr(user, "pk", None):
        raise AdhError("Solo quien hizo la solicitud puede anularla.", "forbidden", 403)
    r.status, r.decided_at = ChangeRequest.Status.CANCELLED, timezone.now()
    r.save(update_fields=["status", "decided_at"])
    record("adh_request_cancelled", Category.WFM, f"Solicitud #{r.pk} del {fmt(r.shift_date)} anulada por quien la pidió.",
           request=request, actor=user, target=r.employee,
           details={"shift_date": r.shift_date.isoformat(), "shift_dates": [r.shift_date.isoformat()], "request_id": r.pk})
    return r


def list_requests(user, params) -> dict:
    """WFM ve toda la cola; el agente y el supervisor, las solicitudes que hicieron o que son sobre ellos."""
    perms = user_permissions(user)
    qs = _requests_qs()
    if Perm.WFM_VIEW not in perms:
        me = user_employee(user)
        qs = qs.filter(Q(requested_by=user) | Q(employee=me) if me else Q(requested_by=user))
    status = str(params.get("status") or "").upper()
    if status in ChangeRequest.Status.values:
        qs = qs.filter(status=status)
    if params.get("employee"):
        qs = qs.filter(employee__employee_code=str(params["employee"]).strip().upper())
    d_from, d_to = parse_any_date(params.get("from")), parse_any_date(params.get("to"))
    if d_from:
        qs = qs.filter(shift_date__gte=d_from)
    if d_to:
        qs = qs.filter(shift_date__lte=d_to)
    rows = [request_dict(r) for r in qs.order_by("status", "-requested_at")[:MAX_LIST]]
    pending = ChangeRequest.objects.filter(status=ChangeRequest.Status.PENDING)
    return {"results": rows, "pending": pending.count() if Perm.WFM_VIEW in perms else sum(1 for r in rows if r["status"] == "PENDING"),
            "can_decide": Perm.WFM_MANAGE in perms}


# ============================================================================ mi plan / mi equipo
def my_plan(user, d: date) -> dict:
    """Autoservicio (modo lectura): el día del agente y, si es líder en el roster, el de los agentes bajo su mando."""
    from apps.adherence import grid

    me = user_employee(user)
    team_ids = subordinates(user, d)
    ids = ([me.pk] if me else []) + sorted(team_ids - ({me.pk} if me else set()))
    employees = sorted(Employee.objects.filter(pk__in=ids),
                       key=lambda e: (not (me and e.pk == me.pk), e.last_name, e.first_name, e.employee_code))
    data = grid.grid_day(employees, d, {}) if employees else {"rows": [], "grid": None, "status_colors": {}, "summary": None}
    for row in data.get("rows", []):
        row["is_me"] = bool(me and row["employee_code"] == me.employee_code)
    return {**data, "date": d.isoformat(), "me": me.employee_code if me else None, "is_leader": bool(team_ids),
            "team_size": len(team_ids), "can_manage": False, "toolbox": [],
            "previous": (d - timedelta(days=1)).isoformat(), "next": (d + timedelta(days=1)).isoformat()}
