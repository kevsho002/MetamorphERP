"""Servicios de la Fase 16: planificación de segmentos, justificaciones por AP y cálculo de adherencia.

* El CONTENEDOR del turno es cada bloque entrada-salida del horario vigente (sch_schedule_assignment, creado por una
  AP aprobada). Los segmentos se programan siempre dentro de un contenedor de su fecha de turno.
* El plan y las justificaciones están en hora LOCAL; los segmentos ACD se guardan en UTC y se convierten a la zona de
  la operación (settings.TIME_ZONE) antes de cruzarlos.
* Un corte de asistencia CERRADO congela la planificación, las justificaciones y el cálculo guardado de esas fechas.
* Fase 18: todo va al SEGUNDO (HH:MM:SS): inicio / fin de segmentos y justificaciones, duraciones y el cálculo; cada
  cambio deja en la auditoría la fecha de turno y el antes / después (audit trail por agente y fecha).
* Fase 19: categorías del Time Utilization; segmentos que exigen AP aprobada (actividad marcada, día completo o cambio
  mayor); Lateness / Unjustified Absence bloqueados (solo se REEMPLAZAN con un segmento respaldado por AP).
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db import connection, transaction
from django.db.models import Prefetch, Q
from django.utils import timezone

from apps.acd.models import AgentMembership, StatusSegment
from apps.adherence import engine
from apps.adherence.models import (
    ICONS, REVIEW_AREAS, ActivityStatusRule, ActivityType, AdherenceDay, AdherenceException, Deviation, GridSetting,
    ScheduleSegment, UtilizationCategory,
)
from apps.hcm.models import Employee
from apps.personnel_actions.models import PersonnelAction
from apps.scheduling.services import ScheduleBook, closed_cutoff_hit, parse_any_date, parse_wall_clock
from apps.system.audit import Category, record

MAX_RANGE_DAYS = 31
MAX_EMPLOYEES = 300
MAX_BULK_ITEMS = 2000
MIN_SEGMENT_SECONDS = 60


class AdhError(Exception):
    def __init__(self, message: str, code: str = "invalid", status: int = 400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


class AdhErrors(Exception):
    def __init__(self, errors: dict):
        super().__init__("; ".join(str(v) for v in errors.values()))
        self.errors = errors


def fmt(d: date) -> str:
    return f"{d:%d/%m/%Y}"


def hm(dt: datetime) -> str:
    """HH:MM, o HH:MM:SS cuando la hora tiene segundos (Fase 18)."""
    return f"{dt:%H:%M:%S}" if dt.second else f"{dt:%H:%M}"


def fmt_duration(seconds: int) -> str:
    """3725 → «1 h 02 min 05 s»; 90 → «1 min 30 s»; 300 → «5 min»."""
    h, rem = divmod(int(seconds), 3600)
    m, sec = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h} h")
    if m or (h and sec):
        parts.append(f"{m:02d} min" if h else f"{m} min")
    if sec:
        parts.append(f"{sec:02d} s" if (h or m) else f"{sec} s")
    return " ".join(parts) or "0 s"


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def local_naive(dt: datetime) -> datetime:
    """UTC (aware) → hora local de la operación sin tzinfo, al segundo."""
    return timezone.localtime(dt).replace(tzinfo=None, microsecond=0)


def aware(dt: datetime) -> datetime:
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


def now_local() -> datetime:
    return local_naive(timezone.now())


# ================================================================ catálogo de actividades
def _activity_qs():
    return ActivityType.objects.select_related("utilization_category").prefetch_related(Prefetch(
        "status_rules", queryset=ActivityStatusRule.objects.select_related("primary_status", "aux_code", "aux_code__parent")),
        "clients")


def category_dict(c: UtilizationCategory | None) -> dict | None:
    if c is None:
        return None
    return {"code": c.code, "name": c.name, "department": c.department, "department_label": c.get_department_display(),
            "sort_order": c.sort_order}


def activity_dict(a: ActivityType) -> dict:
    rules = list(a.status_rules.all())
    return {
        "code": a.code, "name": a.name, "category": a.category, "category_label": a.get_category_display(),
        "description": a.description, "color": a.color, "is_paid": a.is_paid, "is_billable": a.is_billable,
        "is_default": a.is_default, "default_seconds": a.default_seconds, "sort_order": a.sort_order, "is_active": a.is_active,
        "icon": a.icon, "clients": sorted(c.code for c in a.clients.all()),
        "utilization_category": category_dict(a.utilization_category),
        "requires_acd_login": a.requires_acd_login, "allows_full_day": a.allows_full_day, "allows_partial": a.allows_partial,
        "requires_ap": a.requires_ap, "client_paid": a.client_paid, "client_paid_label": a.get_client_paid_display(),
        "review_areas": a.review_list, "system_role": a.system_role or None,
        "rules": [{
            "id": r.pk, "primary_status": r.primary_status.code, "primary_label": r.primary_status.label,
            "aux_code": r.aux_code.code if r.aux_code_id else None,
            "aux_name": r.aux_code.full_name if r.aux_code_id else None,
            "role": r.role, "role_label": r.get_role_display(),
        } for r in sorted(rules, key=lambda r: (r.role, r.primary_status.sort_order, r.aux_code_id or 0))],
    }


def engine_activities(qs=None) -> dict[str, engine.Activity]:
    out = {}
    for a in (qs if qs is not None else _activity_qs()):
        out[a.code] = engine.Activity(
            a.code, a.name, a.is_paid, a.is_billable,
            tuple(engine.StatusRule(r.primary_status.code, r.aux_code.code if r.aux_code_id else None, r.role) for r in a.status_rules.all()),
            a.requires_acd_login,
        )
    return out


@transaction.atomic
def save_activity(data: dict, *, activity: ActivityType | None = None, user=None, request=None) -> ActivityType:
    from apps.acd.models import AuxCode, PrimaryStatus

    errors: dict = {}
    created = activity is None
    if created:
        code = str(data.get("code") or "").strip().upper()
        if not code or not code[0].isalpha() or len(code) > 30 or not all(c.isalnum() or c in "_-" for c in code):
            errors["code"] = "Código: MAYÚSCULAS, dígitos, guion o guion bajo (máx. 30), iniciando con letra."
        elif ActivityType.objects.filter(code=code).exists():
            errors["code"] = f"Ya existe la actividad {code}."
        activity = ActivityType(code=code)
    name = str(data.get("name", activity.name) or "").strip()
    if not name:
        errors["name"] = "Indique el nombre de la actividad."
    category = data.get("category", activity.category)
    if category not in ActivityType.Category.values:
        errors["category"] = "Elija una categoría válida."
    color = str(data.get("color", activity.color) or "").strip()
    if not (len(color) == 7 and color.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in color[1:])):
        errors["color"] = "Color hexadecimal (#RRGGBB)."
    if "default_seconds" in data:
        seconds = data.get("default_seconds")
    elif "default_minutes" in data:  # compatibilidad: minutos → segundos
        seconds = data["default_minutes"] if data["default_minutes"] in ("", None) else _num(data["default_minutes"], 60)
    else:
        seconds = activity.default_seconds
    if seconds in ("", None):
        seconds = None
    else:
        try:
            seconds = int(seconds)
            if not 60 <= seconds <= 43200:
                raise ValueError
        except (TypeError, ValueError):
            errors["default_seconds"] = "Duración sugerida: de 00:01:00 a 12:00:00 (60 a 43200 segundos)."
    is_active = bool(data.get("is_active", activity.is_active))
    is_default = bool(data.get("is_default", activity.is_default))
    # Fase 19: matriz del Time Utilization.
    if created and data.get("system_role"):
        errors["system_role"] = "Las actividades del sistema (Lateness, ausencia, almuerzo legal) no se crean a mano."
    flags = {k: bool(data.get(k, getattr(activity, k) if not created else default))
             for k, default in (("requires_acd_login", True), ("allows_full_day", False), ("allows_partial", True), ("requires_ap", False))}
    if not flags["allows_full_day"] and not flags["allows_partial"]:
        errors["allows_partial"] = "La actividad debe poder ser parcial, de día completo o ambas."
    client_paid = data.get("client_paid", activity.client_paid or ActivityType.ClientPaid.NONE)
    if client_paid not in ActivityType.ClientPaid.values:
        errors["client_paid"] = "Pagado por el cliente: NONE, MANDATORY u OPTIONAL."
    review = activity.review_areas
    if "review_areas" in data:
        raw = data.get("review_areas") or []
        items = [str(x).strip().upper() for x in (raw.split(",") if isinstance(raw, str) else raw) if str(x).strip()]
        valid = [code for code, _ in REVIEW_AREAS]
        if any(x not in valid for x in items):
            errors["review_areas"] = f"Áreas válidas: {', '.join(valid)}."
        review = ",".join(x for x in valid if x in items)
    category_obj = activity.utilization_category if not created else None
    if "utilization_category" in data:
        code = str(data.get("utilization_category") or "").strip().upper()
        category_obj = UtilizationCategory.objects.filter(code=code).first() if code else None
        if code and category_obj is None:
            errors["utilization_category"] = f"Categoría «{code}» no encontrada."
    if activity.system_role:
        if is_default:
            errors["is_default"] = "Una actividad del sistema no puede ser la predeterminada del contenedor."
        flags["requires_ap"] = False
    icon = str(data.get("icon", activity.icon) or "clock")
    if icon not in dict(ICONS):
        errors["icon"] = "Icono no reconocido."
    clients = None
    if "clients" in data:
        from apps.operations.models import Client

        codes = [str(c).strip() for c in (data.get("clients") or []) if str(c).strip()]
        clients = list(Client.objects.filter(code__in=codes))
        missing = set(codes) - {c.code for c in clients}
        if missing:
            errors["clients"] = f"Clientes no reconocidos: {', '.join(sorted(missing))}."
    if is_default and not is_active:
        errors["is_default"] = "La actividad predeterminada debe estar activa."
    if not created and activity.is_default and not is_default:
        errors["is_default"] = "Debe haber una actividad predeterminada: marque otra como predeterminada en su lugar."
    rules = None
    if "rules" in data:
        rules = []
        seen = set()
        statuses = {s.code: s for s in PrimaryStatus.objects.all()}
        auxes = {a.code: a for a in AuxCode.objects.select_related("primary_status")}
        for i, r in enumerate(data.get("rules") or []):
            r = r if isinstance(r, dict) else {}
            st = statuses.get(str(r.get("primary_status") or "").upper())
            aux = auxes.get(str(r.get("aux_code") or "").upper()) if r.get("aux_code") else None
            role = r.get("role") or ActivityStatusRule.Role.PRIMARY
            if st is None or not st.is_logged_in:
                errors[f"rules.{i}"] = "Elija un estado con sesión iniciada (Offline no cumple ninguna actividad)."
            elif r.get("aux_code") and aux is None:
                errors[f"rules.{i}"] = f"Auxiliar «{r.get('aux_code')}» no reconocido."
            elif aux is not None and aux.primary_status_id != st.pk:
                errors[f"rules.{i}"] = f"El auxiliar {aux.full_name} es de {aux.primary_status.label}, no de {st.label}."
            elif role not in ActivityStatusRule.Role.values:
                errors[f"rules.{i}"] = "Rol: PRIMARY o SECONDARY."
            elif (st.code, aux.code if aux else None) in seen:
                errors[f"rules.{i}"] = "Estado / auxiliar repetido."
            else:
                seen.add((st.code, aux.code if aux else None))
                rules.append((st, aux, role))
        if not rules and is_active and flags["requires_acd_login"] and not activity.system_role:
            errors["rules"] = "Indique al menos un estado ACD que cumpla la actividad (o márquela como «no requiere sesión»)."
    if errors:
        raise AdhErrors(errors)
    if is_default and not activity.is_default:
        ActivityType.objects.filter(is_default=True).exclude(pk=activity.pk).update(is_default=False)
    activity.name, activity.category, activity.color, activity.default_seconds = name, category, color, seconds
    activity.description = str(data.get("description", activity.description) or "")[:300]
    activity.is_paid = bool(data.get("is_paid", activity.is_paid if not created else True))
    activity.is_billable = bool(data.get("is_billable", activity.is_billable))
    activity.is_active, activity.is_default, activity.icon = is_active, is_default, icon
    for k, v in flags.items():
        setattr(activity, k, v)
    activity.client_paid, activity.review_areas, activity.utilization_category = client_paid, review, category_obj
    if "sort_order" in data:
        try:
            activity.sort_order = max(0, min(int(data["sort_order"]), 32000))
        except (TypeError, ValueError):
            pass
    activity.save()
    if rules is not None:
        ActivityStatusRule.objects.filter(activity=activity).delete()
        ActivityStatusRule.objects.bulk_create([ActivityStatusRule(activity=activity, primary_status=s, aux_code=a, role=r) for s, a, r in rules])
    if clients is not None:
        activity.clients.set(clients)
    record("adh_activity_created" if created else "adh_activity_updated", Category.WFM,
           f"Actividad {activity.code} {'creada' if created else 'actualizada'}"
           + (f" ({len(rules)} estados ACD)" if rules is not None else "") + ".",
           request=request, actor=user, target_type="ActivityType", target_id=activity.code)
    return _activity_qs().get(pk=activity.pk)


def _num(value, factor: int):
    try:
        return round(float(value) * factor)
    except (TypeError, ValueError):
        return value


def default_activity() -> ActivityType:
    a = ActivityType.objects.filter(is_default=True, is_active=True).first()
    if a is None:
        raise AdhError("No hay actividad predeterminada del contenedor: marque una (p. ej. Producción) en «Actividades».", "no_default")
    return a


# ================================================================ selección de agentes
def select_employees(*, group: str = "", employee: str = "", search: str = "") -> list[Employee]:
    qs = Employee.objects.select_related("country")
    if employee:
        codes = [c.strip().upper() for c in employee.split(",") if c.strip()]
        qs = qs.filter(employee_code__in=codes)
    elif group:
        ids = AgentMembership.objects.filter(group__code=group.upper(), is_active=True).values_list("employee_id", flat=True)
        qs = qs.filter(pk__in=list(ids))
    else:
        ids = AgentMembership.objects.filter(is_active=True).values_list("employee_id", flat=True)
        qs = qs.filter(pk__in=list(ids))
    if search:
        qs = qs.filter(Q(employee_code__icontains=search) | Q(first_name__icontains=search) | Q(last_name__icontains=search))
    return list(qs.order_by("employee_code")[:MAX_EMPLOYEES + 1])


def employee_dict(e: Employee) -> dict:
    return {"employee_code": e.employee_code, "full_name": e.full_name}


def _check_range(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    if date_from is None:
        raise AdhError("Indique la fecha inicial (AAAA-MM-DD).", "date_required")
    date_to = date_to or date_from
    if date_to < date_from:
        raise AdhError("La fecha final no puede ser anterior a la inicial.", "invalid_range")
    if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
        raise AdhError(f"El rango máximo es de {MAX_RANGE_DAYS} días.", "range_too_long")
    return date_from, date_to


# ================================================================ contenedores y plan
def _containers(book: ScheduleBook, employee_id: int, start: date, end: date) -> list[engine.Container]:
    out = []
    for inst in book.instances(employee_id, start, end):
        out.append(engine.Container(inst.shift_date, inst.start, inst.end, inst.shift_code))
    return out


def _container_dict(c: engine.Container, book: ScheduleBook, employee_id: int) -> dict:
    lunch = 0
    for inst in book.instances(employee_id, c.shift_date, c.shift_date):
        if inst.start == c.start:
            lunch = inst.lunch_minutes
    seconds = int((c.end - c.start).total_seconds())
    return {"shift_date": c.shift_date.isoformat(), "start": iso(c.start), "end": iso(c.end), "label": c.label,
            "seconds": seconds, "minutes": round(seconds / 60, 4), "lunch_minutes": lunch}


def segment_dict(s: ScheduleSegment) -> dict:
    return {"id": s.pk, "employee_code": s.employee.employee_code if hasattr(s, "employee") else None,
            "shift_date": s.shift_date.isoformat(), "start": iso(s.start_at), "end": iso(s.end_at), "seconds": s.seconds, "minutes": s.minutes,
            "activity": s.activity.code, "activity_name": s.activity.name, "color": s.activity.color,
            "category": s.activity.category, "is_paid": s.activity.is_paid, "notes": s.notes, "icon": s.activity.icon,
            "origin": s.origin, "origin_label": s.get_origin_display(), "is_locked": s.is_locked,
            "folio": s.personnel_action.folio if s.personnel_action_id else None, "system_role": s.activity.system_role or None,
            "requires_ap": s.activity.requires_ap, "requires_acd_login": s.activity.requires_acd_login,
            "utilization_category": s.activity.utilization_category.name if s.activity.utilization_category_id else None,
            "created_by": s.created_by.username if s.created_by_id else None,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None}


def _plan_block_dict(b: engine.PlanBlock, acts: dict[str, ActivityType]) -> dict:
    a = acts.get(b.activity)
    seconds = int((b.end - b.start).total_seconds())
    return {"shift_date": b.shift_date.isoformat(), "start": iso(b.start), "end": iso(b.end), "source": b.source,
            "seconds": seconds, "minutes": round(seconds / 60, 4), "activity": b.activity,
            "activity_name": a.name if a else b.activity, "color": a.color if a else "#64748b",
            "is_paid": a.is_paid if a else True, "segment_id": b.ref, "icon": a.icon if a else "clock",
            "system_role": (a.system_role or None) if a else None}


def planner_day(employees: list[Employee], d: date) -> dict:
    """Vista del planificador para una fecha de turno: contenedores, segmentos y plan resultante de cada agente."""
    default = ActivityType.objects.filter(is_default=True, is_active=True).first()
    acts = {a.code: a for a in ActivityType.objects.all()}
    ids = [e.pk for e in employees]
    book = ScheduleBook(ids, d, d)
    segs = defaultdict(list)
    for s in ScheduleSegment.objects.filter(employee_id__in=ids, shift_date=d).select_related("activity__utilization_category", "employee", "created_by", "personnel_action").order_by("start_at"):
        segs[s.employee_id].append(s)
    rows = []
    for e in employees:
        containers = _containers(book, e.pk, d, d)
        warnings = []
        plan = []
        if default and containers:
            try:
                plan = engine.build_plan(containers, [engine.PlannedSegment(s.shift_date, s.start_at, s.end_at, s.activity.code, s.pk)
                                                      for s in segs[e.pk]], default.code)
            except engine.PlanError as exc:
                warnings.append(str(exc))
        cdicts = [_container_dict(c, book, e.pk) for c in containers]
        lunch = sum(c["lunch_minutes"] for c in cdicts)
        meal = sum(s.seconds for s in segs[e.pk] if s.activity.category == ActivityType.Category.MEAL)
        if lunch and meal < lunch * 60:
            warnings.append(f"El horario incluye {lunch} min de almuerzo y hay {fmt_duration(meal)} programados como almuerzo.")
        if not containers:
            warnings.append("Sin horario (contenedor) para esta fecha: descanso o sin AP de horario vigente.")
        rows.append({**employee_dict(e), "containers": cdicts, "segments": [segment_dict(s) for s in segs[e.pk]],
                     "plan": [_plan_block_dict(b, acts) for b in plan], "warnings": warnings})
    return {"date": d.isoformat(), "default_activity": default.code if default else None, "rows": rows}


def _parse_clock(value, field: str) -> time:
    """HH:MM o HH:MM:SS (24 h). Fase 18: los segundos se conservan, sin redondeo."""
    text = str(value or "").strip()
    try:
        parts = [int(x) for x in text.split(":")]
        if len(parts) not in (2, 3):
            raise ValueError
        return time(*parts)
    except (ValueError, TypeError):
        raise AdhErrors({field: "Hora HH:MM o HH:MM:SS (24 h), p. ej. 10:15 o 10:15:30."}) from None


def resolve_times(shift_date: date, start: time, end: time, containers: list[engine.Container]) -> tuple[datetime, datetime, engine.Container]:
    """Ubica HH:MM–HH:MM dentro de un contenedor de la fecha de turno (un turno nocturno puede seguir al día siguiente)."""
    for base in (shift_date, shift_date + timedelta(days=1)):
        s = datetime.combine(base, start)
        e = datetime.combine(base, end)
        if e <= s:
            e += timedelta(days=1)
        c = engine.segment_container(s, e, containers)
        if c is not None:
            return s, e, c
    shown = ", ".join(f"{hm(c.start)}–{hm(c.end)}" for c in containers)
    raise AdhError(f"El segmento {_t(start)}–{_t(end)} no cabe dentro del turno del {fmt(shift_date)} ({shown}).", "outside_container")


def _t(t: time) -> str:
    return f"{t:%H:%M:%S}" if t.second else f"{t:%H:%M}"


def _closed(employee: Employee, start: date, end: date, what: str):
    cutoff = closed_cutoff_hit(employee, start, end)
    if cutoff:
        raise AdhError(f"El corte {cutoff.code} (asistencia del {fmt(cutoff.cutoff_start)} al {fmt(cutoff.cutoff_end)}) está "
                       f"cerrado: no se pueden {what} en esas fechas.", "cutoff_closed", 409)


def _activity(code, *, allow_system: bool = False) -> ActivityType:
    a = ActivityType.objects.filter(code=str(code or "").strip().upper(), is_active=True).first()
    if a is None:
        raise AdhErrors({"activity": "Elija una actividad activa."})
    if a.system_role and not allow_system:
        raise AdhErrors({"activity": f"{a.name} la inserta el sistema (asistencia); no se coloca a mano."})
    return a


# ================================================================ Fase 19: reglas de asistencia y respaldo por AP
def attendance_setting(employee: Employee) -> GridSetting:
    """Reglas de la Management Unit del agente (o las globales): tolerancia de lateness y duración que exige AP."""
    m = AgentMembership.objects.filter(employee=employee, is_active=True).first()
    s = GridSetting.objects.filter(group_id=m.group_id).first() if m else None
    return s or GridSetting.objects.filter(group__isnull=True).first() or GridSetting()


def backing_ap(employee: Employee, folio, field: str = "folio") -> PersonnelAction:
    """AP de respaldo: existente, del mismo empleado y APROBADA."""
    folio = str(folio or "").strip().upper()
    pa = PersonnelAction.objects.select_related("action_type").filter(folio=folio).first() if folio else None
    if pa is None:
        raise AdhErrors({field: "Indique el folio de una AP aprobada del agente (respaldo del cambio)."})
    if pa.employee_id != employee.pk:
        raise AdhErrors({field: f"La AP {pa.folio} es de otro empleado."})
    if pa.status != PersonnelAction.Status.APPROVED:
        raise AdhErrors({field: f"La AP {pa.folio} está «{pa.get_status_display()}»: el respaldo debe ser una AP aprobada."})
    return pa


def is_full_day(s: datetime, e: datetime, container: engine.Container) -> bool:
    return s <= container.start and e >= container.end


def ap_reason(activity: ActivityType, s: datetime, e: datetime, container: engine.Container, setting: GridSetting) -> str | None:
    """Por qué el segmento exige AP (None = WFM lo coloca libremente)."""
    if activity.requires_ap:
        return f"{activity.name} exige una AP aprobada (respaldo legal ante el Ministerio de Trabajo)."
    if is_full_day(s, e, container):
        return "El segmento cubre el día completo del turno: el cambio exige una AP aprobada."
    secs = int((e - s).total_seconds())
    if setting.ap_required_seconds and secs >= setting.ap_required_seconds:
        return f"Cambio mayor ({fmt_duration(secs)}; desde {fmt_duration(setting.ap_required_seconds)} se exige AP aprobada)."
    return None


def check_duration_kind(activity: ActivityType, s: datetime, e: datetime, container: engine.Container) -> None:
    full = is_full_day(s, e, container)
    if full and not activity.allows_full_day and not activity.is_default:
        raise AdhError(f"{activity.name} no puede cubrir el día completo del turno.", "full_day_not_allowed")
    if not full and not activity.allows_partial:
        raise AdhError(f"{activity.name} solo se programa para el día completo ({hm(container.start)}–{hm(container.end)}).",
                       "full_day_only")


@contextmanager
def unlocked_segments():
    """Permite al SERVICIO reemplazar segmentos bloqueados: el trigger TR_adh_schedule_segment_locked (50073) rechaza
    cualquier otro DELETE / UPDATE de un Lateness o una ausencia."""
    mssql = connection.vendor == "microsoft"
    if mssql:
        with connection.cursor() as c:
            c.execute("EXEC sp_set_session_context @key = N'adh.replace_locked', @value = 1")
    try:
        yield
    finally:
        if mssql:
            with connection.cursor() as c:
                c.execute("EXEC sp_set_session_context @key = N'adh.replace_locked', @value = NULL")


def _locked_error(segment: ScheduleSegment, verb: str) -> AdhError:
    return AdhError(f"{segment.activity.name} {hm(segment.start_at)}–{hm(segment.end_at)} lo insertó el sistema y está bloqueado: no "
                    f"se puede {verb}; solo se reemplaza con un segmento respaldado por una AP aprobada (justificación).", "locked", 409)


@transaction.atomic
def save_segment(employee: Employee, data: dict, *, segment: ScheduleSegment | None = None, user=None, request=None,
                 audit: bool = True, origin: str = ScheduleSegment.Origin.WFM) -> ScheduleSegment:
    if segment is not None and segment.is_locked:
        raise _locked_error(segment, "mover ni editar")
    shift_date = parse_any_date(data.get("shift_date")) if "shift_date" in data or segment is None else segment.shift_date
    if shift_date is None:
        raise AdhErrors({"shift_date": "Indique la fecha del turno."})
    activity = _activity(data.get("activity")) if "activity" in data or segment is None else segment.activity
    start = _parse_clock(data.get("start"), "start") if "start" in data or segment is None else segment.start_at.time()
    end = _parse_clock(data.get("end"), "end") if "end" in data or segment is None else segment.end_at.time()
    if start == end:
        raise AdhErrors({"end": "El fin debe ser distinto del inicio."})
    book = ScheduleBook([employee.pk], shift_date, shift_date)
    containers = _containers(book, employee.pk, shift_date, shift_date)
    if not containers:
        raise AdhError(f"{employee.employee_code} no tiene horario (contenedor) el {fmt(shift_date)}: el segmento se programa "
                       "dentro del turno que asignó la AP.", "no_container")
    s, e, container = resolve_times(shift_date, start, end, containers)
    if (e - s) < timedelta(seconds=MIN_SEGMENT_SECONDS):
        raise AdhErrors({"end": f"Un segmento dura al menos {fmt_duration(MIN_SEGMENT_SECONDS)}."})
    clash = (ScheduleSegment.objects.filter(employee=employee, start_at__lt=e, end_at__gt=s).exclude(pk=getattr(segment, "pk", None))
             .select_related("activity").first())
    if clash:
        hint = " (bloqueado: reemplácelo con una AP)" if clash.is_locked else ": ajuste o elimine ese segmento"
        raise AdhError(f"Se traslapa con {clash.activity.name} de {hm(clash.start_at)} a {hm(clash.end_at)}{hint}.", "overlap", 409)
    _closed(employee, s.date(), e.date(), "programar segmentos")
    if segment is not None:
        _closed(employee, segment.start_at.date(), segment.end_at.date(), "modificar segmentos")
    # Fase 19: día completo / parcial y respaldo por AP (Ministerio de Trabajo).
    check_duration_kind(activity, s, e, container)
    reason = ap_reason(activity, s, e, container, attendance_setting(employee))
    pa = None
    if data.get("folio"):
        pa = backing_ap(employee, data["folio"])
    elif segment is not None and segment.personnel_action_id and "folio" not in data:
        pa = segment.personnel_action
    if reason and pa is None:
        raise AdhError(f"{reason} Indique el folio de la AP (o tramítela en Acciones de personal).", "ap_required", 409)
    created = segment is None
    before = None if created else _seg_snapshot(segment)
    segment = segment or ScheduleSegment(employee=employee, created_by=user if getattr(user, "pk", None) else None, origin=origin)
    assignment = next((a for a in book.assignments_on(employee.pk, shift_date) if a.label == container.label), None)
    segment.shift_date, segment.activity, segment.start_at, segment.end_at = shift_date, activity, s, e
    segment.assignment, segment.personnel_action = assignment, pa
    if origin == ScheduleSegment.Origin.REQUEST:
        segment.origin = origin
    segment.notes = str(data.get("notes", segment.notes) or "")[:200]
    segment.save()
    if audit:
        after = _seg_snapshot(segment)
        dates = sorted({shift_date.isoformat(), *([before["shift_date"]] if before else [])})
        was = (f" (antes: {before['activity_name']} {hm(datetime.fromisoformat(before['start']))}–"
               f"{hm(datetime.fromisoformat(before['end']))})") if before else ""
        backing = f" con la AP {pa.folio}" if pa else ""
        via = " (solicitud aprobada)" if origin == ScheduleSegment.Origin.REQUEST else ""
        record("adh_segment_created" if created else "adh_segment_updated", Category.WFM,
               f"Segmento {activity.name} {hm(s)}–{hm(e)} del {fmt(shift_date)} {'programado' if created else 'modificado'} "
               f"para {employee.employee_code}{backing}{via}{was}.", request=request, actor=user, target=employee,
               details={"shift_date": shift_date.isoformat(), "shift_dates": dates, "segment_id": segment.pk,
                        "folio": pa.folio if pa else None, "origin": segment.origin, "before": before, "after": after})
    return segment


def _seg_snapshot(seg: ScheduleSegment) -> dict:
    return {"shift_date": seg.shift_date.isoformat(), "activity": seg.activity.code, "activity_name": seg.activity.name,
            "start": iso(seg.start_at), "end": iso(seg.end_at), "seconds": seg.seconds, "notes": seg.notes,
            "origin": seg.origin, "is_locked": seg.is_locked,
            "folio": seg.personnel_action.folio if seg.personnel_action_id else None}


def bulk_segments(employees: list[Employee], date_from: date, date_to: date, data: dict, *, user=None, request=None) -> dict:
    """Programa el mismo segmento a varios agentes y fechas; cada omisión se informa con su motivo."""
    date_from, date_to = _check_range(date_from, date_to)
    days = (date_to - date_from).days + 1
    if not employees:
        raise AdhError("Elija al menos un agente.", "no_employees")
    if len(employees) * days > MAX_BULK_ITEMS:
        raise AdhError(f"Demasiados segmentos en una sola operación (máx. {MAX_BULK_ITEMS}).", "too_many")
    activity = _activity(data.get("activity"))
    if activity.requires_ap:
        raise AdhError(f"{activity.name} exige una AP aprobada por agente: prográmela en la grilla con el folio de cada AP.",
                       "ap_required", 409)
    created, skipped, rest = [], [], 0
    for e in employees:
        for i in range(days):
            d = date_from + timedelta(days=i)
            try:
                with transaction.atomic():
                    seg = save_segment(e, {**data, "folio": "", "shift_date": d.isoformat()}, user=user, audit=False)
                created.append(seg.pk)
            except AdhError as exc:
                if exc.code == "no_container":
                    rest += 1
                else:
                    skipped.append({"employee_code": e.employee_code, "date": d.isoformat(), "reason": exc.message})
            except AdhErrors as exc:
                skipped.append({"employee_code": e.employee_code, "date": d.isoformat(), "reason": str(exc)})
    record("adh_segment_bulk", Category.WFM,
           f"Programación masiva: {len(created)} segmentos {data.get('activity')} {data.get('start')}–{data.get('end')} del "
           f"{fmt(date_from)} al {fmt(date_to)} ({len(employees)} agentes, {len(skipped)} omitidos).", request=request, actor=user,
           details={"date_from": date_from.isoformat(), "date_to": date_to.isoformat(), "activity": data.get("activity"),
                    "start": data.get("start"), "end": data.get("end"), "employees": [e.employee_code for e in employees][:MAX_EMPLOYEES],
                    "segment_ids": created[:MAX_BULK_ITEMS]})
    return {"created": len(created), "skipped": skipped, "rest_days": rest}


@transaction.atomic
def delete_segment(segment: ScheduleSegment, *, user=None, request=None, via_request: bool = False) -> None:
    if segment.is_locked:
        raise _locked_error(segment, "eliminar")
    _closed(segment.employee, segment.start_at.date(), segment.end_at.date(), "eliminar segmentos")
    summary = (f"Segmento {segment.activity.name} {hm(segment.start_at)}–{hm(segment.end_at)} del {fmt(segment.shift_date)} "
               f"eliminado para {segment.employee.employee_code}{' (solicitud aprobada)' if via_request else ''}.")
    before = _seg_snapshot(segment)
    seg_id = segment.pk
    segment.delete()
    record("adh_segment_deleted", Category.WFM, summary, request=request, actor=user, target=segment.employee,
           details={"shift_date": before["shift_date"], "shift_dates": [before["shift_date"]], "segment_id": seg_id,
                    "before": before, "after": None})


@transaction.atomic
def replace_segment(segment: ScheduleSegment, data: dict, *, user=None, request=None,
                    origin: str = ScheduleSegment.Origin.WFM) -> ScheduleSegment:
    """Reemplaza un segmento BLOQUEADO (Lateness / Unjustified Absence / Legal Benefit Lunch) por uno documentado.

    * Siempre exige el folio de una AP APROBADA del agente (justificación, permiso, falla de sistema…).
    * `start` / `end` (opcionales) acotan el reemplazo dentro del segmento bloqueado: lo que quede fuera sigue bloqueado.
    * `scope = "day"` (ausencia): reemplaza toda la ausencia del día (incluido el Legal Benefit Lunch) por un segmento que
      cubre esos tramos (p. ej. Paid Sick Time con su AP).
    """
    if not segment.is_locked:
        raise AdhError("Solo los segmentos bloqueados (Lateness / ausencia) se reemplazan; los demás se editan.", "not_locked")
    employee = segment.employee
    pa = backing_ap(employee, data.get("folio"))
    activity = _activity(data.get("activity"))
    _closed(employee, segment.start_at.date(), segment.end_at.date(), "reemplazar segmentos")
    book = ScheduleBook([employee.pk], segment.shift_date, segment.shift_date)
    containers = _containers(book, employee.pk, segment.shift_date, segment.shift_date)
    container = engine.segment_container(segment.start_at, segment.end_at, containers)
    if container is None:
        raise AdhError("El segmento ya no está dentro de un turno vigente.", "outside_container", 409)
    absence_roles = (ActivityType.SystemRole.ABSENCE, ActivityType.SystemRole.LEGAL_LUNCH)
    day_scope = data.get("scope") == "day" and segment.activity.system_role in absence_roles
    if day_scope:
        targets = [x for x in ScheduleSegment.objects.filter(employee=employee, is_locked=True, start_at__gte=container.start,
                                                             end_at__lte=container.end).select_related("activity", "personnel_action")
                   if x.activity.system_role in absence_roles]
        s, e = min(x.start_at for x in targets), max(x.end_at for x in targets)
        others = ScheduleSegment.objects.filter(employee=employee, start_at__lt=e, end_at__gt=s).exclude(pk__in=[x.pk for x in targets])
        if others.exists():
            raise AdhError("Entre la ausencia hay otros segmentos: reemplace cada tramo por separado.", "overlap", 409)
    else:
        targets = [segment]
        s, e = segment.start_at, segment.end_at
        if data.get("start") or data.get("end"):
            s, e, _ = resolve_times(segment.shift_date, _parse_clock(data.get("start") or hm(segment.start_at), "start"),
                                    _parse_clock(data.get("end") or hm(segment.end_at), "end"), containers)
        if not (segment.start_at <= s < e <= segment.end_at):
            raise AdhErrors({"start": f"El reemplazo debe quedar dentro de {hm(segment.start_at)}–{hm(segment.end_at)}."})
    check_duration_kind(activity, s, e, container)
    befores = [_seg_snapshot(x) for x in targets]
    leftovers = [] if day_scope else [(a, b) for a, b in ((segment.start_at, s), (e, segment.end_at)) if b > a]
    with unlocked_segments():
        for x in targets:
            x.delete()
    for a, b in leftovers:
        ScheduleSegment.objects.create(employee=employee, shift_date=segment.shift_date, assignment_id=segment.assignment_id,
                                       activity=segment.activity, start_at=a, end_at=b, notes=segment.notes,
                                       origin=ScheduleSegment.Origin.SYSTEM, is_locked=True)
    new = ScheduleSegment.objects.create(
        employee=employee, shift_date=segment.shift_date, assignment_id=segment.assignment_id, activity=activity,
        start_at=s, end_at=e, notes=str(data.get("notes") or f"Reemplaza {segment.activity.name} (AP {pa.folio})")[:200],
        origin=origin, personnel_action=pa, created_by=user if getattr(user, "pk", None) else None,
    )
    record("adh_segment_replaced", Category.WFM,
           f"{segment.activity.name} {hm(s)}–{hm(e)} del {fmt(segment.shift_date)} reemplazado por {activity.name} con la AP "
           f"{pa.folio} para {employee.employee_code}" + (f"; {len(leftovers)} tramo(s) siguen bloqueados" if leftovers else "") + ".",
           request=request, actor=user, target=employee,
           details={"shift_date": segment.shift_date.isoformat(), "shift_dates": [segment.shift_date.isoformat()],
                    "segment_id": new.pk, "folio": pa.folio, "origin": origin, "replaced": befores,
                    "before": befores[0] if len(befores) == 1 else {"activity_name": segment.activity.name, "start": iso(s),
                                                                     "end": iso(e), "segments": len(befores)},
                    "after": _seg_snapshot(new)})
    return new


# ================================================================ justificaciones por AP
def exception_dict(x: AdherenceException) -> dict:
    pa = x.personnel_action
    return {"id": x.pk, "employee_code": x.employee.employee_code, "full_name": x.employee.full_name,
            "start": iso(x.start_at), "end": iso(x.end_at), "is_paid": x.is_paid, "reason": x.reason,
            "folio": pa.folio, "action_type": pa.action_type.name, "effective_date": pa.effective_date}


@transaction.atomic
def save_exception(employee: Employee, data: dict, *, user=None, request=None) -> AdherenceException:
    errors = {}
    folio = str(data.get("folio") or "").strip().upper()
    pa = PersonnelAction.objects.select_related("action_type").filter(folio=folio).first() if folio else None
    if pa is None:
        errors["folio"] = "Indique el folio de una AP existente."
    elif pa.employee_id != employee.pk:
        errors["folio"] = f"La AP {pa.folio} es de otro empleado."
    elif pa.status != PersonnelAction.Status.APPROVED:
        errors["folio"] = f"La AP {pa.folio} está «{pa.get_status_display()}»: solo una AP aprobada justifica tiempo."
    start = parse_wall_clock(data.get("start"), keep_seconds=True)
    end = parse_wall_clock(data.get("end"), keep_seconds=True)
    if start is None:
        errors["start"] = "Fecha y hora de inicio (hora local, AAAA-MM-DDTHH:MM[:SS])."
    if end is None:
        errors["end"] = "Fecha y hora de fin (hora local, AAAA-MM-DDTHH:MM[:SS])."
    elif start and end <= start:
        errors["end"] = "El fin debe ser posterior al inicio."
    elif start and end - start > timedelta(days=MAX_RANGE_DAYS):
        errors["end"] = f"Una justificación cubre como máximo {MAX_RANGE_DAYS} días."
    reason = str(data.get("reason") or "").strip()[:200]
    if not reason:
        errors["reason"] = "Indique el motivo."
    if errors:
        raise AdhErrors(errors)
    _closed(employee, start.date(), end.date(), "registrar justificaciones")
    x = AdherenceException.objects.create(employee=employee, personnel_action=pa, start_at=start, end_at=end,
                                          is_paid=bool(data.get("is_paid", True)), reason=reason,
                                          created_by=user if getattr(user, "pk", None) else None)
    record("adh_exception_created", Category.WFM,
           f"Justificación {fmt(start.date())} {hm(start)} → {fmt(end.date())} {hm(end)} con la AP {pa.folio} para "
           f"{employee.employee_code} ({'pagada' if x.is_paid else 'no pagada'}).", request=request, actor=user, target=employee,
           details={"exception_id": x.pk, "folio": pa.folio, "start": iso(start), "end": iso(end), "is_paid": x.is_paid,
                    "reason": reason, "shift_dates": dates_between(start, end)})
    return x


def dates_between(start: datetime, end: datetime) -> list[str]:
    """Fechas de turno que toca una ventana (incluye la víspera: un turno nocturno empieza el día anterior)."""
    first, last = start.date() - timedelta(days=1), (end - timedelta(seconds=1)).date()
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)][:MAX_RANGE_DAYS + 2]


@transaction.atomic
def delete_exception(x: AdherenceException, *, user=None, request=None) -> None:
    _closed(x.employee, x.start_at.date(), x.end_at.date(), "eliminar justificaciones")
    summary = (f"Justificación con la AP {x.personnel_action.folio} ({fmt(x.start_at.date())} {hm(x.start_at)} → "
               f"{fmt(x.end_at.date())} {hm(x.end_at)}) eliminada para {x.employee.employee_code}.")
    details = {"exception_id": x.pk, "folio": x.personnel_action.folio, "start": iso(x.start_at), "end": iso(x.end_at),
               "is_paid": x.is_paid, "reason": x.reason, "shift_dates": dates_between(x.start_at, x.end_at)}
    x.delete()
    record("adh_exception_deleted", Category.WFM, summary, request=request, actor=user, target=x.employee, details=details)


# ================================================================ cálculo
def _actual(seg: StatusSegment, end_fallback: datetime) -> engine.Actual:
    aux = seg.aux_code
    paid = aux.paid if aux else seg.primary_status.is_paid
    label = seg.primary_status.label + (f" · {aux.full_name}" if aux else "")
    return engine.Actual(local_naive(seg.start_at), local_naive(seg.end_at) if seg.end_at else end_fallback,
                         seg.primary_status.code, aux.code if aux else None, aux.parent.code if aux and aux.parent_id else None,
                         paid, label, seg.pk)


def evaluate(employees: list[Employee], date_from: date, date_to: date, *, now: datetime | None = None) -> dict[int, engine.Result]:
    """Resultado del motor por agente para las FECHAS DE TURNO del rango (se evalúa hasta `now`, hora local)."""
    date_from, date_to = _check_range(date_from, date_to)
    now = now or now_local()
    default = default_activity()
    activities = engine_activities()
    ids = [e.pk for e in employees]
    lo, hi = date_from - timedelta(days=1), date_to + timedelta(days=1)
    window_start = datetime.combine(lo, time())
    window_end = min(datetime.combine(hi + timedelta(days=1), time()), now)
    book = ScheduleBook(ids, lo, hi)
    segments = defaultdict(list)
    for s in ScheduleSegment.objects.filter(employee_id__in=ids, shift_date__range=(lo, hi)).select_related("activity"):
        segments[s.employee_id].append(engine.PlannedSegment(s.shift_date, s.start_at, s.end_at, s.activity.code, s.pk))
    actual = defaultdict(list)
    if window_end > window_start:
        qs = StatusSegment.objects.filter(employee_id__in=ids, start_at__lt=aware(window_end)).filter(
            Q(end_at__isnull=True) | Q(end_at__gt=aware(window_start))).select_related("primary_status", "aux_code", "aux_code__parent")
        for seg in qs.order_by("start_at"):
            if seg.primary_status.is_logged_in:
                actual[seg.employee_id].append(_actual(seg, now))
    just = defaultdict(list)
    for x in AdherenceException.objects.filter(employee_id__in=ids, start_at__lt=window_end + timedelta(days=1),
                                               end_at__gt=window_start).select_related("personnel_action"):
        just[x.employee_id].append(engine.Justification(x.start_at, x.end_at, x.is_paid, x.pk, x.personnel_action.folio))
    out = {}
    for e in employees:
        try:
            plan = engine.build_plan(_containers(book, e.pk, lo, hi), segments[e.pk], default.code)
        except engine.PlanError as exc:
            raise AdhError(f"{e.employee_code}: {exc}", "invalid_plan", 409) from None
        res = engine.evaluate(plan, actual[e.pk], just[e.pk], activities, window_start=window_start, window_end=max(window_end, window_start))
        res.days = {d: t for d, t in res.days.items() if date_from <= d <= date_to}
        res.deviations = [x for x in res.deviations if date_from <= x.day <= date_to]
        res.plan = [b for b in res.plan if date_from <= b.shift_date <= date_to]
        out[e.pk] = res
    return out


def _sum(days: list[engine.DayTotals]) -> dict:
    total = engine.DayTotals(date.min)
    for t in days:
        for k in ("scheduled", "scheduled_paid", "in_adherence", "out_of_adherence", "justified", "justified_scheduled", "logged",
                  "logged_in_container", "paid_valid", "billable", "primary_work", "secondary_paid", "unpaid_excess"):
            setattr(total, k, getattr(total, k) + getattr(t, k))
    d = total.as_dict()
    d.pop("date")
    return d


def deviation_dict(x: engine.Deviation, acts: dict[str, ActivityType]) -> dict:
    a = acts.get(x.expected) if x.expected else None
    return {"kind": x.kind, "kind_label": dict(Deviation.Kind.choices)[x.kind], "date": x.day.isoformat(),
            "start": iso(x.start), "end": iso(x.end), "seconds": x.seconds,
            "expected": x.expected, "expected_name": a.name if a else None,
            "actual": x.actual.label if x.actual else "Sin sesión (Offline)",
            "actual_primary": x.actual.primary if x.actual else None, "actual_aux": x.actual.aux if x.actual else None}


def report(employees: list[Employee], date_from: date, date_to: date) -> dict:
    if len(employees) > MAX_EMPLOYEES:
        raise AdhError(f"Demasiados agentes (máx. {MAX_EMPLOYEES}): filtre por grupo.", "too_many")
    results = evaluate(employees, date_from, date_to)
    acts = {a.code: a for a in ActivityType.objects.all()}
    rows, all_days = [], []
    for e in employees:
        res = results[e.pk]
        days = [res.days[d] for d in sorted(res.days)]
        all_days.extend(days)
        counts = defaultdict(int)
        for x in res.deviations:
            counts[x.kind] += 1
        rows.append({**employee_dict(e), "totals": _sum(days), "days": [t.as_dict() for t in days],
                     "deviation_counts": dict(counts)})
    return {"from": date_from.isoformat(), "to": date_to.isoformat(), "rows": rows, "totals": _sum(all_days),
            "computed_until": iso(min(now_local(), datetime.combine(date_to + timedelta(days=2), time()))),
            "activities": {k: {"name": a.name, "color": a.color} for k, a in acts.items()}}


def detail(employee: Employee, d: date) -> dict:
    res = evaluate([employee], d, d)[employee.pk]
    acts = {a.code: a for a in ActivityType.objects.all()}
    t = res.days.get(d) or engine.DayTotals(d)
    blocks = res.plan
    # Ventana: el turno y la actividad real del día, ±1 h, en horas completas (o el día calendario si no hay nada).
    day0, day1 = datetime.combine(d, time()), datetime.combine(d + timedelta(days=1), time())
    real = [a for a in res.actuals if a.end > day0 - timedelta(hours=6) and a.start < day1 + timedelta(hours=6)]
    starts = [b.start for b in blocks] + [a.start for a in real if not blocks or a.end > min(b.start for b in blocks) - timedelta(hours=4)]
    ends = [b.end for b in blocks] + [a.end for a in real if not blocks or a.start < max(b.end for b in blocks) + timedelta(hours=4)]
    if starts and ends:
        lo = max(day0 - timedelta(hours=6), min(starts).replace(minute=0, second=0) - timedelta(hours=1))
        hi = min(day1 + timedelta(hours=6), max(ends).replace(minute=0, second=0) + timedelta(hours=2))
    else:
        lo, hi = day0, day1
    actual = [{"start": iso(max(a.start, lo)), "end": iso(min(a.end, hi)), "primary": a.primary, "aux": a.aux, "label": a.label,
               "paid": a.paid} for a in res.actuals if a.end > lo and a.start < hi]
    justif = [{"start": iso(j.start), "end": iso(j.end), "is_paid": j.is_paid, "folio": j.label}
              for j in res.justifications if j.end > lo and j.start < hi]
    return {**employee_dict(employee), "date": d.isoformat(), "window": {"start": iso(lo), "end": iso(hi)},
            "totals": t.as_dict(), "plan": [_plan_block_dict(b, acts) for b in blocks], "actual": actual, "justifications": justif,
            "deviations": [deviation_dict(x, acts) for x in res.deviations]}


@transaction.atomic
def compute_and_store(employees: list[Employee], date_from: date, date_to: date, *, user=None, request=None,
                      audit: bool = True) -> dict:
    """Guarda el cálculo de los días YA TERMINADOS (antes de hoy) para nómina y calidad; omite los cortes cerrados."""
    date_from, date_to = _check_range(date_from, date_to)
    today = now_local().date()
    last = min(date_to, today - timedelta(days=1))
    if last < date_from:
        raise AdhError("Solo se guardan días terminados (anteriores a hoy).", "not_closed")
    results = evaluate(employees, date_from, last)
    acts = {a.code: a.pk for a in ActivityType.objects.all()}
    from apps.acd.models import AuxCode, PrimaryStatus

    statuses = {s.code: s.pk for s in PrimaryStatus.objects.all()}
    auxes = {a.code: a.pk for a in AuxCode.objects.all()}
    stamp = timezone.now()
    stored = skipped = 0
    frozen = []
    for e in employees:
        res = results[e.pk]
        cutoff = closed_cutoff_hit(e, date_from, last)
        locked = set()
        if cutoff:
            from apps.scheduling.models import AttendanceCutoff

            for c in AttendanceCutoff.objects.filter(cycle=cutoff.cycle, status="CLOSED", cutoff_start__lte=last, cutoff_end__gte=date_from):
                for i in range((c.cutoff_end - c.cutoff_start).days + 1):
                    locked.add(c.cutoff_start + timedelta(days=i))
            frozen.append({"employee_code": e.employee_code, "cutoff": cutoff.code})
        days = [d for d in (date_from + timedelta(days=i) for i in range((last - date_from).days + 1)) if d not in locked]
        AdherenceDay.objects.filter(employee=e, shift_date__in=days).delete()
        for d in days:
            t = res.days.get(d)
            if t is None or (not t.scheduled and not t.logged):
                skipped += 1
                continue
            row = AdherenceDay.objects.create(
                employee=e, shift_date=d, scheduled_seconds=t.scheduled, scheduled_paid_seconds=t.scheduled_paid,
                in_adherence_seconds=t.in_adherence, out_of_adherence_seconds=t.out_of_adherence, justified_seconds=t.justified,
                logged_seconds=t.logged, logged_in_container_seconds=t.logged_in_container, paid_valid_seconds=t.paid_valid,
                billable_seconds=t.billable, primary_work_seconds=t.primary_work, secondary_paid_seconds=t.secondary_paid,
                unpaid_excess_seconds=t.unpaid_excess,
                adherence_pct=Decimal(str(t.adherence_pct)) if t.adherence_pct is not None else None,
                conformance_pct=Decimal(str(t.conformance_pct)) if t.conformance_pct is not None else None,
                computed_at=stamp, computed_by=user if getattr(user, "pk", None) else None,
            )
            Deviation.objects.bulk_create([Deviation(
                day=row, employee=e, shift_date=d, kind=x.kind, start_at=x.start, end_at=x.end, seconds=x.seconds,
                expected_activity_id=acts.get(x.expected), actual_status_id=statuses.get(x.actual.primary) if x.actual else None,
                actual_aux_id=auxes.get(x.actual.aux) if x.actual and x.actual.aux else None,
            ) for x in res.deviations if x.day == d])
            stored += 1
    if audit:
        record("adh_computed", Category.WFM,
               f"Adherencia guardada del {fmt(date_from)} al {fmt(last)}: {stored} días-agente ({len(employees)} agentes"
               + (f", {len(frozen)} con cortes cerrados omitidos" if frozen else "") + ").", request=request, actor=user)
    return {"stored": stored, "skipped_empty": skipped, "frozen": frozen, "until": last.isoformat()}


# ================================================================ Fase 17: recálculo tras cambiar el plan
def day_metrics(employee: Employee, d: date) -> dict | None:
    """Adherencia en vivo del agente en la fecha de turno (None si el día aún no empieza o no hay plan válido)."""
    if d > now_local().date():
        return None
    try:
        res = evaluate([employee], d, d)[employee.pk]
    except AdhError:
        return None
    t = res.days.get(d)
    return {**t.as_dict(), "deviations": len(res.deviations)} if t else None


def refresh_after_plan_change(employee: Employee, d: date, *, user=None) -> dict:
    """Tras programar / mover / eliminar un segmento: adherencia en vivo del día y, si ese día ya estaba GUARDADO para
    nómina y calidad (adh_adherence_day), se vuelve a guardar con el plan nuevo."""
    restored = False
    if d < now_local().date() and AdherenceDay.objects.filter(employee=employee, shift_date=d).exists() \
            and not closed_cutoff_hit(employee, d, d):
        compute_and_store([employee], d, d, user=user, audit=False)
        restored = True
        day = AdherenceDay.objects.filter(employee=employee, shift_date=d).first()
        record("adh_day_recomputed", Category.WFM,
               f"Adherencia guardada del {fmt(d)} recalculada para {employee.employee_code} tras cambiar el plan"
               + (f": {day.adherence_pct} %." if day and day.adherence_pct is not None else "."),
               actor=user, target=employee, details={"shift_date": d.isoformat(), "shift_dates": [d.isoformat()]})
    return {"employee_code": employee.employee_code, "date": d.isoformat(), "metrics": day_metrics(employee, d),
            "stored_recomputed": restored}
