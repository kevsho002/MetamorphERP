"""Fase 19 — Asistencia automática sobre el plan de WFM.

* LATENESS: si el agente inicia sesión en el ACD / Web Timer después de la entrada programada (+ tolerancia de su
  Management Unit), el sistema inserta un segmento «Lateness» BLOQUEADO que cubre el retraso (al segundo). No se elimina
  ni se mueve: solo se REEMPLAZA con un segmento respaldado por una AP aprobada (services.replace_segment). Se detecta al
  iniciar sesión (acd.services.login) y, para días ya terminados, al conciliar la asistencia.
* UNJUSTIFIED ABSENCE (no-show): si en todo el bloque del turno no hubo sesión ACD, el contenedor se marca como
  «Unjustified Absence» salvo un bloque predeterminado de «Legal Benefit Lunch» (donde estaba el almuerzo o al centro
  del turno, con la duración del almuerzo del horario). Así la dotación y la proyección de WFM no se distorsionan.
* Se mantiene SEPARADO el personal inactivo (no activo, aún no contratado o dado de baja en la fecha) y el que tiene
  permiso / licencia (justificación por AP o segmentos sin sesión que cubren el turno): no se marcan como ausentes.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.acd.models import StatusSegment
from apps.adherence import engine
from apps.adherence.models import ActivityType, AdherenceException, ScheduleSegment
from apps.adherence.services import (
    _containers, _seg_snapshot, attendance_setting, aware, fmt, fmt_duration, hm, iso, local_naive, now_local,
)
from apps.hcm.models import Employee
from apps.scheduling.services import ScheduleBook, closed_cutoff_hit
from apps.system.audit import Category, record

log = logging.getLogger(__name__)
SYSTEM = ScheduleSegment.Origin.SYSTEM
ABSENCE_ROLES = (ActivityType.SystemRole.ABSENCE, ActivityType.SystemRole.LEGAL_LUNCH)


def system_activity(role: str) -> ActivityType | None:
    return ActivityType.objects.filter(system_role=role, is_active=True).first()


def is_inactive(employee: Employee, d: date) -> bool:
    """Personal inactivo en la fecha: no activo, aún no contratado o dado de baja."""
    if employee.employment_status != Employee.Status.ACTIVE:
        return True
    if employee.hire_date and d < employee.hire_date:
        return True
    return bool(employee.termination_date and d > employee.termination_date)


def _logged(employee: Employee, lo: datetime, hi: datetime) -> list[tuple[datetime, datetime]]:
    """Tramos con sesión iniciada (estado con login) que tocan [lo, hi), en hora local al segundo."""
    now = now_local()
    qs = (StatusSegment.objects.filter(employee=employee, primary_status__is_logged_in=True, start_at__lt=aware(hi))
          .filter(Q(end_at__isnull=True) | Q(end_at__gt=aware(lo))).order_by("start_at"))
    out = []
    for seg in qs:
        a = local_naive(seg.start_at)
        b = local_naive(seg.end_at) if seg.end_at else now
        if b > lo and a < hi and b > a:
            out.append((a, b))
    return out


def _free(lo: datetime, hi: datetime, taken: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """[lo, hi) menos los tramos ocupados (ordenados o no)."""
    out, cursor = [], lo
    for a, b in sorted(taken):
        if b <= cursor or a >= hi:
            continue
        if a > cursor:
            out.append((cursor, min(a, hi)))
        cursor = max(cursor, b)
    if cursor < hi:
        out.append((cursor, hi))
    return [(a, b) for a, b in out if (b - a).total_seconds() >= 1]


def _segments_in(employee: Employee, c: engine.Container) -> list[ScheduleSegment]:
    return list(ScheduleSegment.objects.filter(employee=employee, start_at__lt=c.end, end_at__gt=c.start)
                .select_related("activity", "personnel_action").order_by("start_at"))


def _on_leave(employee: Employee, c: engine.Container, segs: list[ScheduleSegment]) -> bool:
    """Permiso / licencia: una justificación por AP o segmentos que no exigen sesión cubren TODO el bloque."""
    if AdherenceException.objects.filter(employee=employee, start_at__lte=c.start, end_at__gte=c.end).exists():
        return True
    no_login = [(s.start_at, s.end_at) for s in segs if not s.activity.requires_acd_login and not s.activity.system_role]
    return bool(no_login) and not _free(c.start, c.end, no_login)


def _assignment_id(book: ScheduleBook, employee: Employee, c: engine.Container):
    a = next((x for x in book.assignments_on(employee.pk, c.shift_date) if x.label == c.label), None)
    return a.pk if a else None


# ============================================================================ lateness
def _insert_lateness(employee: Employee, c: engine.Container, login: datetime, *, book: ScheduleBook, user=None,
                     source: str = "acd") -> list[ScheduleSegment]:
    lateness = system_activity(ActivityType.SystemRole.LATENESS)
    if lateness is None or is_inactive(employee, c.shift_date):
        return []
    setting = attendance_setting(employee)
    login = login.replace(microsecond=0)
    if not (c.start + timedelta(seconds=setting.lateness_grace_seconds) < login < c.end):
        return []
    if ScheduleSegment.objects.filter(employee=employee, activity__system_role__in=[ActivityType.SystemRole.LATENESS, *ABSENCE_ROLES],
                                      start_at__lt=c.end, end_at__gt=c.start).exists():
        return []  # ya detectado (o el día ya se marcó como ausencia)
    if _logged(employee, c.start, login):
        return []  # ya había iniciado sesión antes dentro del turno: no es llegada tarde
    if closed_cutoff_hit(employee, c.start.date(), login.date()):
        return []
    segs = _segments_in(employee, engine.Container(c.shift_date, c.start, login))
    if any(not s.activity.requires_acd_login for s in segs if s.start_at <= c.start):
        return []  # el turno empieza con un permiso / actividad sin sesión
    pieces = _free(c.start, login, [(s.start_at, s.end_at) for s in segs])
    if not pieces:
        return []
    late = int((login - c.start).total_seconds())
    note = f"Inicio de sesión ACD {hm(login)} · entrada {hm(c.start)} · tolerancia {fmt_duration(setting.lateness_grace_seconds)}"
    created = [ScheduleSegment.objects.create(employee=employee, shift_date=c.shift_date, assignment_id=_assignment_id(book, employee, c),
                                              activity=lateness, start_at=a, end_at=b, notes=note[:200], origin=SYSTEM, is_locked=True)
               for a, b in pieces]
    record("adh_lateness_detected", Category.WFM,
           f"Lateness de {fmt_duration(late)} el {fmt(c.shift_date)} para {employee.employee_code}: entrada {hm(c.start)}, inicio de "
           f"sesión {hm(login)} ({'ACD / Web Timer' if source == 'acd' else 'conciliación de asistencia'}).", actor=user, target=employee,
           details={"shift_date": c.shift_date.isoformat(), "shift_dates": [c.shift_date.isoformat()], "segment_id": created[0].pk,
                    "segment_ids": [x.pk for x in created], "login": iso(login), "late_seconds": late, "before": None,
                    "after": _seg_snapshot(created[0])})
    return created


def detect_lateness(employee: Employee, *, login_at: datetime, user=None) -> list[ScheduleSegment]:
    """Al iniciar sesión en el ACD: inserta el Lateness si la sesión empieza después de la entrada del bloque en curso."""
    login = local_naive(login_at) if timezone.is_aware(login_at) else login_at.replace(microsecond=0)
    out = []
    for d in (login.date() - timedelta(days=1), login.date()):
        book = ScheduleBook([employee.pk], d, d)
        for c in _containers(book, employee.pk, d, d):
            if c.shift_date == d and c.start < login < c.end:
                out += _insert_lateness(employee, c, login, book=book, user=user)
    return out


def detect_lateness_safely(employee: Employee, *, login_at: datetime, user=None) -> int:
    """Gancho del login del ACD: un error de WFM nunca impide iniciar sesión (queda en el log)."""
    try:
        with transaction.atomic():
            return len(detect_lateness(employee, login_at=login_at, user=user))
    except Exception:  # noqa: BLE001 - el login del agente no depende del plan
        log.exception("No se pudo evaluar el lateness de %s", employee.employee_code)
        return 0


# ============================================================================ ausencia (no-show)
def _legal_lunch_window(c: engine.Container, free: list[tuple[datetime, datetime]], seconds: int,
                        preferred: datetime | None) -> tuple[datetime, datetime] | None:
    dur = timedelta(seconds=seconds)
    mid = c.start + (c.end - c.start - dur) / 2
    mid = mid.replace(second=0, microsecond=0)
    for start in [p for p in (preferred, mid) if p is not None]:
        if any(a <= start and start + dur <= b for a, b in free):
            return start, start + dur
    fits = [(a, b) for a, b in free if b - a >= dur]
    if not fits:
        return None
    a, b = max(fits, key=lambda x: x[1] - x[0])
    start = (a + (b - a - dur) / 2).replace(microsecond=0)
    return start, start + dur


def _mark_absence(employee: Employee, c: engine.Container, segs: list[ScheduleSegment], *, book: ScheduleBook, user=None) -> dict | None:
    absence = system_activity(ActivityType.SystemRole.ABSENCE)
    lunch_act = system_activity(ActivityType.SystemRole.LEGAL_LUNCH)
    if absence is None:
        return None
    # El plan de un día sin presentarse queda sin efecto: se quitan los segmentos que exigían sesión (break, almuerzo,
    # coaching…); se conservan los permisos / actividades sin sesión y los segmentos del sistema.
    removed = [s for s in segs if s.activity.requires_acd_login and not s.is_locked and not s.activity.system_role]
    kept = [s for s in segs if s not in removed]
    meal = next((s for s in removed if s.activity.category == ActivityType.Category.MEAL), None)
    snapshots = [_seg_snapshot(s) for s in removed]
    for s in removed:
        s.delete()
    free = _free(c.start, c.end, [(s.start_at, s.end_at) for s in kept])
    lunch_minutes = next((i.lunch_minutes for i in book.instances(employee.pk, c.shift_date, c.shift_date) if i.start == c.start), 0)
    lunch_secs = lunch_minutes * 60 or (lunch_act.default_seconds if lunch_act else 0) or 0
    lunch_secs = min(lunch_secs, int((c.end - c.start).total_seconds()) // 2)
    window = _legal_lunch_window(c, free, lunch_secs, meal.start_at if meal else None) if lunch_act and lunch_secs >= 60 else None
    assignment_id = _assignment_id(book, employee, c)
    note = f"Sin sesión ACD en el turno {hm(c.start)}–{hm(c.end)} (no-show)"
    created = []
    for a, b in _free(c.start, c.end, [(s.start_at, s.end_at) for s in kept] + ([window] if window else [])):
        created.append(ScheduleSegment.objects.create(employee=employee, shift_date=c.shift_date, assignment_id=assignment_id,
                                                      activity=absence, start_at=a, end_at=b, notes=note, origin=SYSTEM, is_locked=True))
    if window:
        created.append(ScheduleSegment.objects.create(employee=employee, shift_date=c.shift_date, assignment_id=assignment_id,
                                                      activity=lunch_act, start_at=window[0], end_at=window[1], origin=SYSTEM,
                                                      is_locked=True, notes="Beneficio legal de almuerzo (día de ausencia)"))
    created.sort(key=lambda s: s.start_at)
    if not created:
        return None
    record("adh_absence_detected", Category.WFM,
           f"Unjustified Absence el {fmt(c.shift_date)} para {employee.employee_code}: sin sesión ACD en el turno {hm(c.start)}–"
           f"{hm(c.end)}" + (f"; Legal Benefit Lunch {hm(window[0])}–{hm(window[1])}" if window else "")
           + (f"; {len(removed)} segmento(s) del plan sin efecto" if removed else "") + ".", actor=user, target=employee,
           details={"shift_date": c.shift_date.isoformat(), "shift_dates": [c.shift_date.isoformat()], "segment_id": created[0].pk,
                    "segment_ids": [s.pk for s in created], "removed": snapshots,
                    "before": snapshots[0] if len(snapshots) == 1 else ({"segments": len(snapshots)} if snapshots else None),
                    "after": _seg_snapshot(created[0])})
    return {"segments": len(created), "legal_lunch": bool(window), "removed": len(removed)}


# ============================================================================ conciliación
def day_status(segments: list[dict], containers: list[dict], justifications: list[dict] | None = None) -> str | None:
    """Estado de asistencia de una fila de la grilla a partir de sus segmentos y justificaciones (sin consultas)."""
    if not containers:
        return None
    roles = {s.get("system_role") for s in segments}
    if ActivityType.SystemRole.ABSENCE in roles:
        return "ABSENT"
    if ActivityType.SystemRole.LATENESS in roles:
        return "LATE"
    if justifications and all(c.get("start") and any(j["start"] <= c["start"] and j["end"] >= c["end"] for j in justifications)
                              for c in containers):
        return "LEAVE"  # permiso / licencia por AP que cubre todo el turno
    total = sum(c["seconds"] for c in containers)
    no_login = sum(s["seconds"] for s in segments if not s.get("requires_acd_login", True) and not s.get("system_role"))
    return "LEAVE" if total and no_login >= total else None


@transaction.atomic
def reconcile(employees: list[Employee], d: date, *, user=None, request=None) -> dict:
    """Concilia la asistencia de la fecha de turno: Lateness de quienes llegaron tarde y Unjustified Absence (con Legal
    Benefit Lunch) de quienes no se presentaron en un bloque ya terminado. Idempotente."""
    now = now_local()
    out = {"date": d.isoformat(), "lateness": 0, "absences": 0, "on_leave": 0, "inactive": 0, "frozen": 0, "present": 0,
           "pending": 0, "rows": []}
    ids = [e.pk for e in employees]
    book = ScheduleBook(ids, d, d)
    for e in employees:
        containers = [c for c in _containers(book, e.pk, d, d) if c.shift_date == d]
        if not containers:
            continue
        if is_inactive(e, d):
            out["inactive"] += 1
            out["rows"].append({"employee_code": e.employee_code, "status": "INACTIVE"})
            continue
        if closed_cutoff_hit(e, d, d):
            out["frozen"] += 1
            continue
        status = "PRESENT"
        for c in containers:
            if c.start >= now:
                status = "PENDING"
                continue
            segs = _segments_in(e, c)
            if _on_leave(e, c, segs):
                status = "LEAVE"
                continue
            logged = _logged(e, c.start, min(c.end, now))
            if not logged:
                if c.end > now:
                    status = "PENDING"
                    continue
                if any(s.activity.system_role in ABSENCE_ROLES for s in segs):
                    status = "ABSENT"
                    continue
                if _mark_absence(e, c, segs, book=book, user=user):
                    out["absences"] += 1
                status = "ABSENT"
                continue
            first = min(a for a, _ in logged)
            if first > c.start and _insert_lateness(e, c, first, book=book, user=user, source="reconcile"):
                out["lateness"] += 1
                status = "LATE"
            elif any(s.activity.system_role == ActivityType.SystemRole.LATENESS for s in segs):
                status = "LATE"
        key = {"PRESENT": "present", "LATE": "present", "LEAVE": "on_leave", "PENDING": "pending"}.get(status)
        if key:
            out[key] += 1
        out["rows"].append({"employee_code": e.employee_code, "status": status})
    record("adh_attendance_reconciled", Category.WFM,
           f"Asistencia del {fmt(d)} conciliada: {out['lateness']} lateness y {out['absences']} ausencias nuevas "
           f"({len(employees)} agentes; {out['on_leave']} con permiso, {out['inactive']} inactivos separados).",
           request=request, actor=user, details={k: v for k, v in out.items() if k != "rows"} | {"shift_dates": [d.isoformat()]})
    return out


__all__ = ["day_status", "detect_lateness", "detect_lateness_safely", "is_inactive", "reconcile", "system_activity"]
