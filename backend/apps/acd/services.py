"""Reglas del módulo ACD: flujo del agente, acceso a auxiliares por grupo, tablero y reporte estilo Genesys Cloud.

SQL Server es la última barrera (migración 0002):
    50060  segmentos de estado traslapados para un agente
    50061  el auxiliar no pertenece al estado primario del segmento
    50062  sub-auxiliar con más de un nivel o con otro estado primario que su padre
Además: un solo segmento abierto y una sola sesión abierta por agente (índices únicos filtrados) y un solo grupo
activo por agente.

Flujo: el agente INICIA SESIÓN (Available), entra a colas (On Queue = tiempo productivo) o elige un estado / auxiliar
permitido para su grupo; cada cambio cierra el segmento anterior y abre otro con la hora del SERVIDOR (el navegador no
envía horas: no se puede manipular). Al CERRAR SESIÓN queda en Offline y el tiempo PAGADO de la sesión (sin Meal ni
auxiliares no pagados) se envía como registro de tiempo WEB_TIMER a horarios (sch_time_record): son las horas reales del
reporte teórico vs real y de los cortes de planilla.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db import DatabaseError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.acd.models import (
    AgentGroup, AgentMembership, AgentSession, AuxCode, Division, GroupAuxAccess, PrimaryStatus, Source, StatusSegment,
)
from apps.hcm.models import Employee
from apps.system.audit import Category, record

MS = timedelta(milliseconds=1)
MAX_REPORT_DAYS = 31
MAX_EXPORT_ROWS = 250_000
INTERVALS = {"30": 30, "60": 60, "1440": 1440, "range": None}
REPORT_COLUMNS = [
    "Interval Start", "Interval End", "Interval Complete", "Employee Id", "Employee Name", "Division Id", "Division Name",
    "Start Time", "End Time", "Primary Status", "Secondary Status", "Duration",
]


class AcdError(Exception):
    def __init__(self, message: str, code: str = "invalid", status: int = 400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def duration_ms(start: datetime, end: datetime) -> int:
    return (end - start) // MS


# ================================================================ acceso por grupo
def membership_for(employee: Employee) -> AgentMembership | None:
    return AgentMembership.objects.select_related("group__division").filter(employee=employee, is_active=True).first()


def allowed_aux_codes(group: AgentGroup) -> list[AuxCode]:
    """Auxiliares que el grupo ve y usa: los no restringidos y los otorgados (otorgar el padre incluye a sus hijos)."""
    granted = set(GroupAuxAccess.objects.filter(group=group).values_list("aux_code_id", flat=True))
    out = []
    for aux in AuxCode.objects.select_related("primary_status", "parent").filter(is_active=True, primary_status__is_active=True):
        if aux.parent_id and not aux.parent.is_active:
            continue
        if not aux.is_restricted or aux.pk in granted or (aux.parent_id and aux.parent_id in granted):
            out.append(aux)
    return out


def options_for(group: AgentGroup) -> list[dict]:
    """Estados que el agente puede elegir, con su árbol de auxiliares / sub-auxiliares permitidos."""
    auxes = allowed_aux_codes(group)
    by_primary: dict[int, list[AuxCode]] = {}
    for aux in auxes:
        by_primary.setdefault(aux.primary_status_id, []).append(aux)
    allowed_ids = {a.pk for a in auxes}
    out = []
    for st in PrimaryStatus.objects.filter(is_active=True, agent_selectable=True).order_by("sort_order"):
        mine = by_primary.get(st.pk, [])
        roots = [a for a in mine if not a.parent_id or a.parent_id not in allowed_ids]
        out.append({
            **primary_dict(st),
            "aux_codes": [{
                **aux_dict(a), "children": [aux_dict(c) for c in mine if c.parent_id == a.pk],
            } for a in roots],
        })
    return out


def primary_dict(st: PrimaryStatus) -> dict:
    return {"code": st.code, "label": st.label, "name": st.name_es, "color": st.color, "is_productive": st.is_productive,
            "is_paid": st.is_paid, "is_logged_in": st.is_logged_in, "agent_selectable": st.agent_selectable}


def aux_dict(a: AuxCode) -> dict:
    return {"code": a.code, "name": a.name, "full_name": a.full_name, "primary_status": a.primary_status.code,
            "parent": a.parent.code if a.parent_id else None, "is_paid": a.paid, "is_productive": a.is_productive,
            "max_minutes": a.max_minutes, "is_restricted": a.is_restricted, "is_active": a.is_active}


def _status(code: str) -> PrimaryStatus:
    st = PrimaryStatus.objects.filter(code=code, is_active=True).first()
    if st is None:
        raise AcdError(f"El estado «{code}» no existe o está inactivo.", "unknown_status")
    return st


# ================================================================ segmentos y sesiones
def current_segment(employee: Employee, *, lock: bool = False) -> StatusSegment | None:
    qs = StatusSegment.objects.filter(employee=employee, end_at__isnull=True)
    if lock:
        qs = qs.select_for_update()
    return qs.select_related("primary_status", "aux_code__parent", "aux_code__primary_status", "group", "division").first()


def open_session(employee: Employee, *, lock: bool = False) -> AgentSession | None:
    qs = AgentSession.objects.filter(employee=employee, logout_at__isnull=True)
    if lock:
        qs = qs.select_for_update()
    return qs.select_related("group").first()


def _close(segment: StatusSegment | None, now: datetime) -> None:
    if segment is None:
        return
    end = max(now, segment.start_at)
    segment.end_at = end
    segment.duration_ms = duration_ms(segment.start_at, end)
    segment.save(update_fields=["end_at", "duration_ms"])


def _open(employee, status: PrimaryStatus, aux: AuxCode | None, *, session, group, now, source, user, notes="") -> StatusSegment:
    return StatusSegment.objects.create(
        employee=employee, session=session, primary_status=status, aux_code=aux, group=group,
        division=group.division if group else None, start_at=now, source=source,
        changed_by=user if getattr(user, "pk", None) else None, notes=notes[:300],
    )


def _require_agent(employee: Employee) -> AgentMembership:
    if employee.employment_status != Employee.Status.ACTIVE:
        raise AcdError("El empleado no está activo: no puede iniciar sesión en el ACD.", "inactive_employee", 403)
    membership = membership_for(employee)
    if membership is None or not membership.group.is_active:
        raise AcdError("No pertenece a ningún grupo ACD activo: pida a WFM que lo asigne a un grupo de agentes.", "no_group", 403)
    return membership


@transaction.atomic
def login(employee: Employee, *, user=None, source: str = Source.AGENT) -> StatusSegment:
    membership = _require_agent(employee)
    if open_session(employee, lock=True):
        raise AcdError("Ya tiene una sesión ACD iniciada.", "already_logged_in")
    now = timezone.now()
    _close(current_segment(employee, lock=True), now)  # el Offline anterior
    session = AgentSession.objects.create(employee=employee, group=membership.group, login_at=now)
    segment = _open(employee, _status(PrimaryStatus.AVAILABLE), None, session=session, group=membership.group,
                    now=now, source=source, user=user)
    record("acd_login", Category.ACD, f"{employee.employee_code} inició sesión ACD (grupo {membership.group.code}).",
           actor=user, target=employee, details={"session": session.pk})
    return segment


@transaction.atomic
def set_status(employee: Employee, primary_code: str, aux_code: str | None = None, *, user=None,
               source: str = Source.AGENT, notes: str = "") -> StatusSegment:
    session = open_session(employee, lock=True)
    if session is None:
        raise AcdError("Inicie sesión en el ACD antes de cambiar de estado.", "not_logged_in")
    primary_code = (primary_code or "").strip().upper()
    if primary_code == PrimaryStatus.OFFLINE:
        raise AcdError("Para quedar Offline, cierre la sesión.", "use_logout")
    status = _status(primary_code)
    if not status.agent_selectable and source == Source.AGENT:
        raise AcdError(f"El estado «{status.label}» no se elige manualmente.", "not_selectable")
    aux = None
    if aux_code:
        aux = AuxCode.objects.select_related("primary_status", "parent").filter(code=str(aux_code).strip().upper(), is_active=True).first()
        if aux is None:
            raise AcdError(f"El auxiliar «{aux_code}» no existe o está inactivo.", "unknown_aux")
        if aux.primary_status_id != status.pk:
            raise AcdError(f"«{aux.full_name}» pertenece al estado {aux.primary_status.label}, no a {status.label}.", "aux_status_mismatch")
        if aux.pk not in {a.pk for a in allowed_aux_codes(session.group)}:
            raise AcdError(f"Su grupo ({session.group.name}) no tiene acceso al auxiliar «{aux.full_name}».", "aux_not_allowed", 403)
        if aux.children.filter(is_active=True).exists():
            raise AcdError(f"«{aux.full_name}» tiene sub-auxiliares: elija uno.", "choose_sub_aux")
    current = current_segment(employee, lock=True)
    if current and current.primary_status_id == status.pk and current.aux_code_id == (aux.pk if aux else None):
        raise AcdError("Ya está en ese estado.", "same_status")
    now = timezone.now()
    _close(current, now)
    return _open(employee, status, aux, session=session, group=session.group, now=now, source=source, user=user, notes=notes)


@transaction.atomic
def logout(employee: Employee, *, user=None, source: str = Source.AGENT, notes: str = "") -> tuple[StatusSegment, AgentSession]:
    session = open_session(employee, lock=True)
    if session is None:
        raise AcdError("No tiene una sesión ACD iniciada.", "not_logged_in")
    now = timezone.now()
    _close(current_segment(employee, lock=True), now)
    session.logout_at, session.logout_source = now, source
    session.save(update_fields=["logout_at", "logout_source"])
    segment = _open(employee, _status(PrimaryStatus.OFFLINE), None, session=None, group=session.group, now=now,
                    source=source, user=user, notes=notes)
    sync_session_time(session, user=user)
    who = "cerró su sesión" if source == Source.AGENT else f"salió del ACD por {user.username if user else 'el sistema'}"
    record("acd_logout", Category.ACD, f"{employee.employee_code} {who}: {session.get_sync_status_display().lower()} "
           f"({session.paid_minutes} min pagados).", actor=user, target=employee,
           details={"session": session.pk, "sync": session.sync_status, "message": session.sync_message})
    return segment, session


# ================================================================ sesión -> tiempo real (Web Timer)
def _is_paid(seg: StatusSegment) -> bool:
    if not seg.primary_status.is_logged_in:
        return False
    return seg.aux_code.paid if seg.aux_code_id else seg.primary_status.is_paid


def paid_runs(session: AgentSession) -> list[tuple[datetime, datetime]]:
    """Tramos continuos de tiempo PAGADO de la sesión (Meal y auxiliares no pagados los cortan)."""
    runs: list[list[datetime]] = []
    for seg in session.segments.select_related("primary_status", "aux_code__primary_status").order_by("start_at"):
        if seg.end_at is None or not _is_paid(seg):
            continue
        if runs and runs[-1][1] == seg.start_at:
            runs[-1][1] = seg.end_at
        else:
            runs.append([seg.start_at, seg.end_at])
    return [(a, b) for a, b in runs]


def _local_minute(dt: datetime) -> datetime:
    return timezone.localtime(dt).replace(tzinfo=None, second=0, microsecond=0)


def sync_session_time(session: AgentSession, *, user=None) -> AgentSession:
    """Envía el tiempo pagado de la sesión como registros WEB_TIMER (hora local, al minuto). Un error (p. ej. corte de
    asistencia cerrado) no deshace el cierre de sesión: queda en `sync_status` / `sync_message` para el supervisor."""
    from apps.scheduling import services as sch
    from apps.scheduling.models import TimeRecord

    employee = session.employee
    created, minutes, problems = 0, 0, []
    for start, end in paid_runs(session):
        a, b = _local_minute(start), _local_minute(end)
        while a < b:
            chunk_end = min(b, a + timedelta(minutes=sch.MAX_RECORD_MINUTES))
            check = sch.check_time_record(employee, {
                "start_at": a, "end_at": chunk_end, "source": TimeRecord.Source.WEB_TIMER,
                "external_ref": f"ACD-S{session.pk}", "notes": "Sesión ACD (tiempo pagado)",
            })
            if check.ok:
                try:
                    with transaction.atomic():
                        rec = sch.create_time_record(employee, check, user=user)
                    created += 1
                    minutes += rec.minutes
                except DatabaseError as exc:
                    problems.append(f"{a:%d/%m %H:%M}–{chunk_end:%H:%M}: SQL Server lo rechazó ({str(exc)[:120]})")
            else:
                problems.append(f"{a:%d/%m %H:%M}–{chunk_end:%H:%M}: " + " ".join(e["message"] for e in check.errors))
            a = chunk_end
    if problems:
        session.sync_status = AgentSession.SyncStatus.ERROR
    elif created:
        session.sync_status = AgentSession.SyncStatus.SYNCED
    else:
        session.sync_status = AgentSession.SyncStatus.SKIPPED
    session.paid_minutes = minutes
    session.sync_message = "; ".join(problems)[:500] if problems else (
        f"{created} registro(s) WEB_TIMER, {minutes} min." if created else "La sesión no tuvo minutos pagados completos.")
    session.save(update_fields=["sync_status", "sync_message", "paid_minutes"])
    return session


# ================================================================ estado del agente y tablero
def segment_dict(seg: StatusSegment, now: datetime | None = None) -> dict:
    now = now or timezone.now()
    end = seg.end_at or now
    aux = seg.aux_code
    elapsed = duration_ms(seg.start_at, end)
    over = bool(aux and aux.max_minutes and seg.end_at is None and elapsed > aux.max_minutes * 60_000)
    return {
        "id": seg.pk, "primary_status": seg.primary_status.code, "primary_label": seg.primary_status.label,
        "primary_name": seg.primary_status.name_es, "color": seg.primary_status.color,
        "aux_code": aux.code if aux else None, "secondary_status": aux.full_name if aux else "",
        "start_at": seg.start_at, "end_at": seg.end_at, "duration_ms": seg.duration_ms if seg.end_at else elapsed,
        "is_open": seg.end_at is None, "over_limit": over, "max_minutes": aux.max_minutes if aux else None,
        "source": seg.source, "source_label": seg.get_source_display(),
        "is_productive": seg.primary_status.is_productive or bool(aux and aux.is_productive),
    }


def agent_state(employee: Employee) -> dict:
    now = timezone.now()
    membership = membership_for(employee)
    session = open_session(employee)
    current = current_segment(employee)
    local_today = timezone.localdate()
    day_start = timezone.make_aware(datetime.combine(local_today, time.min))
    today = list(StatusSegment.objects.filter(employee=employee, start_at__lt=now).filter(
        Q(end_at__isnull=True) | Q(end_at__gt=day_start)).select_related(
        "primary_status", "aux_code__parent", "aux_code__primary_status").order_by("start_at"))
    totals: dict[str, int] = {}
    for seg in today:
        a, b = max(seg.start_at, day_start), seg.end_at or now
        totals[seg.primary_status.label] = totals.get(seg.primary_status.label, 0) + max(0, duration_ms(a, b))
    group = membership.group if membership else None
    return {
        "employee_code": employee.employee_code, "full_name": employee.full_name,
        "group": {"code": group.code, "name": group.name, "is_active": group.is_active} if group else None,
        "division": {"id": str(group.division.division_uid), "name": group.division.name} if group else None,
        "logged_in": session is not None,
        "session": {"id": session.pk, "login_at": session.login_at} if session else None,
        "current": segment_dict(current, now) if current else None,
        "options": options_for(group) if group and group.is_active else [],
        "today": [segment_dict(s, now) for s in today],
        "today_totals_ms": [{"primary_status": k, "duration_ms": v} for k, v in totals.items()],
        "last_session": _last_session(employee),
        "server_time": now,
    }


def _last_session(employee: Employee) -> dict | None:
    s = AgentSession.objects.filter(employee=employee, logout_at__isnull=False).order_by("-logout_at").first()
    if not s:
        return None
    return {"id": s.pk, "login_at": s.login_at, "logout_at": s.logout_at, "sync_status": s.sync_status,
            "sync_status_label": s.get_sync_status_display(), "sync_message": s.sync_message, "paid_minutes": s.paid_minutes}


def board(*, group: str = "", division: str = "", status: str = "", search: str = "") -> list[dict]:
    now = timezone.now()
    members = AgentMembership.objects.filter(is_active=True).select_related("group__division", "employee")
    if group:
        members = members.filter(group__code=group.upper())
    if division:
        members = members.filter(group__division__code=division.upper())
    if search:
        for term in search.split():
            members = members.filter(Q(employee__employee_code__icontains=term) | Q(employee__first_name__icontains=term)
                                     | Q(employee__last_name__icontains=term))
    members = list(members.order_by("group__name", "employee__employee_code"))
    ids = [m.employee_id for m in members]
    open_segments = {s.employee_id: s for s in StatusSegment.objects.filter(employee_id__in=ids, end_at__isnull=True).select_related(
        "primary_status", "aux_code__parent", "aux_code__primary_status")}
    sessions = {s.employee_id: s for s in AgentSession.objects.filter(employee_id__in=ids, logout_at__isnull=True)}
    rows = []
    for m in members:
        seg = open_segments.get(m.employee_id)
        row = {
            "employee_code": m.employee.employee_code, "full_name": m.employee.full_name,
            "group": m.group.code, "group_name": m.group.name, "division": m.group.division.name,
            "logged_in": m.employee_id in sessions,
            "login_at": sessions[m.employee_id].login_at if m.employee_id in sessions else None,
            "current": segment_dict(seg, now) if seg else None,
        }
        if status and (row["current"] or {}).get("primary_status", PrimaryStatus.OFFLINE) != status.upper():
            continue
        rows.append(row)
    return rows


# ================================================================ reporte estilo Genesys Cloud
def resolve_tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or settings.TIME_ZONE)
    except (ZoneInfoNotFoundError, ValueError):
        raise AcdError(f"Zona horaria «{name}» no reconocida (p. ej. America/El_Salvador).", "invalid_tz") from None


def _iso(dt: datetime, tz: ZoneInfo) -> str:
    return dt.astimezone(tz).isoformat(timespec="milliseconds")


def _boundaries(start: datetime, end: datetime, minutes: int | None, tz: ZoneInfo) -> list[tuple[datetime, datetime]]:
    """Intervalos del reporte en hora local de `tz` (30 / 60 min, día) o todo el rango como un solo intervalo."""
    if minutes is None:
        return [(start, end)]
    out = []
    cur = start.astimezone(tz).replace(tzinfo=None)
    last = end.astimezone(tz).replace(tzinfo=None)
    step = timedelta(minutes=minutes)
    while cur < last:
        nxt = min(cur + step, last)
        out.append((cur.replace(tzinfo=tz), nxt.replace(tzinfo=tz)))
        cur = nxt
    return out


@dataclass
class ReportFilters:
    date_from: date
    date_to: date
    interval: str = "1440"
    tz: str | None = None
    group: str = ""
    division: str = ""
    employee: str = ""
    primary_status: str = ""
    extra: dict = field(default_factory=dict)


def agent_status_report(f: ReportFilters) -> dict:
    """Filas con las columnas del reporte de estados de agentes de Genesys Cloud (Agent Status Detail):
    cada segmento se recorta a cada intervalo que toca; Duration en milisegundos; horas ISO-8601 con milisegundos y
    desfase de la zona elegida. «Interval Complete» = el intervalo ya terminó."""
    if f.interval not in INTERVALS:
        raise AcdError("Intervalo inválido: use 30, 60, 1440 (día) o range (todo el rango).", "invalid_interval")
    if f.date_to < f.date_from:
        raise AcdError("«Hasta» no puede ser anterior a «desde».", "invalid_range")
    if (f.date_to - f.date_from).days >= MAX_REPORT_DAYS:
        raise AcdError(f"Consulte como máximo {MAX_REPORT_DAYS} días.", "range_too_long")
    tz = resolve_tz(f.tz)
    now = timezone.now()
    start = datetime.combine(f.date_from, time.min).replace(tzinfo=tz)
    end = datetime.combine(f.date_to + timedelta(days=1), time.min).replace(tzinfo=tz)
    intervals = _boundaries(start, end, INTERVALS[f.interval], tz)
    starts = [i[0] for i in intervals]

    qs = StatusSegment.objects.filter(start_at__lt=end).filter(Q(end_at__isnull=True) | Q(end_at__gt=start)).select_related(
        "employee", "primary_status", "aux_code__parent", "division")
    if f.employee:
        qs = qs.filter(employee__employee_code=f.employee.upper())
    if f.group:
        qs = qs.filter(group__code=f.group.upper())
    if f.division:
        qs = qs.filter(division__code=f.division.upper())
    if f.primary_status:
        qs = qs.filter(primary_status__code=f.primary_status.upper())
    rows, totals = [], {}
    for seg in qs.order_by("employee__employee_code", "start_at").iterator(chunk_size=2000):
        seg_end = seg.end_at or now
        if seg_end <= start or seg.start_at >= end:
            continue
        div = seg.division
        idx = max(0, bisect_right(starts, seg.start_at) - 1)
        for i_start, i_end in intervals[idx:]:
            if i_start >= seg_end:
                break
            a, b = max(seg.start_at, i_start), min(seg_end, i_end)
            if a >= b:
                continue
            ongoing = seg.end_at is None and b == seg_end
            ms = duration_ms(a, b)
            rows.append({
                "Interval Start": _iso(i_start, tz), "Interval End": _iso(i_end, tz),
                "Interval Complete": "TRUE" if i_end <= now else "FALSE",
                "Employee Id": seg.employee.employee_code, "Employee Name": seg.employee.full_name,
                "Division Id": str(div.division_uid) if div else "", "Division Name": div.name if div else "",
                "Start Time": _iso(a, tz), "End Time": "" if ongoing else _iso(b, tz),
                "Primary Status": seg.primary_status.label,
                "Secondary Status": seg.aux_code.full_name if seg.aux_code_id else "",
                "Duration": ms,
            })
            key = (seg.employee.employee_code, seg.employee.full_name)
            agent = totals.setdefault(key, {})
            agent[seg.primary_status.label] = agent.get(seg.primary_status.label, 0) + ms
            if len(rows) > MAX_EXPORT_ROWS:
                raise AcdError(f"El reporte supera {MAX_EXPORT_ROWS:,} filas: reduzca el rango o use un intervalo mayor.", "too_many_rows")
    summary = [{"employee_code": code, "full_name": name, "by_status_ms": by, "total_ms": sum(by.values())}
               for (code, name), by in totals.items()]
    return {"columns": REPORT_COLUMNS, "rows": rows, "summary": summary, "tz": str(tz), "interval": f.interval,
            "from": f.date_from, "to": f.date_to}


# ================================================================ grupos (configuración por WFM)
def group_dict(g: AgentGroup, *, with_members: bool = False) -> dict:
    granted = list(GroupAuxAccess.objects.filter(group=g).select_related("aux_code__parent").order_by("aux_code__code"))
    out = {
        "code": g.code, "name": g.name, "description": g.description, "is_active": g.is_active,
        "division": {"code": g.division.code, "name": g.division.name, "id": str(g.division.division_uid)},
        "aux_codes": [a.aux_code.code for a in granted],
        "members_count": g.members.filter(is_active=True).count(),
    }
    if with_members:
        out["members"] = [{"employee_code": m.employee.employee_code, "full_name": m.employee.full_name, "since": m.created_at}
                          for m in g.members.filter(is_active=True).select_related("employee").order_by("employee_id")]
    return out


@transaction.atomic
def save_group(data: dict, *, group: AgentGroup | None = None, user=None, request=None) -> AgentGroup:
    errors = {}
    division = None
    if "division" in data or group is None:
        division = Division.objects.filter(code=str(data.get("division") or "").upper(), is_active=True).first()
        if division is None:
            errors["division"] = "Elija una división activa."
    if group is None:
        code = str(data.get("code") or "").strip().upper()
        if not code or not code[0].isalpha() or not all(ch.isalnum() or ch in "_-" for ch in code) or len(code) > 30:
            errors["code"] = "Código: MAYÚSCULAS, dígitos, guion o guion bajo (máx. 30), iniciando con letra."
        elif AgentGroup.objects.filter(code=code).exists():
            errors["code"] = f"Ya existe el grupo {code}."
    name = str(data.get("name") if "name" in data else (group.name if group else "")).strip()
    if not name:
        errors["name"] = "Indique el nombre del grupo."
    aux_codes = None
    if "aux_codes" in data:
        wanted = {str(c).strip().upper() for c in (data.get("aux_codes") or [])}
        found = {a.code: a for a in AuxCode.objects.filter(code__in=wanted)}
        missing = sorted(wanted - set(found))
        if missing:
            errors["aux_codes"] = f"Auxiliares no reconocidos: {', '.join(missing)}."
        aux_codes = list(found.values())
    if errors:
        raise AcdErrors(errors)
    created = group is None
    if created:
        group = AgentGroup.objects.create(code=code, name=name, division=division, description=str(data.get("description") or "")[:300])
    else:
        group.name = name
        if division:
            group.division = division
        if "description" in data:
            group.description = str(data.get("description") or "")[:300]
        if "is_active" in data:
            if not data["is_active"] and AgentSession.objects.filter(group=group, logout_at__isnull=True).exists():
                raise AcdErrors({"is_active": "Hay agentes del grupo con sesión iniciada: ciérrelas antes de desactivarlo."})
            group.is_active = bool(data["is_active"])
        group.save()
    if aux_codes is not None:
        GroupAuxAccess.objects.filter(group=group).exclude(aux_code__in=aux_codes).delete()
        have = set(GroupAuxAccess.objects.filter(group=group).values_list("aux_code_id", flat=True))
        GroupAuxAccess.objects.bulk_create([GroupAuxAccess(group=group, aux_code=a) for a in aux_codes if a.pk not in have])
    record("acd_group_created" if created else "acd_group_updated", Category.ACD,
           f"Grupo ACD {group.code} {'creado' if created else 'actualizado'} (división {group.division.name}"
           + (f", {len(aux_codes)} auxiliares permitidos" if aux_codes is not None else "") + ").",
           request=request, actor=user, target_type="AgentGroup", target_id=group.code)
    return group


class AcdErrors(Exception):
    def __init__(self, errors: dict):
        super().__init__("; ".join(errors.values()))
        self.errors = errors


@transaction.atomic
def add_member(group: AgentGroup, employee: Employee, *, user=None, request=None) -> AgentMembership:
    if not group.is_active:
        raise AcdError("El grupo está inactivo.", "inactive_group")
    if employee.employment_status != Employee.Status.ACTIVE:
        raise AcdError(f"{employee.employee_code} no está activo.", "inactive_employee")
    current = AgentMembership.objects.select_for_update().filter(employee=employee, is_active=True).first()
    if current and current.group_id == group.pk:
        raise AcdError(f"{employee.employee_code} ya pertenece a {group.code}.", "already_member")
    if open_session(employee):
        raise AcdError(f"{employee.employee_code} tiene una sesión ACD iniciada: cámbielo de grupo cuando la cierre.", "session_open")
    previous = None
    if current:
        previous = current.group.code
        current.is_active, current.ended_at = False, timezone.now()
        current.save(update_fields=["is_active", "ended_at"])
    m = AgentMembership.objects.create(group=group, employee=employee, created_by=user if getattr(user, "pk", None) else None)
    record("acd_member_added", Category.ACD,
           f"{employee.employee_code} asignado al grupo ACD {group.code}" + (f" (antes {previous})." if previous else "."),
           request=request, actor=user, target=employee)
    return m


@transaction.atomic
def remove_member(group: AgentGroup, employee: Employee, *, user=None, request=None) -> None:
    m = AgentMembership.objects.select_for_update().filter(group=group, employee=employee, is_active=True).first()
    if m is None:
        raise AcdError(f"{employee.employee_code} no pertenece a {group.code}.", "not_member", 404)
    if open_session(employee):
        raise AcdError(f"{employee.employee_code} tiene una sesión ACD iniciada: ciérrela antes de retirarlo.", "session_open")
    m.is_active, m.ended_at = False, timezone.now()
    m.save(update_fields=["is_active", "ended_at"])
    record("acd_member_removed", Category.ACD, f"{employee.employee_code} retirado del grupo ACD {group.code}.",
           request=request, actor=user, target=employee)
