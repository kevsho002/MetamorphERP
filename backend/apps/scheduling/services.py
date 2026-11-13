"""Reglas de negocio de horarios, registros de tiempo, reporte teórico vs real y cortes de nómina.

La API solo orquesta; SQL Server es la última barrera (triggers de la migración 0002):
    50040  dos horarios PRINCIPALES del empleado en fechas que se cruzan (los adicionales conviven)
    50041  registros de tiempo (entrada/salida) traslapados para un empleado
    50042  dos reglas de nocturnidad activas para un país en fechas que se cruzan
    50043  periodos de PAGO traslapados en un ciclo
    50044  CORTES internos de asistencia traslapados en un ciclo (dimensión independiente, Fase 11)
    50045  hueco / colisión: el periodo de pago no inicia el día siguiente al fin del periodo anterior
    50046  hueco / colisión: el corte no inicia el día siguiente al cierre del corte anterior
    50047  dos reglas de almuerzo activas del país con el mismo umbral en fechas que se cruzan
    50048  el corte se mapea al periodo de pago de su ciclo que contiene su fecha de cierre
    50049  las fechas de un corte cerrado no se modifican

Periodos de pago y cortes internos (Fase 11): el periodo de pago (1–15 / 16–fin) fija las fechas oficiales de devengo
y pago; el corte interno (p. ej. 25–9 / 10–24) es la ventana en la que se cuentan las horas. Cada uno se valida contra
los de su misma dimensión; las horas de un periodo de pago son las de los cortes que se mapean a él.

Varias AP / turnos el mismo día (Fase 10): un día puede tener varios bloques (turno partido) y un empleado
puede tener, además de su horario principal, asignaciones ADICIONALES con fecha de fin. Las horas
programadas de todos los bloques y asignaciones se SUMAN por fecha de ocurrencia; ningún par de bloques
puede pedir las mismas horas (se valida al elaborar y al aplicar la AP).

Fecha de ocurrencia: todo tiempo (programado o laborado) se evalúa en el DÍA CALENDARIO en que
transcurre. Un turno que cruza la medianoche se reparte entre sus fechas, y cada porción conserva la
`shift_date` del turno (no se fragmenta en dos turnos).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.hcm.models import Employee
from apps.scheduling import engine
from apps.scheduling.models import (
    FAR_FUTURE, AttendanceCutoff, LunchRule, NightRule, PayCycle, PayPeriod, ScheduleAssignment, TimeRecord, TimeRecordDay,
)
from apps.system.audit import Category, record

MAX_REPORT_DAYS = 93
MAX_RECORD_MINUTES = 1440


def fmt(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "Now"


def fmt_dt(d: datetime | None) -> str:
    return d.strftime("%d/%m/%Y %H:%M") if d else "—"


def parse_any_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


_DT_PATTERNS = (
    "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S",
    "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%Y/%m/%d %H:%M",
)


def parse_wall_clock(value: Any, *, keep_seconds: bool = False) -> datetime | None:
    """Fecha y hora LOCAL (sin zona). Acepta ISO, dd/mm/aaaa hh:mm y datetimes de Excel.

    Las marcaciones de nómina van al minuto; `keep_seconds=True` conserva los segundos (planificación WFM, Fase 18)."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        result = timezone.make_naive(value) if timezone.is_aware(value) else value
        return result.replace(microsecond=0) if keep_seconds else result.replace(second=0, microsecond=0)
    text = str(value).strip()
    if text.endswith("Z") or re.search(r"[+-]\d{2}:\d{2}$", text):
        return None  # con zona horaria: se rechaza para no correr la fecha de ocurrencia
    for pattern in _DT_PATTERNS:
        try:
            parsed = datetime.strptime(text, pattern)
            return parsed if keep_seconds else parsed.replace(second=0)
        except ValueError:
            continue
    return None


def parse_minutes(minutes: Any = None, hours: Any = None) -> int | None:
    """Minutos desde `minutes` (entero) u `hours` (7.5 o 7:30)."""
    if minutes not in (None, ""):
        try:
            value = Decimal(str(minutes).strip())
        except InvalidOperation:
            return None
        return int(value) if value == value.to_integral_value() else None
    if hours not in (None, ""):
        text = str(hours).strip()
        match = re.match(r"^(\d{1,2}):([0-5]\d)$", text)
        if match:
            return int(match.group(1)) * 60 + int(match.group(2))
        try:
            return int((Decimal(text.replace(",", ".")) * 60).to_integral_value())
        except InvalidOperation:
            return None
    return None


@dataclass
class Check:
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    cleaned: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, field_name: str | None, message: str, code: str = "invalid") -> None:
        self.errors.append({"field": field_name, "message": message, "code": code})

    def warn(self, field_name: str | None, message: str, code: str = "warning") -> None:
        self.warnings.append({"field": field_name, "message": message, "code": code})

    def as_dict(self) -> dict:
        return {"valid": self.ok, "errors": self.errors, "warnings": self.warnings}


# ================================================================ nocturnidad
class NightRules:
    """Reglas de nocturnidad en memoria: `lookup(country_id)` devuelve d -> NightWindow vigente."""

    def __init__(self, country_ids: Iterable[int] | None = None):
        qs = NightRule.objects.filter(is_active=True)
        if country_ids is not None:
            qs = qs.filter(country_id__in=set(country_ids))
        self._by_country: dict[int, list[NightRule]] = defaultdict(list)
        self.by_id: dict[int, NightRule] = {}
        for rule in qs.order_by("effective_start_date"):
            self._by_country[rule.country_id].append(rule)
            self.by_id[rule.pk] = rule

    def rule_for(self, country_id: int, d: date) -> NightRule | None:
        for rule in self._by_country.get(country_id, ()):
            if rule.effective_start_date <= d <= (rule.effective_end_date or FAR_FUTURE):
                return rule
        return None

    def lookup(self, country_id: int):
        cache: dict[date, engine.NightWindow | None] = {}

        def _lookup(d: date):
            if d not in cache:
                rule = self.rule_for(country_id, d)
                cache[d] = rule.window() if rule else None
            return cache[d]

        return _lookup


def lunch_rules_for(country_id: int | None, on: date) -> list[LunchRule]:
    if not country_id:
        return []
    return list(LunchRule.objects.filter(country_id=country_id, is_active=True, effective_start_date__lte=on).filter(
        Q(effective_end_date__isnull=True) | Q(effective_end_date__gte=on)).order_by("min_block_minutes"))


def lunch_rule_dict(r: LunchRule) -> dict:
    return {"id": r.pk, "name": r.name, "min_block_minutes": r.min_block_minutes, "lunch_minutes": r.lunch_minutes,
            "enforcement": r.enforcement, "enforcement_label": r.get_enforcement_display(),
            "effective_start_date": r.effective_start_date, "effective_end_date": r.effective_end_date,
            "legal_reference": r.legal_reference}


