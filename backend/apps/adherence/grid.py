"""Fase 17 — Planificación estilo IEX: filtros jerárquicos, grilla multi-agente y vista histórica del agente.

* Management Unit = grupo de agentes ACD (acd_agent_group). Cliente / marca = atributos del roster vigentes en la
  fecha. Jerarquía = Team Manager del roster (atributo «team_manager») y su cadena en ops_leader.
* La grilla devuelve, por agente, el PRE-CONTENEDOR (turno de la AP de horario), los segmentos, el plan resultante, la
  actividad real del ACD y la adherencia del día; más los METADATOS de la grilla (intervalo, ajuste, ventana) y la
  barra de segmentos (actividades con icono y color de la cuenta elegida).
* Los tiempos van en hora local de la operación (ISO sin zona) y la ventana en minutos desde las 00:00 de la fecha.
* Fase 18: ajuste al soltar en SEGUNDOS (snap_seconds) y audit trail por agente y fecha (`audit_trail`).
* Fase 19: categorías del Time Utilization para el desplegable de la barra; estado de asistencia por fila (Lateness,
  Unjustified Absence, permiso) y dotación neta que separa ausentes, permisos e inactivos.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.db.models import Count, Q

from apps.acd.models import AgentGroup, AgentMembership
from apps.adherence import engine
from apps.adherence.attendance import day_status, is_inactive
from apps.adherence.models import ActivityType, AdherenceDay, AdherenceException, GridSetting, ScheduleSegment, UtilizationCategory
from apps.adherence.services import (
    MAX_EMPLOYEES, MAX_RANGE_DAYS, AdhError, _activity_qs, _container_dict, _containers, _plan_block_dict, activity_dict,
    deviation_dict, employee_dict, evaluate, iso, now_local, planner_day, segment_dict,
)
from apps.hcm.models import Employee
from apps.operations import hierarchy
from apps.operations.models import Brand, Client
from apps.roster.models import RosterAssignment
from apps.scheduling.services import ScheduleBook

DEFAULT_WINDOW = (6 * 60, 20 * 60)  # 06:00–20:00 cuando nadie tiene turno


# ============================================================================ metadatos de la grilla
def grid_setting(group_code: str = "") -> GridSetting:
    s = None
    if group_code:
        s = GridSetting.objects.filter(group__code=group_code.upper()).first()
    return s or GridSetting.objects.filter(group__isnull=True).first() or GridSetting()


def setting_dict(s: GridSetting) -> dict:
    return {"group": s.group.code if s.group_id else None, "interval_minutes": s.interval_minutes, "snap_seconds": s.snap_seconds,
            "margin_hours": s.margin_hours, "intervals": [v for v, _ in GridSetting.INTERVALS],
            "lateness_grace_seconds": s.lateness_grace_seconds, "ap_required_seconds": s.ap_required_seconds,
            "snaps": [{"value": v, "label": lb} for v, lb in GridSetting.SNAPS]}


def save_setting(data: dict, *, user=None) -> GridSetting:
    from apps.adherence.services import AdhErrors

    group_code = str(data.get("group") or "").strip().upper()
    group = AgentGroup.objects.filter(code=group_code).first() if group_code else None
    if group_code and group is None:
        raise AdhErrors({"group": f"Management Unit «{group_code}» no encontrada."})
    s = GridSetting.objects.filter(group=group).first() if group else GridSetting.objects.filter(group__isnull=True).first()
    s = s or GridSetting(group=group)
    errors = {}
    try:
        interval = int(data.get("interval_minutes", s.interval_minutes))
        snap = int(data["snap_seconds"]) if "snap_seconds" in data else (
            int(data["snap_minutes"]) * 60 if "snap_minutes" in data else s.snap_seconds)
        margin = int(data.get("margin_hours", s.margin_hours))
        grace = int(data.get("lateness_grace_seconds", s.lateness_grace_seconds))
        ap_secs = int(data.get("ap_required_seconds", s.ap_required_seconds))
    except (TypeError, ValueError):
        raise AdhErrors({"interval_minutes": "Valores numéricos."}) from None
    if interval not in dict(GridSetting.INTERVALS):
        errors["interval_minutes"] = "Intervalo: 15, 30 o 60 minutos."
    if snap not in dict(GridSetting.SNAPS):
        errors["snap_seconds"] = "Ajuste: 1 s, 15 s, 30 s, 1, 5, 15 o 30 min."
    elif interval in dict(GridSetting.INTERVALS) and snap > interval * 60:
        errors["snap_seconds"] = "El ajuste no puede ser mayor que el intervalo."
    if not 0 <= margin <= 6:
        errors["margin_hours"] = "Margen de 0 a 6 horas."
    if not 0 <= grace <= 3600:
        errors["lateness_grace_seconds"] = "Tolerancia de llegada: de 0 a 3600 segundos."
    if not 0 <= ap_secs <= 86400:
        errors["ap_required_seconds"] = "Duración que exige AP: de 0 (solo día completo) a 86400 segundos."
    if errors:
        raise AdhErrors(errors)
    s.interval_minutes, s.snap_seconds, s.margin_hours = interval, snap, margin
    s.lateness_grace_seconds, s.ap_required_seconds = grace, ap_secs
    s.updated_by = user if getattr(user, "pk", None) else None
    s.save()
    from apps.system.audit import Category, record

    record("adh_grid_setting", Category.WFM, f"Grilla de planificación ({group.code if group else 'global'}): intervalo {interval} min, "
           f"ajuste {dict(GridSetting.SNAPS)[snap]}, margen {margin} h, tolerancia {grace} s, AP desde {ap_secs} s.", actor=user)
    return s


def toolbox(client_code: str = "") -> list[dict]:
    """Cuadros de la barra de segmentos: actividades activas de la cuenta (sin cuentas asignadas = todas). Las del
    sistema (Lateness, ausencia, almuerzo legal) no se ofrecen: las inserta el sistema."""
    out = []
    for a in _activity_qs().filter(is_active=True, system_role=""):
        codes = {c.code for c in a.clients.all()}
        if client_code and codes and client_code not in codes:
            continue
        out.append(activity_dict(a))
    return out


def categories() -> list[dict]:
    """Categorías del Time Utilization (desplegable de la barra de segmentos), en orden."""
    return [{"code": c.code, "name": c.name, "department": c.department, "department_label": c.get_department_display()}
            for c in UtilizationCategory.objects.filter(is_active=True).order_by("sort_order", "name")]


# ============================================================================ filtros
def filters_payload() -> dict:
    groups = AgentGroup.objects.filter(is_active=True).annotate(
        agents=Count("members", filter=Q(members__is_active=True))).order_by("name")
    clients = Client.objects.filter(is_active=True).order_by("name")
    brands = Brand.objects.filter(is_active=True).select_related("client").order_by("name")
    by_client = defaultdict(list)
    for b in brands:
        by_client[b.client_id].append({"code": b.code, "name": b.name})
    return {
        "management_units": [{"code": g.code, "name": g.name, "agents": g.agents} for g in groups],
        "clients": [{"code": c.code, "name": c.name, "brands": by_client.get(c.pk, [])} for c in clients],
        "levels": [{"value": lvl, "param": param, "label": dict((v, lb) for v, lb in hierarchy.HierarchyLevel.choices)[lvl]}
                   for param, lvl in hierarchy.FILTER_PARAMS.items()],
        "leaders": [hierarchy.leader_dict(x) for x in hierarchy.leaders()],
        "setting": setting_dict(grid_setting()),
    }


def _roster_items(employee_ids: list[int], attribute: str, start: date, end: date) -> dict[int, list[RosterAssignment]]:
    out = defaultdict(list)
    qs = (RosterAssignment.objects.current().filter(attribute__code=attribute, employee_id__in=employee_ids, item__isnull=False)
          .filter(effective_start__lte=end).filter(Q(effective_end__isnull=True) | Q(effective_end__gte=start))
          .select_related("item"))
    for row in qs:
        out[row.employee_id].append(row)
    return out


def _on(rows: list[RosterAssignment], d: date) -> RosterAssignment | None:
    return next((r for r in rows if r.effective_start <= d and (r.effective_end is None or r.effective_end >= d)), None)


def select_grid_employees(params, d: date) -> list[Employee]:
    """Agentes de la grilla: Management Unit (o todos los agentes ACD activos) ∩ cliente / marca ∩ jerarquía ∩ búsqueda."""
    group = str(params.get("group") or "").strip().upper()
    members = AgentMembership.objects.filter(is_active=True)
    if group:
        members = members.filter(group__code=group)
    ids = set(members.values_list("employee_id", flat=True))
    for attr, key in (("client", "client"), ("brand", "brand")):
        code = str(params.get(key) or "").strip()
        if code and ids:
            rows = _roster_items(list(ids), attr, d, d)
            ids = {eid for eid in ids if (r := _on(rows.get(eid, []), d)) and r.item.code == code}
    # El nivel más bajo elegido manda (Team Manager > Account Supervisor > Operations Manager > Director).
    for param in ("team_manager", "supervisor", "manager", "director"):
        code = str(params.get(param) or "").strip()
        if code:
            ids &= hierarchy.employees_under(hierarchy.FILTER_PARAMS[param], code, d)
            break
    qs = Employee.objects.filter(pk__in=list(ids))
    search = str(params.get("search") or "").strip()
    if search:
        qs = qs.filter(Q(employee_code__icontains=search) | Q(first_name__icontains=search) | Q(last_name__icontains=search))
    return list(qs.order_by("last_name", "first_name", "employee_code")[:MAX_EMPLOYEES + 1])


# ============================================================================ grilla multi-agente
def _safe_evaluate(employees: list[Employee], date_from: date, date_to: date) -> dict[int, engine.Result | None]:
    try:
        return evaluate(employees, date_from, date_to)
    except AdhError:
        out = {}
        for e in employees:  # un plan inválido no tumba la grilla completa
            try:
                out[e.pk] = evaluate([e], date_from, date_to)[e.pk]
            except AdhError:
                out[e.pk] = None
        return out


def _window(d: date, containers: list[dict], margin_hours: int) -> tuple[int, int]:
    base = datetime.combine(d, time())
    if not containers:
        return DEFAULT_WINDOW
    lo = min(int((datetime.fromisoformat(c["start"]) - base).total_seconds() // 60) for c in containers)
    hi = max(int((datetime.fromisoformat(c["end"]) - base).total_seconds() // 60) for c in containers)
    lo = (lo // 60) * 60 - margin_hours * 60
    hi = -(-hi // 60) * 60 + margin_hours * 60
    return max(lo, -6 * 60), min(hi, 36 * 60)


def _actual_blocks(res: engine.Result | None, lo: datetime, hi: datetime) -> list[dict]:
    if res is None:
        return []
    return [{"start": iso(max(a.start, lo)), "end": iso(min(a.end, hi)), "primary": a.primary, "aux": a.aux, "label": a.label,
             "paid": a.paid} for a in res.actuals if a.end > lo and a.start < hi]


def status_colors() -> dict[str, str]:
    from apps.acd.models import PrimaryStatus

    return dict(PrimaryStatus.objects.values_list("code", "color"))


def _justification_blocks(res: engine.Result | None, lo: datetime, hi: datetime) -> list[dict]:
    if res is None:
        return []
    return [{"start": iso(max(j.start, lo)), "end": iso(min(j.end, hi)), "folio": j.label, "is_paid": j.is_paid}
            for j in res.justifications if j.end > lo and j.start < hi]


def _deviation_blocks(res: engine.Result | None, d: date, acts: dict) -> list[dict]:
    return [deviation_dict(x, acts) for x in res.deviations if x.day == d] if res else []


def grid_day(employees: list[Employee], d: date, params) -> dict:
    if len(employees) > MAX_EMPLOYEES:
        raise AdhError(f"Demasiados agentes (máx. {MAX_EMPLOYEES}): filtre por Management Unit o supervisor.", "too_many")
    setting = grid_setting(str(params.get("group") or ""))
    base = planner_day(employees, d)
    ids = [e.pk for e in employees]
    tree = hierarchy.agent_hierarchy(ids, d)
    clients = _roster_items(ids, "client", d, d)
    brands = _roster_items(ids, "brand", d, d)
    today = now_local().date()
    has_default = ActivityType.objects.filter(is_default=True, is_active=True).exists()
    results = _safe_evaluate(employees, d, d) if employees and d <= today and has_default else {}
    acts = {a.code: a for a in ActivityType.objects.all()}
    day0 = datetime.combine(d, time())
    lo, hi = _window(d, [c for r in base["rows"] for c in r["containers"]], setting.margin_hours)
    wlo, whi = day0 + timedelta(minutes=lo), day0 + timedelta(minutes=hi)
    rows = []
    for e, row in zip(employees, base["rows"], strict=True):
        res = results.get(e.pk)
        totals = res.days.get(d) if res else None
        c, b = _on(clients.get(e.pk, []), d), _on(brands.get(e.pk, []), d)
        rows.append({
            **row, "attendance": "INACTIVE" if row["containers"] and is_inactive(e, d) else None,
            "hierarchy": tree.get(e.pk), "client": {"code": c.item.code, "name": c.item.name} if c else None,
            "brand": {"code": b.item.code, "name": b.item.name} if b else None,
            "actual": _actual_blocks(res, wlo, whi), "deviations": _deviation_blocks(res, d, acts),
            "justifications": _justification_blocks(res, wlo, whi),
            "metrics": totals.as_dict() if totals else None,
        })
        if rows[-1]["attendance"] is None:
            rows[-1]["attendance"] = day_status(row["segments"], row["containers"], rows[-1]["justifications"])
    scheduled = sum(r["metrics"]["scheduled"] for r in rows if r["metrics"])
    in_adh = sum(r["metrics"]["in_adherence"] for r in rows if r["metrics"])
    just = sum(r["metrics"]["justified_scheduled"] for r in rows if r["metrics"])
    base_secs = scheduled - just
    status = [r["attendance"] for r in rows if r["containers"]]
    with_shift = sum(1 for r in rows if r["containers"])
    absent, on_leave, inactive = status.count("ABSENT"), status.count("LEAVE"), status.count("INACTIVE")
    return {
        "date": d.isoformat(), "default_activity": base["default_activity"], "rows": rows,
        "grid": {**setting_dict(setting), "window_start": lo, "window_end": hi, "window_start_at": iso(wlo), "window_end_at": iso(whi)},
        "toolbox": toolbox(str(params.get("client") or "")), "categories": categories(),
        "status_colors": status_colors(),
        "summary": {"agents": len(rows), "with_shift": with_shift, "absent": absent, "late": status.count("LATE"),
                    "on_leave": on_leave, "inactive": inactive, "net_staff": with_shift - absent - on_leave - inactive,
                    "adherence_pct": round(in_adh * 100 / base_secs, 2) if base_secs > 0 else None,
                    "evaluated": d <= today},
    }


# ============================================================================ vista histórica del agente
def agent_history(employee: Employee, date_from: date | None, date_to: date | None) -> dict:
    """Líneas de tiempo del agente día por día, desde su fecha de contratación en adelante (páginas de ≤ 31 días)."""
    hire = employee.hire_date
    today = now_local().date()
    if date_from is None:
        date_from = max(hire, today - timedelta(days=13))
        date_to = date_to or date_from + timedelta(days=13)
    date_to = date_to or date_from + timedelta(days=13)
    if date_from < hire:
        date_from = hire
    if date_to < date_from:
        date_to = date_from
    if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
        date_to = date_from + timedelta(days=MAX_RANGE_DAYS - 1)
    days = [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]
    setting = grid_setting()
    book = ScheduleBook([employee.pk], date_from, date_to)
    segs = defaultdict(list)
    for s in (ScheduleSegment.objects.filter(employee=employee, shift_date__range=(date_from, date_to))
              .select_related("activity__utilization_category", "employee", "created_by", "personnel_action")):
        segs[s.shift_date].append(s)
    default = ActivityType.objects.filter(is_default=True, is_active=True).first()
    acts = {a.code: a for a in ActivityType.objects.all()}
    last_eval = min(date_to, today)
    res = _safe_evaluate([employee], date_from, last_eval).get(employee.pk) if default and date_from <= last_eval else None
    stored = {x.shift_date: x for x in AdherenceDay.objects.filter(employee=employee, shift_date__range=(date_from, date_to))}
    just = list(AdherenceException.objects.filter(employee=employee, start_at__lt=datetime.combine(date_to + timedelta(days=2), time()),
                                                  end_at__gt=datetime.combine(date_from - timedelta(days=1), time()))
                .select_related("personnel_action"))
    containers_by_day = {d: _containers(book, employee.pk, d, d) for d in days}
    # Ventana común (minutos desde las 00:00 de cada fecha) para alinear todas las filas.
    all_c = []
    for d in days:
        base = datetime.combine(d, time())
        for c in containers_by_day[d]:
            all_c.append(((c.start - base).total_seconds() // 60, (c.end - base).total_seconds() // 60))
    if all_c:
        lo = int(min(a for a, _ in all_c)) // 60 * 60 - setting.margin_hours * 60
        hi = -(-int(max(b for _, b in all_c)) // 60) * 60 + setting.margin_hours * 60
        lo, hi = max(lo, -6 * 60), min(hi, 36 * 60)
    else:
        lo, hi = DEFAULT_WINDOW
    rows = []
    for d in days:
        containers = containers_by_day[d]
        plan = []
        warning = None
        if default and containers:
            try:
                plan = engine.build_plan(containers, [engine.PlannedSegment(s.shift_date, s.start_at, s.end_at, s.activity.code, s.pk)
                                                      for s in segs[d]], default.code)
            except engine.PlanError as exc:
                warning = str(exc)
        base = datetime.combine(d, time())
        wlo, whi = base + timedelta(minutes=lo), base + timedelta(minutes=hi)
        totals = res.days.get(d) if res and d <= last_eval else None
        st = stored.get(d)
        rows.append({
            "date": d.isoformat(), "weekday": d.weekday(), "is_today": d == today, "is_future": d > today,
            "containers": [_container_dict(c, book, employee.pk) for c in containers],
            "segments": [segment_dict(s) for s in segs[d]],
            "plan": [_plan_block_dict(b, acts) for b in plan],
            "actual": _actual_blocks(res, wlo, whi) if d <= last_eval else [],
            "deviations": _deviation_blocks(res, d, acts) if d <= last_eval else [],
            "justifications": [{"start": iso(max(j.start_at, wlo)), "end": iso(min(j.end_at, whi)), "folio": j.personnel_action.folio,
                                "is_paid": j.is_paid} for j in just if j.end_at > wlo and j.start_at < whi],
            "metrics": totals.as_dict() if totals else None,
            "stored": {"adherence_pct": float(st.adherence_pct) if st.adherence_pct is not None else None,
                       "computed_at": st.computed_at.isoformat()} if st else None,
            "warning": warning,
        })
        rows[-1]["attendance"] = day_status(rows[-1]["segments"], rows[-1]["containers"], rows[-1]["justifications"])
    membership = AgentMembership.objects.filter(employee=employee, is_active=True).select_related("group").first()
    first_seg = ScheduleSegment.objects.filter(employee=employee).order_by("shift_date").values_list("shift_date", flat=True).first()
    return {
        **employee_dict(employee), "hire_date": hire.isoformat(), "today": today.isoformat(),
        "employment_status": employee.employment_status,
        "termination_date": employee.termination_date.isoformat() if employee.termination_date else None,
        "management_unit": {"code": membership.group.code, "name": membership.group.name} if membership else None,
        "hierarchy_history": hierarchy.agent_hierarchy_history(employee.pk),
        "first_segment_date": first_seg.isoformat() if first_seg else None,
        "from": date_from.isoformat(), "to": date_to.isoformat(),
        "prev_from": max(hire, date_from - timedelta(days=(date_to - date_from).days + 1)).isoformat() if date_from > hire else None,
        "next_from": (date_to + timedelta(days=1)).isoformat(),
        "grid": {**setting_dict(setting), "window_start": lo, "window_end": hi},
        "rows": rows,
        "toolbox": toolbox(), "categories": categories(),
        "status_colors": status_colors(),
    }
