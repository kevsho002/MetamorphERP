"""Fase 22 — Justificaciones y permisos dentro del módulo regular de Acciones de Personal.

Al APROBARSE una AP con efecto:

* JUSTIFY (Justificación de tiempo): la ventana «desde – hasta» del día efectivo queda justificada en la adherencia
  (adh_exception, pagada o no) y, si la AP indica la actividad (sub-segmento del Time Utilization), la grilla IEX
  coloca ese segmento respaldado por la AP (reemplaza lo que hubiera en la ventana, incluso Lateness / ausencia).
* LEAVE (Permiso con / sin goce): para cada día laborable del rango, el turno COMPLETO (o la ventana por horas) se
  cubre con la actividad del permiso (Paid / Unpaid Time Off) y queda justificado. Con goce: las horas se pagan como
  programadas; sin goce: no se pagan pero tampoco cuentan como Unjustified Absence ni Lateness.

Impacto: WFM (no hay Out of Adherence ni ausencia), cálculo de horas (paid_valid de la adherencia y respaldo de la
planilla sin adherencia guardada), grilla de segmentos y nómina.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from django.db import transaction

from apps.adherence import engine
from apps.adherence.models import ActivityType, AdherenceException, ScheduleSegment
from apps.adherence.services import (
    AdhError, _containers, fmt, hm, now_local, refresh_after_plan_change, resolve_times, unlocked_segments,
)
from apps.personnel_actions.dynamic_fields import parse_time
from apps.scheduling.services import ScheduleBook, closed_cutoff_hit
from apps.system.audit import Category, record

MAX_LEAVE_DAYS = 31
SCOPE_DAY, SCOPE_HOURS = "DIA", "HORAS"


@dataclass
class TimeRequest:
    start_date: date
    end_date: date
    scope: str
    start: object | None  # datetime.time
    end: object | None
    activity: ActivityType | None
    paid: bool
    reason: str
    errors: list[tuple[str | None, str]] = field(default_factory=list)


def _get(values: dict, key: str):
    v = values.get(key)
    if v is None:
        return None
    # values puede traer (attr, valor) [validación] o ActionValue [aplicación]
    return v[1] if isinstance(v, tuple) else v.value


def read_request(effect: str, values: dict, effective_date: date) -> TimeRequest:
    code = _get(values, "actividad")
    activity = ActivityType.objects.filter(code=code).first() if code else None
    start, end = parse_time(_get(values, "desde")), parse_time(_get(values, "hasta"))
    motivo = _get(values, "motivo")
    if effect == "LEAVE":
        scope = (_get(values, "alcance") or SCOPE_DAY).upper()
        last = _get(values, "fecha_fin") or effective_date
        paid = activity.is_paid if activity else False
    else:
        scope, last = SCOPE_HOURS, effective_date
        flag = _get(values, "pagado")
        paid = bool(flag) if flag is not None else (activity.is_paid if activity else True)
    reason = str(motivo or (activity.name if activity else "Justificación")).strip()
    req = TimeRequest(effective_date, last, scope, start, end, activity, paid, reason)
    if last < effective_date:
        req.errors.append(("values.fecha_fin", "La fecha final no puede ser anterior a la fecha efectiva."))
    elif (last - effective_date).days + 1 > MAX_LEAVE_DAYS:
        req.errors.append(("values.fecha_fin", f"Un permiso cubre como máximo {MAX_LEAVE_DAYS} días; elabore otra AP para el resto."))
    if scope not in (SCOPE_DAY, SCOPE_HOURS):
        req.errors.append(("values.alcance", "Elija «Día laborable completo» o «Por horas»."))
    if scope == SCOPE_HOURS:
        if start is None:
            req.errors.append(("values.desde", "Indique la hora de inicio (HH:MM)."))
        if end is None:
            req.errors.append(("values.hasta", "Indique la hora de fin (HH:MM)."))
        if start is not None and start == end:
            req.errors.append(("values.hasta", "La hora de fin debe ser distinta del inicio."))
    if activity is not None:
        if scope == SCOPE_DAY and not activity.allows_full_day:
            req.errors.append(("values.actividad", f"{activity.name} no puede cubrir el día completo del turno."))
        if scope == SCOPE_HOURS and not activity.allows_partial:
            req.errors.append(("values.actividad", f"{activity.name} solo se programa para el día completo."))
    if effect == "LEAVE" and activity is None:
        req.errors.append(("values.actividad", "Elija el tipo de permiso (actividad del Time Utilization)."))
    return req


def _windows(req: TimeRequest, d: date, containers) -> list[tuple[datetime, datetime, engine.Container]]:
    if req.scope == SCOPE_DAY:
        return [(c.start, c.end, c) for c in containers]
    return [resolve_times(d, req.start, req.end, containers)]


def preview(employee, effect: str, values: dict, effective_date: date) -> tuple[TimeRequest, dict]:
    """Validación previa: errores de la solicitud y días laborables que cubre (para el aviso del formulario)."""
    req = read_request(effect, values, effective_date)
    info = {"workdays": [], "rest_days": [], "closed": [], "outside": []}
    if req.errors:
        return req, info
    book = ScheduleBook([employee.pk], req.start_date - timedelta(days=1), req.end_date + timedelta(days=1))
    d = req.start_date
    while d <= req.end_date:
        containers = _containers(book, employee.pk, d, d)
        if not containers:
            info["rest_days"].append(d)
        elif closed_cutoff_hit(employee, d, d):
            info["closed"].append(d)
        else:
            try:
                _windows(req, d, containers)
                info["workdays"].append(d)
            except AdhError:
                info["outside"].append(d)
        d += timedelta(days=1)
    return req, info


def _place(employee, d: date, s: datetime, e: datetime, activity: ActivityType, action, book: ScheduleBook,
           container: engine.Container, user) -> ScheduleSegment:
    """Coloca la actividad de la AP en [s, e): recorta / reemplaza lo que hubiera (incluidos los bloqueados)."""
    overlapping = list(ScheduleSegment.objects.filter(employee=employee, start_at__lt=e, end_at__gt=s))
    keep = []
    for x in overlapping:
        for a, b in ((x.start_at, s), (e, x.end_at)):
            if b > a:
                keep.append((x, a, b))
    with unlocked_segments():
        for x in overlapping:
            x.delete()
        for x, a, b in keep:
            ScheduleSegment.objects.create(employee=employee, shift_date=x.shift_date, assignment_id=x.assignment_id,
                                           activity_id=x.activity_id, start_at=a, end_at=b, notes=x.notes, origin=x.origin,
                                           personnel_action_id=x.personnel_action_id, is_locked=x.is_locked,
                                           created_by_id=x.created_by_id)
    assignment = next((a for a in book.assignments_on(employee.pk, d) if a.label == container.label), None)
    return ScheduleSegment.objects.create(
        employee=employee, shift_date=d, assignment=assignment, activity=activity, start_at=s, end_at=e,
        notes=f"AP {action.folio}"[:200], origin=ScheduleSegment.Origin.SYSTEM, personnel_action=action,
        created_by=user if getattr(user, "pk", None) else None,
    )


@transaction.atomic
def apply(action, values: dict, *, user=None) -> str:
    """Aplica la justificación / el permiso de una AP aprobada. Devuelve el resumen para la auditoría."""
    employee = action.employee
    effect = action.action_type.effect
    req = read_request(effect, values, action.effective_date)
    if req.errors:
        return f"AP {action.folio} aprobada sin ventana de tiempo aplicable: {req.errors[0][1]}"
    book = ScheduleBook([employee.pk], req.start_date - timedelta(days=1), req.end_date + timedelta(days=1))
    placed, rest, closed, outside, seconds = [], [], [], [], 0
    today = now_local().date()
    d = req.start_date
    while d <= req.end_date:
        containers = _containers(book, employee.pk, d, d)
        if not containers:
            rest.append(d)
        elif closed_cutoff_hit(employee, d, d):
            closed.append(d)
        else:
            try:
                windows = _windows(req, d, containers)
            except AdhError:
                outside.append(d)
                windows = []
            for s, e, c in windows:
                if req.activity is not None:
                    _place(employee, d, s, e, req.activity, action, book, c, user)
                AdherenceException.objects.create(
                    employee=employee, personnel_action=action, start_at=s, end_at=e, is_paid=req.paid,
                    reason=f"{action.action_type.name}: {req.reason}"[:200], created_by=user if getattr(user, "pk", None) else None)
                seconds += int((e - s).total_seconds())
            if windows:
                placed.append(d)
                if d < today:
                    refresh_after_plan_change(employee, d, user=user)
        d += timedelta(days=1)
    what = req.activity.name if req.activity else "Justificación"
    parts = [f"{what} ({'con goce' if req.paid else 'sin goce'}) aplicado(a) por la AP {action.folio} a {employee.employee_code}: "
             f"{len(placed)} día(s) laborable(s), {seconds // 3600} h {seconds % 3600 // 60:02d} min justificados"]
    if req.scope == SCOPE_HOURS and req.start:
        parts.append(f"ventana {req.start:%H:%M}–{req.end:%H:%M}")
    if rest:
        parts.append(f"{len(rest)} día(s) de descanso sin turno")
    if closed:
        parts.append("cortes cerrados (no se aplicó): " + ", ".join(fmt(x) for x in closed))
    if outside:
        parts.append("ventana fuera del turno: " + ", ".join(fmt(x) for x in outside))
    summary = "; ".join(parts) + "."
    record("adh_ap_time_applied", Category.WFM, summary[:500], actor=user, target=employee,
           details={"folio": action.folio, "effect": effect, "paid": req.paid, "seconds": seconds,
                    "activity": req.activity.code if req.activity else None,
                    "shift_dates": [x.isoformat() for x in placed], "closed": [x.isoformat() for x in closed]})
    return summary


__all__ = ["apply", "preview", "read_request", "hm"]