# ================================================================ instancias de turno
class ScheduleBook:
    """Asignaciones (con su turno) de varios empleados, para expandir instancias de turno por fecha."""

    def __init__(self, employee_ids: Iterable[int], start: date, end: date):
        ids = list(set(employee_ids))
        self._by_employee: dict[int, list[ScheduleAssignment]] = defaultdict(list)
        if ids:
            qs = ScheduleAssignment.objects.filter(employee_id__in=ids, effective_start_date__lte=end).filter(
                Q(effective_end_date__isnull=True) | Q(effective_end_date__gte=start)
            ).select_related("personnel_action").order_by("effective_start_date")
            for a in qs:
                self._by_employee[a.employee_id].append(a)
        self._parsed: dict[int, engine.ShiftDefinition] = {}

    def assignments(self, employee_id: int) -> list[ScheduleAssignment]:
        return self._by_employee.get(employee_id, [])

    def assignments_on(self, employee_id: int, d: date) -> list[ScheduleAssignment]:
        """Todas las asignaciones vigentes ese día: el principal y las adicionales."""
        return [a for a in self._by_employee.get(employee_id, ()) if a.covers(d)]

    def assignment_on(self, employee_id: int, d: date) -> ScheduleAssignment | None:
        """Horario PRINCIPAL vigente ese día."""
        return next((a for a in self.assignments_on(employee_id, d) if a.mode == ScheduleAssignment.Mode.PRIMARY), None)

    def definition(self, a: ScheduleAssignment) -> engine.ShiftDefinition:
        if a.pk not in self._parsed:
            self._parsed[a.pk] = engine.parse_definition(a.definition)
        return self._parsed[a.pk]

    def instances(self, employee_id: int, start: date, end: date, night_lookup=None) -> list[engine.ShiftInstance]:
        """Instancias (una por bloque y asignación) cuya FECHA DE TURNO está en [start, end]."""
        out = []
        for d in engine.date_range(start, end):
            for a in self.assignments_on(employee_id, d):
                for inst in engine.shift_instances(self.definition(a), d, night_lookup=night_lookup):
                    inst.shift_code, inst.shift_name, inst.assignment_id, inst.mode = a.label, a.label, a.pk, a.mode
                    out.append(inst)
        out.sort(key=lambda i: i.start)
        return out


def employee_instances(employee: Employee, start: date, end: date, *, rules: NightRules | None = None) -> list[engine.ShiftInstance]:
    rules = rules or NightRules([employee.country_id])
    book = ScheduleBook([employee.pk], start, end)
    return book.instances(employee.pk, start, end, rules.lookup(employee.country_id))


# ================================================================ ciclos: periodos de pago y cortes internos (Fase 11)
def cycle_for(employee: Employee) -> PayCycle | None:
    return PayCycle.objects.filter(
        country_id=employee.country_id, pay_frequency=employee.pay_frequency, is_default=True, is_active=True
    ).first()


def cutoff_on(employee: Employee, d: date) -> AttendanceCutoff | None:
    """Corte interno de asistencia del ciclo del empleado que contiene la fecha de ocurrencia."""
    cycle = cycle_for(employee)
    if not cycle:
        return None
    return AttendanceCutoff.objects.select_related("cycle", "pay_period", "closed_by").filter(
        cycle=cycle, cutoff_start__lte=d, cutoff_end__gte=d).first()


def closed_cutoff_hit(employee: Employee, start: date, end: date | None) -> AttendanceCutoff | None:
    """Corte de asistencia CERRADO del ciclo del empleado que toca [start, end]."""
    cycle = cycle_for(employee)
    if not cycle:
        return None
    return AttendanceCutoff.objects.select_related("cycle", "pay_period").filter(
        cycle=cycle, status=AttendanceCutoff.Status.CLOSED, cutoff_start__lte=end or FAR_FUTURE, cutoff_end__gte=start,
    ).order_by("cutoff_start").first()


def _closed_message(cutoff: AttendanceCutoff, what: str) -> str:
    return (
        f"El corte {cutoff.code} del ciclo {cutoff.cycle.code} (asistencia del {fmt(cutoff.cutoff_start)} al "
        f"{fmt(cutoff.cutoff_end)}, se paga en {cutoff.pay_period.code}) está cerrado: no se pueden {what} en esas "
        "fechas. Si hace falta un ajuste, pida que se reabra el corte."
    )


class PeriodGenerationError(Exception):
    pass


MAX_TRANSITION_GAP_DAYS = 31


def _contiguous(items: list, start: date, end: date, *, start_of, end_of, what: str, cycle: PayCycle):
    """Encaja [start, end] a continuación del último elemento existente (periodos o cortes, cada uno por separado):
    devuelve el inicio ajustado, o None si queda cubierto / chocaría con uno posterior. Un hueco largo es error."""
    one = timedelta(days=1)
    if any(start_of(x) == start for x in items):
        return None
    prev = next((x for x in reversed(items) if start_of(x) < start), None)
    nxt = next((x for x in items if start_of(x) > start), None)
    if prev:
        if end <= end_of(prev):
            return None
        gap = (start - end_of(prev)).days - 1
        if gap > MAX_TRANSITION_GAP_DAYS:
            raise PeriodGenerationError(
                f"El ciclo {cycle.code} no tiene {what} entre el {fmt(end_of(prev) + one)} y el {fmt(start - one)}: "
                f"genere primero los años intermedios ({what} contiguos)."
            )
        start = end_of(prev) + one  # recorta la colisión o cubre el hueco (transición tras un cambio de regla)
    if nxt and end >= start_of(nxt):
        return None
    return start


def _period_row(p: PayPeriod) -> dict:
    return {"label": p.code, "period_start": p.period_start, "period_end": p.period_end, "id": p.pk}


@transaction.atomic
def generate_periods(cycle: PayCycle, year: int, *, user=None, request=None) -> dict:
    """Genera, por separado, los PERIODOS DE PAGO del año y sus CORTES INTERNOS de asistencia; lo existente
    (incluido lo editado a mano) no se toca.

    * Periodos de pago: contiguos al último periodo del ciclo (sin colisión ni hueco); un cambio de regla produce un
      periodo de transición.
    * Cortes: contiguos al último corte del ciclo, con su propia regla (p. ej. 25–9 / 10–24) y mapeados al periodo de
      pago que contiene su fecha de cierre. Se generan los cortes que se pagan en los periodos del año.
    Un hueco de más de un mes (p. ej. generar 2028 sin 2027) se rechaza: genere los años en orden.
    """
    rule = cycle.rule()
    periods = list(cycle.periods.order_by("period_start"))
    codes = {p.code for p in periods}
    created, skipped = [], 0
    for p in engine.generate_periods(rule, year):
        start = _contiguous(periods, p["period_start"], p["period_end"], start_of=lambda x: x.period_start,
                            end_of=lambda x: x.period_end, what="periodos de pago", cycle=cycle)
        code = p["label"] if p["label"] not in codes else f"{p['label']}-T"  # transición con la etiqueta de uno existente
        if start is None or code in codes:
            skipped += 1
            continue
        period = PayPeriod.objects.create(cycle=cycle, code=code, period_start=start, period_end=p["period_end"],
                                          payment_date=p["payment_date"])
        created.append(period)
        periods.append(period)
        periods.sort(key=lambda x: x.period_start)
        codes.add(code)

    cut = generate_cutoffs(cycle, year, periods=periods)
    if created or cut["created"]:
        record(
            "pay_periods_generated", Category.SCHEDULING,
            f"Ciclo {cycle.code}, {year}: {len(created)} periodos de pago y {cut['created']} cortes de asistencia generados "
            f"({skipped} periodos y {cut['skipped']} cortes ya existían).",
            request=request, actor=user, target_type="PayCycle", target_id=cycle.code,
            details={"year": year, "created": [p.code for p in created], "cutoffs": cut["codes"]},
        )
    return {"created": len(created), "skipped": skipped, "cutoffs_created": cut["created"], "cutoffs_skipped": cut["skipped"]}


def generate_cutoffs(cycle: PayCycle, year: int, *, periods: list[PayPeriod] | None = None) -> dict:
    """Cortes internos que se PAGAN en los periodos de pago del año (los periodos deben existir)."""
    periods = periods if periods is not None else list(cycle.periods.order_by("period_start"))
    target_ids = {p.pk for p in periods if p.period_start.year == year}
    if not target_ids:
        return {"created": 0, "skipped": 0, "codes": []}
    lo, hi = date(year - 1, 11, 1), date(year + 1, 1, 31)
    rows = [_period_row(p) for p in periods if p.period_end >= lo and p.period_start <= hi]
    cutoffs = list(cycle.cutoffs.order_by("cutoff_start"))
    codes = {c.code for c in cutoffs}
    created, skipped = [], 0
    for w in engine.cutoff_windows(cycle.rule(), rows):
        period_row = w["period"]
        if period_row["id"] not in target_ids:
            continue
        start = _contiguous(cutoffs, w["cutoff_start"], w["cutoff_end"], start_of=lambda x: x.cutoff_start,
                            end_of=lambda x: x.cutoff_end, what="cortes de asistencia", cycle=cycle)
        if start is None:
            skipped += 1
            continue
        code, n = f"C-{period_row['label']}", 2
        while code in codes:
            code, n = f"C-{period_row['label']}-{n}", n + 1
        cutoff = AttendanceCutoff.objects.create(cycle=cycle, pay_period_id=period_row["id"], code=code,
                                                 cutoff_start=start, cutoff_end=w["cutoff_end"])
        created.append(cutoff)
        cutoffs.append(cutoff)
        cutoffs.sort(key=lambda x: x.cutoff_start)
        codes.add(code)
    return {"created": len(created), "skipped": skipped, "codes": [c.code for c in created]}


def preview_cycle(cycle: PayCycle, year: int, limit: int = 4) -> list[dict]:
    """Primeros periodos de pago del año con los cortes que se pagarían en ellos (antes de generarlos)."""
    periods = engine.generate_periods(cycle.rule(), year)
    previous = engine.generate_periods(cycle.rule(), year - 1)[-2:]
    windows = engine.cutoff_windows(cycle.rule(), previous + periods)
    out = []
    for p in periods[:limit]:
        mine = [w for w in windows if w["period"] is p]
        out.append({**p, "cutoffs": [{"cutoff_start": w["cutoff_start"], "cutoff_end": w["cutoff_end"]} for w in mine]})
    return out


@transaction.atomic
def set_cutoff_status(cutoff: AttendanceCutoff, status: str, *, user=None, request=None) -> AttendanceCutoff:
    closing = status == AttendanceCutoff.Status.CLOSED
    cutoff.status = status
    cutoff.closed_at = timezone.now() if closing else None
    cutoff.closed_by = user if closing else None
    cutoff.save(update_fields=["status", "closed_at", "closed_by"])
    record(
        f"cutoff_{'closed' if closing else 'reopened'}", Category.SCHEDULING,
        f"Corte de asistencia {cutoff.code} del ciclo {cutoff.cycle.code} {'cerrado' if closing else 'reabierto'} "
        f"(asistencia {fmt(cutoff.cutoff_start)}–{fmt(cutoff.cutoff_end)}, se paga en {cutoff.pay_period.code}).",
        request=request, actor=user, target_type="AttendanceCutoff", target_id=str(cutoff.pk),
    )
    return cutoff


def _crosses(a: date, b: date) -> bool:
    return (a.year, a.month) != (b.year, b.month)


def cutoff_dict(c: AttendanceCutoff, *, with_period: bool = True) -> dict:
    out = {
        "id": c.pk, "code": c.code, "cycle": c.cycle.code,
        "cutoff_start": c.cutoff_start, "cutoff_end": c.cutoff_end,
        "days": (c.cutoff_end - c.cutoff_start).days + 1, "crosses_month": _crosses(c.cutoff_start, c.cutoff_end),
        "status": c.status, "status_label": c.get_status_display(), "closed_at": c.closed_at,
        "closed_by": c.closed_by.username if c.closed_by_id and c.closed_by else None, "notes": c.notes,
        "pay_period_id": c.pay_period_id,
    }
    if with_period:
        p = c.pay_period
        out["pay_period"] = {"id": p.pk, "code": p.code, "period_start": p.period_start, "period_end": p.period_end,
                             "payment_date": p.payment_date}
    return out


def period_dict(p: PayPeriod, cutoffs: list[AttendanceCutoff] | None = None) -> dict:
    """Periodo de PAGO con los cortes de asistencia que se pagan en él (`cutoff_start` / `cutoff_end` / `status`
    resumen esos cortes, para compatibilidad con el reporte por periodo)."""
    cutoffs = sorted(cutoffs if cutoffs is not None else p.cutoffs.select_related("cycle", "closed_by"), key=lambda c: c.cutoff_start)
    closed = sum(1 for c in cutoffs if c.status == AttendanceCutoff.Status.CLOSED)
    status = "NO_CUTOFF" if not cutoffs else "CLOSED" if closed == len(cutoffs) else "OPEN"
    return {
        "id": p.pk, "code": p.code, "cycle": p.cycle.code, "cycle_name": p.cycle.name,
        "period_start": p.period_start, "period_end": p.period_end, "payment_date": p.payment_date,
        "year": p.period_start.year, "month": p.period_start.month, "crosses_month": _crosses(p.period_start, p.period_end),
        "cutoffs": [cutoff_dict(c, with_period=False) for c in cutoffs],
        "cutoff_start": cutoffs[0].cutoff_start if cutoffs else None,
        "cutoff_end": cutoffs[-1].cutoff_end if cutoffs else None,
        "status": status,
        "status_label": {"NO_CUTOFF": "Sin corte", "CLOSED": "Asistencia cerrada", "OPEN": "Asistencia abierta"}[status],
    }


def payroll_hours(period: PayPeriod, employees=None) -> dict:
    """Motor de horas para planilla: por cada CORTE INTERNO mapeado al periodo de pago, horas teóricas y reales de
    cada empleado del ciclo en la ventana del corte; el total del periodo de pago es la suma de sus cortes."""
    cycle = period.cycle
    cutoffs = list(period.cutoffs.select_related("cycle", "closed_by").order_by("cutoff_start"))
    if employees is None:
        employees = Employee.objects.select_related("country").filter(country_id=cycle.country_id, pay_frequency=cycle.pay_frequency)
        if not cycle.is_default:
            employees = employees.none()  # los empleados se asignan al ciclo PREDETERMINADO de su país y frecuencia
    employees = list(employees.order_by("employee_code"))
    per_employee: dict[int, dict] = {}
    keys = ("scheduled_minutes", "scheduled_night_minutes", "worked_minutes", "worked_night_minutes", "night_premium_minutes")
    for c in cutoffs:
        report = hours_report(employees, c.cutoff_start, c.cutoff_end, include_empty=True)
        by_code = {r["employee_code"]: r for r in report["by_employee"]}
        for e in employees:
            row = per_employee.setdefault(e.pk, {
                "employee_code": e.employee_code, "full_name": e.full_name, "country": e.country.country_code,
                "cutoffs": [], **{k: 0 for k in keys},
            })
            got = by_code.get(e.employee_code)
            part = {"cutoff": c.code, **{k: (got or {}).get(k, 0) for k in keys}}
            row["cutoffs"].append(part)
            for k in keys:
                row[k] += part[k]
    rows = [r for r in per_employee.values() if r["scheduled_minutes"] or r["worked_minutes"]]
    for r in rows:
        r["variance_minutes"] = r["worked_minutes"] - r["scheduled_minutes"]
    totals = {k: sum(r[k] for r in rows) for k in keys}
    totals["variance_minutes"] = totals["worked_minutes"] - totals["scheduled_minutes"]
    totals["employees"] = len(rows)
    return {"period": period_dict(period, cutoffs), "cutoffs": [cutoff_dict(c) for c in cutoffs], "rows": rows, "totals": totals,
            "all_closed": bool(cutoffs) and all(c.status == AttendanceCutoff.Status.CLOSED for c in cutoffs)}


# ================================================================ horario atómico por día (formato AP)
def night_window_for(country_id: int | None, on: date) -> engine.NightWindow | None:
    if not country_id:
        return None
    rule = NightRules([country_id]).rule_for(country_id, on)
    return rule.window() if rule else None


def evaluate_schedule(raw, *, country_id: int | None, on: date, warnings: list | None = None) -> tuple[dict | None, list[dict]]:
    """Valida el horario de una AP (JSON o notación compacta) y devuelve el JSON anotado con horas diurnas y
    nocturnas por bloque (regla de nocturnidad del país vigente a la fecha efectiva), o la lista de errores.

    Las reglas de almuerzo del país se aplican por bloque continuo: las «obligatorias» son errores y las de
    «advertencia» se agregan a `warnings` (si se pasa la lista).
    """
    try:
        raw = engine.coerce_schedule(raw)
        parsed = engine.parse_definition(raw)
    except engine.DefinitionError as exc:
        return None, exc.errors
    window = night_window_for(country_id, on)
    breakdown = engine.day_breakdown(parsed, window)
    errors = engine.check_declared_hours(raw, breakdown)
    lunch_errors, lunch_warnings = engine.check_lunch(parsed, [r.rule() for r in lunch_rules_for(country_id, on)])
    errors += lunch_errors
    if warnings is not None:
        warnings.extend(lunch_warnings)
    if errors:
        return None, errors
    return engine.annotated_json(parsed, window), []


def schedule_summary(definition: dict) -> dict:
    """Filas por día (Lunes…Domingo) de un horario guardado: bloques y totales del día; totales semanales."""
    parsed = engine.parse_definition(definition)
    days = (definition or {}).get("days") or {}
    rows, total_day, total_night = [], 0, 0
    for key in engine.DAY_KEYS:
        blocks = parsed.blocks(key)
        if not blocks:
            rows.append({"day": key, "label": engine.DAY_LABELS[key], "rest": True, "blocks": []})
            continue
        stored = {}
        for b in engine.day_blocks_raw(days.get(key)) or []:
            t = engine.parse_hhmm(b.get("start")) if isinstance(b, dict) else None
            if t:
                stored[engine.hhmm(t)] = b
        block_rows = []
        for index, spec in enumerate(blocks):
            st = stored.get(engine.hhmm(spec.start), {})
            night_m = int(st.get("night_minutes", 0) or 0)
            day_m = int(st.get("day_minutes", spec.net_minutes - night_m))
            block_rows.append({**spec.as_dict(), "block": index, "day_minutes": day_m, "night_minutes": night_m,
                               "net_minutes": spec.net_minutes, "gross_minutes": spec.gross_minutes,
                               "crosses_midnight": spec.crosses_midnight})
        day_m = sum(b["day_minutes"] for b in block_rows)
        night_m = sum(b["night_minutes"] for b in block_rows)
        total_day += day_m
        total_night += night_m
        rows.append({
            "day": key, "label": engine.DAY_LABELS[key], "rest": False, "blocks": block_rows,
            "start": block_rows[0]["start"], "end": block_rows[-1]["end"],
            "lunch_minutes": sum(b["lunch_minutes"] for b in block_rows),
            "day_minutes": day_m, "night_minutes": night_m, "net_minutes": sum(b["net_minutes"] for b in block_rows),
            "crosses_midnight": any(b["crosses_midnight"] for b in block_rows), "is_split": len(block_rows) > 1,
        })
    return {"days": rows, "weekly_minutes": parsed.weekly_net_minutes, "weekly_day_minutes": total_day,
            "weekly_night_minutes": total_night, "lunch_allocation": parsed.lunch_allocation,
            "has_split_days": parsed.has_split_days}


def preview_schedule(raw, *, country_id: int | None, on: date, start: date | None = None, days: int = 7) -> dict:
    warnings: list[dict] = []
    definition, errors = evaluate_schedule(raw, country_id=country_id, on=on, warnings=warnings)
    if errors:
        raise engine.DefinitionError(errors)
    parsed = engine.parse_definition(definition)
    lookup = NightRules([country_id]).lookup(country_id) if country_id else None
    start = start or on
    instances = [i for d in engine.date_range(start, start + timedelta(days=days - 1))
                 for i in engine.shift_instances(parsed, d, night_lookup=lookup)]
    per_day: dict[date, dict] = defaultdict(lambda: {"minutes": 0, "night_minutes": 0, "shift_dates": []})
    for inst in instances:
        for seg in inst.segments:
            row = per_day[seg.occurrence_date]
            row["minutes"] += seg.net_minutes
            row["night_minutes"] += seg.night_net_minutes
            if inst.shift_date.isoformat() not in row["shift_dates"]:
                row["shift_dates"].append(inst.shift_date.isoformat())
    window = night_window_for(country_id, on)
    return {
        "definition": definition, "summary": schedule_summary(definition), "warnings": warnings,
        "lunch_rules": [lunch_rule_dict(r) for r in lunch_rules_for(country_id, on)],
        "night_rule": {"start": engine.hhmm(window.start), "end": engine.hhmm(window.end), "surcharge_percent": window.surcharge_percent,
                       "name": window.name} if window else None,
        "by_occurrence_date": [{"occurrence_date": d.isoformat(), **v} for d, v in sorted(per_day.items())],
    }


# ================================================================ horarios vigentes (los crea una AP)
def assignment_dict(a: ScheduleAssignment, today: date | None = None) -> dict:
    today = today or timezone.localdate()
    end = a.effective_end_date
    pa = a.personnel_action if a.personnel_action_id else None
    return {
        "id": a.pk, "folio": pa.folio if pa else None, "action_type": pa.action_type.name if pa else None,
        "is_initial": bool(pa and pa.is_initial), "mode": a.mode, "mode_label": a.get_mode_display(),
        "weekly_minutes": a.weekly_minutes, "schedule": schedule_summary(a.definition),
        "effective_start_date": a.effective_start_date, "effective_end_date": end, "is_now": end is None,
        "is_current": a.effective_start_date <= today <= (end or FAR_FUTURE),
        "is_future": a.effective_start_date > today, "notes": a.notes,
    }


def _collision(definition: dict, start: date, end: date | None, others: list[tuple[str, dict, date, date | None]]) -> str | None:
    """¿El horario nuevo [start, end] pide horas que ya pide otra asignación? (mismas horas = colisión)"""
    try:
        new = engine.parse_definition(definition)
    except engine.DefinitionError:
        return None
    one = timedelta(days=1)
    for label, other_def, o_start, o_end in others:
        lo, hi = max(start, o_start), min(end or FAR_FUTURE, o_end or FAR_FUTURE)
        if lo > hi:
            continue
        other = engine.parse_definition(other_def)
        window_end = min(hi, lo + timedelta(days=8))
        mine = [i for d in engine.date_range(lo, window_end) for i in engine.shift_instances(new, d)]
        theirs = [i for d in engine.date_range(max(o_start, lo - one), min(o_end or FAR_FUTURE, window_end + one))
                  for i in engine.shift_instances(other, d)]
        hit = engine.first_instance_collision(mine, theirs)
        if hit:
            a, b = hit
            return (
                f"El bloque {a.start:%H:%M}–{a.end:%H:%M} del {fmt(a.shift_date)} pide las mismas horas que {label} "
                f"({b.start:%H:%M}–{b.end:%H:%M} del {fmt(b.shift_date)}): dos asignaciones no pueden cruzarse."
            )
    return None


def check_schedule_application(employee: Employee, effective_date: date, *, definition: dict | None = None,
                               mode: str = ScheduleAssignment.Mode.PRIMARY, end_date: date | None = None) -> Check:
    """¿Se puede aplicar un horario desde `effective_date`? (lo usan la validación y la aprobación de la AP)

    PRINCIPAL: reemplaza el principal vigente (que se cierra el día anterior); no puede haber otro principal que
    inicie en esa fecha o después. ADICIONAL: convive con el principal hasta `end_date`. En ambos casos los
    bloques no pueden pedir las mismas horas que otra asignación vigente en esas fechas.
    """
    check = Check()
    Mode = ScheduleAssignment.Mode
    one = timedelta(days=1)
    existing = list(ScheduleAssignment.objects.filter(employee=employee).select_related("personnel_action"))
    if mode == Mode.PRIMARY:
        later = next((a for a in sorted(existing, key=lambda a: a.effective_start_date)
                      if a.mode == Mode.PRIMARY and a.effective_start_date >= effective_date), None)
        if later:
            check.error("effective_date", (
                f"Ya hay un horario principal vigente desde el {fmt(later.effective_start_date)} ({later.label}): una AP de "
                "horario no puede tener fecha efectiva igual o anterior a la de un horario ya aplicado. Use una fecha posterior."
            ), "schedule_overlap")
    else:
        if end_date is None:
            check.error("values.vigente_hasta", "Una asignación adicional necesita su fecha de fin («vigente hasta»).", "required")
        elif end_date < effective_date:
            check.error("values.vigente_hasta", "La fecha de fin no puede ser anterior a la fecha efectiva.")
    if definition and check.ok:
        others = []
        for a in existing:
            a_end = a.effective_end_date
            if mode == Mode.PRIMARY and a.mode == Mode.PRIMARY and a.effective_start_date < effective_date:
                a_end = min(a_end or FAR_FUTURE, effective_date - one)  # el principal anterior se cierra el día previo
            others.append((f"el horario {a.label} ({a.get_mode_display().lower()})", a.definition, a.effective_start_date, a_end))
        message = _collision(definition, effective_date, end_date if mode == Mode.ADDITIONAL else None, others)
        if message:
            check.error("effective_date", message, "schedule_collision")
    hit = closed_cutoff_hit(employee, effective_date, end_date if mode == Mode.ADDITIONAL else None)
    if hit:
        check.error("effective_date", _closed_message(hit, "cambiar los horarios"), "closed_period")
    return check


@transaction.atomic
def apply_schedule(employee: Employee, definition: dict, effective_date: date, *, action=None, user=None,
                   mode: str = ScheduleAssignment.Mode.PRIMARY, end_date: date | None = None) -> ScheduleAssignment:
    """Aplica el horario de una AP aprobada.

    Principal: cierra el principal vigente el día anterior y abre el nuevo («Now»); las asignaciones adicionales
    siguen hasta su fecha de fin. Adicional: se suma al principal entre la fecha efectiva y su fecha de fin.
    """
    Mode = ScheduleAssignment.Mode
    check = check_schedule_application(employee, effective_date, definition=definition, mode=mode, end_date=end_date)
    if not check.ok:
        raise ValueError(" ".join(e["message"] for e in check.errors))
    if mode == Mode.PRIMARY:
        previous = ScheduleAssignment.objects.select_for_update().filter(
            employee=employee, mode=Mode.PRIMARY, effective_start_date__lt=effective_date,
        ).filter(Q(effective_end_date__isnull=True) | Q(effective_end_date__gte=effective_date)).first()
        if previous:
            previous.effective_end_date = effective_date - timedelta(days=1)
            previous.save(update_fields=["effective_end_date", "updated_at"])
    return ScheduleAssignment.objects.create(
        employee=employee, personnel_action=action, definition=definition, effective_start_date=effective_date,
        effective_end_date=end_date if mode == Mode.ADDITIONAL else None, mode=mode,
        created_by=user if getattr(user, "pk", None) else None,
        notes=f"Aplicado por la AP {action.folio}" if action else "",
    )


# ================================================================ registros de tiempo
def check_time_record(employee: Employee, data: dict, *, pending: list[dict] | None = None) -> Check:
    """Valida un registro: intervalo (start_at/end_at, hora local) o duración (occurrence_date + minutes|hours)."""
    check = Check()
    c = check.cleaned
    raw_start, raw_end = data.get("start_at"), data.get("end_at")
    has_interval = raw_start not in (None, "") or raw_end not in (None, "")
    source = str(data.get("source") or TimeRecord.Source.MANUAL).strip().upper()
    if source not in TimeRecord.Source.values:
        check.error("source", f"Origen «{source}» no reconocido (use {', '.join(TimeRecord.Source.values)}).")
    c["source"] = source
    c["external_ref"] = str(data.get("external_ref") or "").strip()[:100]
    c["notes"] = str(data.get("notes") or "").strip()[:300]

    if has_interval:
        start, end = parse_wall_clock(raw_start), parse_wall_clock(raw_end)
        if start is None:
            check.error("start_at", "Entrada inválida: use AAAA-MM-DD HH:MM en hora local (sin zona horaria).", "required" if raw_start in (None, "") else "invalid")
        if end is None:
            check.error("end_at", "Salida inválida: use AAAA-MM-DD HH:MM en hora local (sin zona horaria).", "required" if raw_end in (None, "") else "invalid")
        if start and end:
            if end <= start:
                check.error("end_at", "La salida debe ser posterior a la entrada (si cruza la medianoche, use la fecha del día siguiente).")
            elif (end - start) > timedelta(minutes=MAX_RECORD_MINUTES):
                check.error("end_at", "Un registro no puede durar más de 24 horas; divídalo en varios.")
        c.update(kind=TimeRecord.Kind.INTERVAL, start_at=start, end_at=end)
        if check.ok:
            c["occurrence_date"] = start.date()
            c["minutes"] = int((end - start).total_seconds() // 60)
            c["last_date"] = (end - timedelta(minutes=1)).date()
    else:
        occurrence = parse_any_date(data.get("occurrence_date"))
        minutes = parse_minutes(data.get("minutes"), data.get("hours"))
        if occurrence is None:
            check.error("occurrence_date", "Indique entrada y salida, o la fecha de ocurrencia y las horas laboradas.", "required")
        if minutes is None:
            check.error("minutes", "Indique los minutos (entero) o las horas (7.5 o 7:30) laboradas.", "required")
        elif not 0 < minutes <= MAX_RECORD_MINUTES:
            check.error("minutes", "Las horas reportadas para un día deben estar entre 1 minuto y 24 horas.")
        c.update(kind=TimeRecord.Kind.DURATION, start_at=None, end_at=None, occurrence_date=occurrence, minutes=minutes)
        if check.ok:
            c["last_date"] = occurrence
    if not check.ok:
        return check

    first, last = c["occurrence_date"], c["last_date"]
    if first < employee.hire_date:
        check.error("start_at" if has_interval else "occurrence_date", f"Es anterior al ingreso del empleado ({fmt(employee.hire_date)}).")
    if employee.termination_date and last > employee.termination_date:
        check.error("end_at" if has_interval else "occurrence_date", f"Es posterior a la terminación del empleado ({fmt(employee.termination_date)}).")
    if first > timezone.localdate():
        check.error("start_at" if has_interval else "occurrence_date", "No se registra tiempo laborado en fechas futuras.")

    # Duplicados y traslapes
    if c["kind"] == TimeRecord.Kind.INTERVAL:
        clash = TimeRecord.objects.filter(
            employee=employee, kind=TimeRecord.Kind.INTERVAL, start_at__lt=c["end_at"], end_at__gt=c["start_at"]
        ).first()
        if clash:
            check.error("start_at", f"Se traslapa con otro registro del empleado ({fmt_dt(clash.start_at)} → {fmt_dt(clash.end_at)}).", "overlap")
        for other in pending or ():
            if other["employee_id"] == employee.pk and other["kind"] == "INTERVAL" and other["start_at"] < c["end_at"] and c["start_at"] < other["end_at"]:
                check.error("start_at", f"Se traslapa con la fila {other['row']} del mismo archivo.", "overlap")
                break
    else:
        if TimeRecord.objects.filter(employee=employee, kind=TimeRecord.Kind.DURATION, occurrence_date=first, source=c["source"]).exists():
            check.error("occurrence_date", f"Ya hay horas reportadas por {c['source']} para el {fmt(first)}; elimine ese registro antes de cargar otro.", "duplicate")
        for other in pending or ():
            if other["employee_id"] == employee.pk and other["kind"] == "DURATION" and other["occurrence_date"] == first and other["source"] == c["source"]:
                check.error("occurrence_date", f"La fila {other['row']} del mismo archivo ya reporta horas de ese día.", "duplicate")
                break
        if TimeRecord.objects.filter(employee=employee, kind=TimeRecord.Kind.INTERVAL, occurrence_date=first).exists():
            check.warn("occurrence_date", "Ese día ya tiene marcaciones de entrada/salida: las horas se sumarán.", "mixed_kinds")

    hit = closed_cutoff_hit(employee, first, last)
    if hit:
        check.error("start_at" if has_interval else "occurrence_date", _closed_message(hit, "registrar tiempos"), "closed_period")
    return check


def _trace_shift_date(employee: Employee, cleaned: dict, book: ScheduleBook) -> date | None:
    """Fecha del turno programado al que pertenece el registro (mayor traslape)."""
    if cleaned["kind"] == TimeRecord.Kind.INTERVAL:
        start, end = cleaned["start_at"], cleaned["end_at"]
        best, best_overlap = None, 0
        for inst in book.instances(employee.pk, start.date() - timedelta(days=1), end.date()):
            ov = engine._overlap(start, end, inst.start, inst.end)
            if ov > best_overlap:
                best, best_overlap = inst.shift_date, ov
        return best
    d = cleaned["occurrence_date"]
    for inst in book.instances(employee.pk, d - timedelta(days=1), d):
        if any(s.occurrence_date == d for s in inst.segments):
            return inst.shift_date
    return None


@transaction.atomic
def save_time_record(employee: Employee, cleaned: dict, *, user=None, upload_ref: str = "",
                     rules: NightRules | None = None, book: ScheduleBook | None = None) -> TimeRecord:
    rules = rules or NightRules([employee.country_id])
    first = cleaned["occurrence_date"]
    book = book or ScheduleBook([employee.pk], first - timedelta(days=1), cleaned["last_date"])
    shift_date = _trace_shift_date(employee, cleaned, book)
    rec = TimeRecord.objects.create(
        employee=employee, kind=cleaned["kind"], start_at=cleaned["start_at"], end_at=cleaned["end_at"],
        occurrence_date=first, minutes=cleaned["minutes"], shift_date=shift_date, source=cleaned["source"],
        external_ref=cleaned["external_ref"], notes=cleaned["notes"], upload_ref=upload_ref,
        created_by=user if getattr(user, "pk", None) else None,
    )
    if rec.kind == TimeRecord.Kind.INTERVAL:
        segments = engine.segments_for_interval(rec.start_at, rec.end_at, night_lookup=rules.lookup(employee.country_id))
        days = [TimeRecordDay(
            record=rec, employee=employee, occurrence_date=s.occurrence_date, start_at=s.start, end_at=s.end,
            minutes=s.net_minutes, night_minutes=s.night_net_minutes, night_rule_id=s.night_rule_id, shift_date=shift_date,
        ) for s in segments]
    else:
        days = [TimeRecordDay(record=rec, employee=employee, occurrence_date=first, minutes=rec.minutes, shift_date=shift_date)]
    TimeRecordDay.objects.bulk_create(days)
    return rec


def time_record_dict(r: TimeRecord) -> dict:
    return {
        "id": r.pk, "employee_code": r.employee.employee_code, "kind": r.kind, "kind_label": r.get_kind_display(),
        "start_at": r.start_at.isoformat(timespec="minutes") if r.start_at else None,
        "end_at": r.end_at.isoformat(timespec="minutes") if r.end_at else None,
        "occurrence_date": r.occurrence_date, "minutes": r.minutes, "shift_date": r.shift_date,
        "source": r.source, "source_label": r.get_source_display(), "external_ref": r.external_ref,
        "notes": r.notes, "upload_ref": r.upload_ref, "created_at": r.created_at,
        "created_by": r.created_by.username if r.created_by_id and r.created_by else None,
        "days": [{
            "occurrence_date": d.occurrence_date,
            "start_at": d.start_at.isoformat(timespec="minutes") if d.start_at else None,
            "end_at": d.end_at.isoformat(timespec="minutes") if d.end_at else None,
            "minutes": d.minutes, "night_minutes": d.night_minutes, "shift_date": d.shift_date,
        } for d in r.days.all()],
    }


@transaction.atomic
def create_time_record(employee: Employee, check: Check, *, user=None, request=None) -> TimeRecord:
    rec = save_time_record(employee, check.cleaned, user=user)
    record(
        "time_record_created", Category.SCHEDULING,
        f"Registro de tiempo de {employee.employee_code}: {rec} ({engine.fmt_minutes(rec.minutes)} h, {rec.get_source_display()}).",
        request=request, actor=user, target=employee, details={"time_record": rec.pk},
    )
    return rec


def check_time_record_delete(rec: TimeRecord) -> Check:
    check = Check()
    last = max((d.occurrence_date for d in rec.days.all()), default=rec.occurrence_date)
    hit = closed_cutoff_hit(rec.employee, rec.occurrence_date, last)
    if hit:
        check.error(None, _closed_message(hit, "eliminar tiempos"), "closed_period")
    return check


@transaction.atomic
def delete_time_record(rec: TimeRecord, *, user=None, request=None) -> None:
    employee, summary = rec.employee, str(rec)
    rec.delete()
    record("time_record_deleted", Category.SCHEDULING, f"Registro de tiempo de {employee.employee_code} eliminado: {summary}.",
           request=request, actor=user, target=employee)


TIME_COLUMNS = {
    "employee_code": {"employee_code", "employee", "id", "codigo", "código", "id_corporativo", "employeecode"},
    "start_at": {"start_at", "start", "entrada", "inicio", "clock_in", "actualstart"},
    "end_at": {"end_at", "end", "salida", "fin", "clock_out", "actualend"},
    "occurrence_date": {"occurrence_date", "date", "fecha", "fecha_ocurrencia", "workdate"},
    "minutes": {"minutes", "minutos", "workedminutes"},
    "hours": {"hours", "horas"},
    "source": {"source", "origen"},
    "external_ref": {"external_ref", "referencia", "ref"},
    "notes": {"notes", "notas"},
}
_ALIASES = {alias: key for key, aliases in TIME_COLUMNS.items() for alias in aliases}


def _normalize_row(raw: Any) -> tuple[dict, list[str]]:
    if not isinstance(raw, dict):
        return {}, []
    row, unknown = {}, []
    for k, v in raw.items():
        key = _ALIASES.get(str(k).strip().lower().replace(" ", "_"))
        if key:
            row[key] = v.strip() if isinstance(v, str) else v
        elif str(k).strip():
            unknown.append(str(k))
    return row, unknown


def process_time_upload(parsed, *, user=None, dry_run: bool = False, default_source: str = "IMPORT", request=None) -> dict:
    """Carga de registros de tiempo TODO o NADA: si una fila falla, no se guarda ninguna."""
    rows_out, pending = [], []
    unknown_cols: set[str] = set()
    codes = set()
    normalized = []
    for number, raw in parsed.rows:
        row, unknown = _normalize_row(raw)
        unknown_cols.update(unknown)
        row.setdefault("source", default_source)
        normalized.append((number, row))
        if row.get("employee_code"):
            codes.add(str(row["employee_code"]).strip().upper())
    employees = {e.employee_code: e for e in Employee.objects.filter(employee_code__in=codes).select_related("country")}

    for number, row in normalized:
        code = str(row.get("employee_code") or "").strip().upper()
        employee = employees.get(code)
        if not code:
            check = Check()
            check.error("employee_code", "Falta el ID corporativo del empleado (columna employee_code).", "required")
        elif not employee:
            check = Check()
            check.error("employee_code", f"No existe un empleado con el ID {code}.", "not_found")
        else:
            check = check_time_record(employee, row, pending=pending)
        entry = {"row": number, "employee_code": code, **check.as_dict()}
        if check.ok:
            c = check.cleaned
            pending.append({"row": number, "employee_id": employee.pk, **{k: c[k] for k in ("kind", "start_at", "end_at", "occurrence_date", "source")},
                            "_employee": employee, "_cleaned": c})
            entry.update(minutes=c["minutes"], occurrence_date=c["occurrence_date"], kind=c["kind"],
                         spans_days=c["last_date"] != c["occurrence_date"])
        rows_out.append(entry)

    errors = sum(1 for r in rows_out if not r["valid"])
    created = 0
    upload_ref = getattr(parsed, "sha256", "")[:64]
    if not errors and not dry_run:
        with transaction.atomic():
            ids = {p["employee_id"] for p in pending}
            dates = [p["_cleaned"]["occurrence_date"] for p in pending]
            rules = NightRules({p["_employee"].country_id for p in pending})
            book = ScheduleBook(ids, min(dates) - timedelta(days=1), max(p["_cleaned"]["last_date"] for p in pending))
            for p in pending:
                save_time_record(p["_employee"], p["_cleaned"], user=user, upload_ref=upload_ref, rules=rules, book=book)
                created += 1
            record(
                "time_records_uploaded", Category.SCHEDULING,
                f"Carga de registros de tiempo «{parsed.file_name}»: {created} registro(s) de {len(ids)} empleado(s).",
                request=request, actor=user, target_type="Upload", target_id=upload_ref[:16],
                details={"file": parsed.file_name, "rows": len(rows_out), "created": created},
            )
    notes = list(getattr(parsed, "notes", []))
    if unknown_cols:
        notes.append("Columnas ignoradas: " + ", ".join(sorted(unknown_cols)) + ".")
    if errors:
        summary = f"Se revisaron {len(rows_out)} filas y {errors} tienen errores: no se guardó ninguna. Corrija las filas marcadas y vuelva a cargar el archivo."
    elif dry_run:
        summary = f"Las {len(rows_out)} filas son válidas. Es solo una validación: no se guardó nada."
    else:
        summary = f"Se guardaron {created} registros de tiempo; las horas se asignaron a su fecha de ocurrencia."
    return {"total": len(rows_out), "valid": len(rows_out) - errors, "errors": errors, "created": created,
            "dry_run": dry_run, "summary": summary, "notes": notes, "rows": rows_out}


# ================================================================ reporte teórico vs real
FLAG_LABELS = {
    "OK": "Cumple", "SHORT": "Menos horas", "OVER": "Más horas", "ABSENT": "Sin registro",
    "UNSCHEDULED": "Sin turno programado", "PENDING": "Pendiente",
}


def _flag(scheduled: int, worked: int, d: date, today: date, tolerance: int) -> str:
    if scheduled and not worked:
        return "PENDING" if d >= today else "ABSENT"
    if worked and not scheduled:
        return "UNSCHEDULED"
    diff = worked - scheduled
    if abs(diff) <= tolerance:
        return "OK"
    return "OVER" if diff > 0 else "SHORT"


def hours_report(employees, date_from: date, date_to: date, *, tolerance: int = 0, include_empty: bool = False) -> dict:
    """Horas teóricas (turno asignado) frente a reales (registros), por empleado y FECHA DE OCURRENCIA."""
    employees = list(employees)
    ids = [e.pk for e in employees]
    rules = NightRules({e.country_id for e in employees})
    book = ScheduleBook(ids, date_from - timedelta(days=1), date_to)
    worked: dict[tuple[int, date], dict] = defaultdict(lambda: {"minutes": 0, "night_minutes": 0, "premium": 0.0, "records": 0, "shift_dates": set()})
    for d in TimeRecordDay.objects.filter(employee_id__in=ids, occurrence_date__range=(date_from, date_to)).select_related("night_rule"):
        w = worked[(d.employee_id, d.occurrence_date)]
        w["minutes"] += d.minutes
        w["night_minutes"] += d.night_minutes
        w["premium"] += d.night_minutes * float(d.night_rule.surcharge_percent if d.night_rule else 0) / 100
        w["records"] += 1
        if d.shift_date:
            w["shift_dates"].add(d.shift_date)

    today = timezone.localdate()
    rows, totals = [], defaultdict(int)
    by_employee = []
    for e in employees:
        lookup = rules.lookup(e.country_id)
        scheduled: dict[date, dict] = defaultdict(lambda: {"minutes": 0, "night_minutes": 0, "premium": 0.0, "actions": [], "shift_dates": set()})
        for inst in book.instances(e.pk, date_from - timedelta(days=1), date_to, lookup):
            for seg in inst.segments:
                if date_from <= seg.occurrence_date <= date_to:
                    s = scheduled[seg.occurrence_date]
                    s["minutes"] += seg.net_minutes
                    s["night_minutes"] += seg.night_net_minutes
                    s["premium"] += seg.night_net_minutes * seg.surcharge_percent / 100
                    if inst.shift_code not in s["actions"]:
                        s["actions"].append(inst.shift_code)
                    s["shift_dates"].add(inst.shift_date)
        emp_tot = defaultdict(int)
        for d in engine.date_range(date_from, date_to):
            s = scheduled.get(d)
            w = worked.get((e.pk, d))
            if not s and not w and not include_empty:
                continue
            sm, wm = (s["minutes"] if s else 0), (w["minutes"] if w else 0)
            rule = rules.rule_for(e.country_id, d)
            row = {
                "employee_code": e.employee_code, "full_name": e.full_name, "country": e.country.country_code,
                "occurrence_date": d, "weekday": engine.DAY_LABELS[engine.DAY_KEYS[d.weekday()]],
                "actions": s["actions"] if s else [],
                "shift_dates": sorted({*(s["shift_dates"] if s else ()), *(w["shift_dates"] if w else ())}),
                "scheduled_minutes": sm, "scheduled_night_minutes": s["night_minutes"] if s else 0,
                "worked_minutes": wm, "worked_night_minutes": w["night_minutes"] if w else 0,
                "night_premium_minutes": round(w["premium"]) if w else 0,
                "night_surcharge_percent": float(rule.surcharge_percent) if rule else None,
                "variance_minutes": wm - sm, "records": w["records"] if w else 0,
            }
            row["flag"] = _flag(sm, wm, d, today, tolerance) if (sm or wm) else "REST"
            row["flag_label"] = FLAG_LABELS.get(row["flag"], "Descanso")
            rows.append(row)
            for key in ("scheduled_minutes", "scheduled_night_minutes", "worked_minutes", "worked_night_minutes", "night_premium_minutes"):
                emp_tot[key] += row[key]
                totals[key] += row[key]
            if row["flag"] in ("ABSENT", "SHORT", "OVER", "UNSCHEDULED"):
                emp_tot[f"days_{row['flag'].lower()}"] += 1
                totals[f"days_{row['flag'].lower()}"] += 1
        if emp_tot:
            emp_tot["variance_minutes"] = emp_tot["worked_minutes"] - emp_tot["scheduled_minutes"]
            by_employee.append({"employee_code": e.employee_code, "full_name": e.full_name, "country": e.country.country_code, **emp_tot})
    totals["variance_minutes"] = totals["worked_minutes"] - totals["scheduled_minutes"]
    totals["employees"] = len(by_employee)
    return {"rows": rows, "by_employee": by_employee, "totals": dict(totals)}


# ================================================================ desglose de un día (fecha de ocurrencia)
def day_detail(employee: Employee, d: date) -> dict:
    """Todo lo que explica las horas de un empleado en UNA fecha de ocurrencia: bloques programados (de qué AP y
    de qué fecha de turno, incluida la porción de un turno que empezó el día anterior), tiempo registrado,
    nocturnidad, reglas de almuerzo, corte de nómina y AP con efecto ese día. Base para auditoría."""
    from apps.personnel_actions.models import PersonnelAction

    rules = NightRules([employee.country_id])
    book = ScheduleBook([employee.pk], d - timedelta(days=1), d)
    lookup = rules.lookup(employee.country_id)
    blocks = []
    for inst in book.instances(employee.pk, d - timedelta(days=1), d, lookup):
        segment = next((s for s in inst.segments if s.occurrence_date == d), None)
        if segment is None:
            continue
        blocks.append({
            **inst.as_dict(), "folio": inst.shift_code,
            "on_this_date": segment.as_dict(), "from_previous_day": inst.shift_date != d,
        })
    assignments = book.assignments_on(employee.pk, d)
    records = TimeRecord.objects.filter(employee=employee, days__occurrence_date=d).distinct().select_related(
        "employee", "created_by").prefetch_related("days")
    report = hours_report([employee], d, d, include_empty=True)
    row = report["rows"][0] if report["rows"] else None
    cutoff = cutoff_on(employee, d)
    night = rules.rule_for(employee.country_id, d)
    actions = PersonnelAction.objects.filter(employee=employee, effective_date=d).select_related("action_type").order_by("id")
    return {
        "employee_code": employee.employee_code, "full_name": employee.full_name, "country": employee.country.country_code,
        "hire_date": employee.hire_date, "termination_date": employee.termination_date,
        "date": d, "weekday": engine.DAY_LABELS[engine.DAY_KEYS[d.weekday()]],
        "previous_date": d - timedelta(days=1), "next_date": d + timedelta(days=1),
        "summary": row, "blocks": blocks,
        "assignments": [assignment_dict(a) for a in assignments],
        "records": [time_record_dict(r) for r in records],
        "night_rule": {"name": night.name, "start": night.start_time.strftime("%H:%M"), "end": night.end_time.strftime("%H:%M"),
                       "surcharge_percent": float(night.surcharge_percent)} if night else None,
        "lunch_rules": [lunch_rule_dict(r) for r in lunch_rules_for(employee.country_id, d)],
        "cutoff": cutoff_dict(cutoff) if cutoff else None,
        "period": period_dict(cutoff.pay_period) if cutoff else None,
        "actions_effective": [{"folio": a.folio, "action_type": a.action_type.name, "status": a.status,
                               "status_label": a.get_status_display()} for a in actions],
    }
