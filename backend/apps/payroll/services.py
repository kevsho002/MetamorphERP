"""Fase 20 — Servicios de planilla: insumos (Web Timer, segmentos WFM, adherencia, AP), cálculo, cierre y boletas.

Flujo de una planilla (una por periodo de pago del ciclo PREDETERMINADO de su país y frecuencia):

    calcular  (DRAFT / CALCULATED / CANCELLED → CALCULATED)  se puede repetir mientras no esté cerrada
    cerrar    (CALCULATED → APPROVED)  exige los cortes de asistencia cerrados y un cálculo posterior a su cierre;
              congela la planilla (SQL 50090) y genera EN MASA las boletas y los lotes por departamento
    pagar     (APPROVED → PAID)
    anular    (DRAFT / CALCULATED → CANCELLED)  libera las AP para otra planilla

El inventario de boletas físicas (RRHH) registra impresión, firma del colaborador y archivo por boleta o por lote.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.adherence.models import ActivityType, AdherenceDay, AdherenceException, ScheduleSegment
from apps.hcm.models import Employee
from apps.payroll import engine
from apps.payroll.models import (
    DeductionBracket, DeductionType, PayConcept, Payroll, PayrollDeduction, PayrollDetail, PayrollException, PayrollIteration,
    PayrollLine, PayrollRun, PayrollSetting, Payslip, PayslipBatch,
)
from apps.personnel_actions.models import ActionValue, Effect, PersonnelAction
from apps.scheduling.models import FAR_FUTURE, AttendanceCutoff, PayCycle, PayPeriod, TimeRecordDay
from apps.scheduling.services import NightRules, cycle_for
from apps.system.audit import record
from apps.system.models import AuditEvent

Category = AuditEvent.Category
CLOSED_STATUSES = ("APPROVED", "PAID")
STATUS_LABELS = {"DRAFT": "Borrador", "CALCULATED": "Calculada", "APPROVED": "Cerrada (boletas generadas)", "PAID": "Pagada",
                 "CANCELLED": "Anulada"}
FREQ_LABELS = dict(Employee.PayFrequency.choices)


class PayrollError(Exception):
    def __init__(self, message: str, code: str = "invalid", status: int = 409):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def fmt(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


def money(value) -> str:
    return f"{Decimal(value or 0):.2f}"


# ================================================================ parámetros
def setting_for(country_id: int, on: date) -> PayrollSetting | None:
    return PayrollSetting.objects.filter(country_id=country_id, is_active=True, effective_start_date__lte=on).filter(
        Q(effective_end_date__isnull=True) | Q(effective_end_date__gte=on)).order_by("-effective_start_date").first()


def params_of(s: PayrollSetting) -> engine.Params:
    return engine.Params(
        days_per_month=s.days_per_month, hours_per_day=s.hours_per_day, overtime_surcharge_percent=s.overtime_surcharge_percent,
        vacation_premium_percent=s.vacation_premium_percent, seventh_day_penalty=s.seventh_day_penalty,
        holiday_premium_percent=s.holiday_premium_percent,
    )


def legal_types(country_id: int, on: date) -> list[DeductionType]:
    """Versión vigente de cada retención del país en la fecha (la de inicio más reciente por código)."""
    qs = DeductionType.objects.filter(country_id=country_id, is_active=True, effective_start_date__lte=on).filter(
        Q(effective_end_date__isnull=True) | Q(effective_end_date__gte=on)).order_by("code", "-effective_start_date")
    out, seen = [], set()
    for t in qs:
        if t.code not in seen:
            seen.add(t.code)
            out.append(t)
    return out


def _brackets(rows) -> tuple[engine.Bracket, ...]:
    return tuple(engine.Bracket(b.lower_bound, b.upper_bound, b.rate, b.fixed_fee, b.excess_over) for b in rows)


def legal_rules(country_id: int, on: date, frequency: str) -> list[engine.LegalRule]:
    types = legal_types(country_id, on)
    brackets = defaultdict(list)
    for b in DeductionBracket.objects.filter(deduction_type__in=types).order_by("lower_bound"):
        brackets[(b.deduction_type_id, b.pay_frequency)].append(b)
    return [engine.LegalRule(
        id=t.deduction_type_id, code=t.code, name=t.name, category=t.category, party=t.party, method=t.calculation_method,
        rate=t.rate, fixed_amount=t.fixed_amount, base_cap=t.base_cap, reduces_taxable_base=t.reduces_taxable_base,
        order=t.calculation_order, brackets=_brackets(brackets[(t.deduction_type_id, frequency)]),
        monthly_brackets=_brackets(brackets[(t.deduction_type_id, "MONTHLY")]),
    ) for t in types]


def concept_map() -> dict[str, engine.Concept]:
    return {c.code: engine.Concept(c.code, c.name, c.kind, c.source, c.affects_social_security, c.affects_income_tax,
                                   c.calculation, c.display_order)
            for c in PayConcept.objects.filter(is_active=True)}


# ================================================================ periodos y ventanas
def windows_for(period: PayPeriod) -> list[tuple[date, date]]:
    """Ventanas de asistencia del periodo: sus cortes internos (Fase 11) o, si no tiene, las fechas del periodo."""
    cutoffs = list(period.cutoffs.order_by("cutoff_start"))
    if cutoffs:
        return [(c.cutoff_start, c.cutoff_end) for c in cutoffs]
    return [(period.period_start, period.period_end)]


def _clip(windows, lo: date, hi: date) -> list[tuple[date, date]]:
    out = []
    for a, b in windows:
        a, b = max(a, lo), min(b, hi)
        if a <= b:
            out.append((a, b))
    return out


def _in(windows, d: date) -> bool:
    return any(a <= d <= b for a, b in windows)


def payroll_code(period: PayPeriod) -> str:
    return f"{period.cycle.code}-{period.code}"[:40]


def closed_payroll_on(employee: Employee, d: date) -> str | None:
    """Código de la planilla CERRADA (o pagada) cuyo periodo cubre la fecha para el ciclo del empleado."""
    cycle = cycle_for(employee)
    if not cycle:
        return None
    cutoff = AttendanceCutoff.objects.filter(cycle=cycle, cutoff_start__lte=d, cutoff_end__gte=d).select_related("pay_period").first()
    period = cutoff.pay_period if cutoff else PayPeriod.objects.filter(cycle=cycle, period_start__lte=d, period_end__gte=d).first()
    if not period:
        return None
    run = PayrollRun.objects.filter(pay_period=period, payroll__payroll_status__in=CLOSED_STATUSES).select_related("payroll").first()
    return run.payroll.payroll_code if run else None


def eligible_employees(cycle: PayCycle, period: PayPeriod) -> tuple[list[Employee], list[str]]:
    """Colaboradores del país y la frecuencia del ciclo contratados en algún día del periodo (Fase 21: también los
    INACTIVOS por suspensión: el motor por horas no les paga los días suspendidos, pero sí lo laborado antes o después)."""
    base = Employee.objects.select_related("country", "cost_center").filter(
        country_id=cycle.country_id, pay_frequency=cycle.pay_frequency, hire_date__lte=period.period_end,
    ).filter(Q(termination_date__isnull=True) | Q(termination_date__gte=period.period_start)).order_by("employee_code")
    employees = list(base)
    inactive = [e.employee_code for e in employees if e.employment_status == Employee.Status.INACTIVE]
    return employees, inactive


# ================================================================ insumos por colaborador
@dataclass
class Gathered:
    inputs: dict[int, engine.EmployeeInput]
    windows: dict[int, list[tuple[date, date]]]


def _seconds(seg) -> int:
    return int((seg.end_at - seg.start_at).total_seconds())


def gather_inputs(employees: list[Employee], period: PayPeriod, windows: list[tuple[date, date]], *,
                  exclude_payroll_id: int | None = None, params: engine.Params | None = None) -> Gathered:
    """Insumos POR HORAS de cada colaborador (Fase 21), día por día dentro de las ventanas de asistencia del periodo:

    * programado: horas netas del horario vigente (ScheduleBook) por fecha de ocurrencia;
    * pagable: lo validado por la adherencia guardada (paid_valid) o, sin adherencia, el Web Timer hasta lo programado;
      los días de vacaciones (AP) se pagan como programados; las suspensiones no se programan ni se pagan;
    * feriados: las horas pagables de un día feriado generan su Holiday Segment y llevan el recargo del feriado;
    * nocturnidad: minutos nocturnos del Web Timer (regla del país) hasta lo pagable del día.
    """
    from apps.holidays.services import generate_segments, holidays_between
    from apps.personnel_actions.lifecycle import suspended_dates
    from apps.scheduling.services import ScheduleBook

    ids = [e.pk for e in employees]
    lo, hi = min(a for a, _ in windows), max(b for _, b in windows)
    calendar_days = (period.period_end - period.period_start).days + 1
    suspended = suspended_dates(ids, min(lo, period.period_start), max(hi, period.period_end))
    per_windows = {e.pk: _clip(windows, e.hire_date, e.termination_date or FAR_FUTURE) for e in employees}
    inputs: dict[int, engine.EmployeeInput] = {}
    for e in employees:
        employed = _clip([(period.period_start, period.period_end)], e.hire_date, e.termination_date or FAR_FUTURE)
        days = sum((b - a).days + 1 for a, b in employed)
        susp = sum(1 for d in suspended.get(e.pk, ()) if period.period_start <= d <= period.period_end and _in(employed, d))
        inputs[e.pk] = engine.EmployeeInput(
            monthly_salary=e.base_salary, frequency=e.pay_frequency, period_calendar_days=calendar_days,
            employed_calendar_days=max(0, days - susp), suspended_days=susp,
        )

    def active(emp_id: int, d: date) -> bool:
        return _in(per_windows[emp_id], d) and d not in suspended.get(emp_id, ())

    # ---- programado por fecha de ocurrencia (horario vigente de las AP)
    rules = NightRules({e.country_id for e in employees})
    book = ScheduleBook(ids, lo - timedelta(days=1), hi)
    scheduled: dict[tuple[int, date], int] = defaultdict(int)
    for e in employees:
        lookup = rules.lookup(e.country_id)
        for inst in book.instances(e.pk, lo - timedelta(days=1), hi, lookup):
            for seg in inst.segments:
                if lo <= seg.occurrence_date <= hi and active(e.pk, seg.occurrence_date):
                    scheduled[(e.pk, seg.occurrence_date)] += seg.net_minutes * 60

    # ---- Fase 22: programado del CORTE COMPLETO (base del rate): las fechas de los cortes internos, aunque el
    #      colaborador ingrese a mitad o se retire antes. Los días sin horario vigente se proyectan con el horario
    #      principal más cercano (el primero antes del ingreso; el último después del retiro).
    for e in employees:
        inputs[e.pk].cutoff_scheduled_seconds = cutoff_scheduled_seconds(book, e.pk, windows, rules.lookup(e.country_id))

    # ---- Web Timer y demás registros (bruto y nocturno)
    worked: dict[tuple[int, date], list[int]] = defaultdict(lambda: [0, 0])
    for t in TimeRecordDay.objects.filter(employee_id__in=ids, occurrence_date__range=(lo, hi)):
        if active(t.employee_id, t.occurrence_date):
            w = worked[(t.employee_id, t.occurrence_date)]
            w[0] += t.minutes * 60
            w[1] += t.night_minutes * 60

    # ---- adherencia guardada: lo validado para pago (Fase 16)
    adherence: dict[tuple[int, date], AdherenceDay] = {}
    for d in AdherenceDay.objects.filter(employee_id__in=ids, shift_date__range=(lo, hi)):
        if active(d.employee_id, d.shift_date):
            adherence[(d.employee_id, d.shift_date)] = d
            inp = inputs[d.employee_id]
            inp.adherence_days += 1
            inp.out_of_adherence_seconds += d.out_of_adherence_seconds
            inp.unpaid_excess_seconds += d.unpaid_excess_seconds

    # ---- segmentos de WFM (información y séptimo día)
    absent: dict[int, set[date]] = defaultdict(set)
    # Fase 22: tiempo justificado por AP con goce (permiso / justificación) para los días sin adherencia guardada.
    leave_paid: dict[tuple[int, date], int] = defaultdict(int)
    ap_with_segments: set[int] = set()
    hol_map = holidays_between({e.country_id for e in employees}, lo, hi)
    country = {e.pk: e.country_id for e in employees}
    for s in ScheduleSegment.objects.filter(employee_id__in=ids, shift_date__range=(lo, hi)).select_related("activity"):
        if not active(s.employee_id, s.shift_date) or (country[s.employee_id], s.shift_date) in hol_map:
            continue
        role, act = s.activity.system_role, s.activity
        inp = inputs[s.employee_id]
        if role == ActivityType.SystemRole.ABSENCE:
            absent[s.employee_id].add(s.shift_date)
        elif role == ActivityType.SystemRole.LATENESS:
            inp.lateness_seconds += _seconds(s)
        elif not role and not act.is_paid and act.category != ActivityType.Category.MEAL:
            inp.unpaid_leave_seconds += _seconds(s)
        if s.personnel_action_id:
            ap_with_segments.add(s.personnel_action_id)
            if not role and act.is_paid and not act.requires_acd_login:
                leave_paid[(s.employee_id, s.shift_date)] += _seconds(s)
    for x in AdherenceException.objects.filter(employee_id__in=ids, is_paid=True, start_at__gte=datetime.combine(lo, time()),
                                                    start_at__lt=datetime.combine(hi + timedelta(days=1), time())):
        d = x.start_at.date()
        if x.personnel_action_id not in ap_with_segments and active(x.employee_id, d):
            leave_paid[(x.employee_id, d)] += int((x.end_at - x.start_at).total_seconds())
    for emp_id, dates in absent.items():
        inputs[emp_id].absence_dates = sorted(dates)

    # ---- días de vacaciones (AP aprobadas): tiempo programado pagado
    vacation_days: dict[int, set[date]] = defaultdict(set)
    vac = PayConcept.objects.filter(is_active=True, calculation=PayConcept.Calculation.VACATION_PREMIUM).first()
    if vac:
        for a in PersonnelAction.objects.filter(employee_id__in=ids, status=PersonnelAction.Status.APPROVED,
                                                action_type__code=vac.action_type_code, effective_date__lte=hi):
            v = ActionValue.objects.filter(action=a, attribute__key=vac.action_attribute_key).first()
            n = int(v.value_decimal or 0) if v else 0
            for i in range(n):
                d = a.effective_date + timedelta(days=i)
                if lo <= d <= hi and active(a.employee_id, d):
                    vacation_days[a.employee_id].add(d)

    # ---- Holiday Segments (se regeneran: idempotente) y consolidación por día
    generate_segments(employees, lo, hi, audit=False)
    from apps.holidays.models import HolidaySegment

    hol_segments = {(s.employee_id, s.shift_date): s for s in
                    HolidaySegment.objects.filter(employee_id__in=ids, shift_date__range=(lo, hi)).select_related("holiday")}
    default_premium = params.holiday_premium_percent if params else Decimal(100)
    days = sorted({k for k in scheduled} | {k for k in worked} | {k for k in adherence} | {(e, d) for e, ds in vacation_days.items() for d in ds})
    for emp_id, d in days:
        inp = inputs[emp_id]
        sch_s = scheduled.get((emp_id, d), 0)
        w_s, night_s = worked.get((emp_id, d), (0, 0))
        inp.scheduled_seconds += sch_s
        inp.worked_seconds += w_s
        if d in vacation_days.get(emp_id, ()):
            inp.paid_seconds += sch_s
            inp.vacation_seconds += sch_s
            continue
        adh = adherence.get((emp_id, d))
        paid = min(adh.paid_valid_seconds, sch_s) if adh is not None else min(w_s + leave_paid.get((emp_id, d), 0), sch_s)
        inp.paid_seconds += paid
        inp.night_seconds += min(night_s, paid)
        seg = hol_segments.get((emp_id, d))
        if seg is not None and paid > 0:
            premium = seg.premium_percent if seg.premium_percent is not None else default_premium
            inp.holidays.append(engine.HolidayItem(d, seg.holiday.name, paid, Decimal(premium)))
    for e in employees:
        rule = rules.rule_for(e.country_id, period.period_end)
        inputs[e.pk].night_surcharge_percent = rule.surcharge_percent if rule else Decimal(0)

    # ---- regla de la cuenta (cliente del roster) para el séptimo día
    for emp_id, (rule_value, account) in account_rules(ids, period.period_end).items():
        inputs[emp_id].seventh_day_penalty = rule_value
        inputs[emp_id].account = account

    # ---- Fase 22: tipo de contrato del roster (retenciones de ley según el Optimum ES Payroll Hours)
    for emp_id, contract in contract_types(ids, min(hi, period.period_end)).items():
        inputs[emp_id].contract_type = contract

    # ---- AP aprobadas con efecto «Concepto de planilla» aún no pagadas en otra planilla vigente
    concepts = {c.code: c for c in PayConcept.objects.filter(is_active=True).exclude(calculation=PayConcept.Calculation.ENGINE)}
    by_type: dict[str, list[PayConcept]] = defaultdict(list)
    for c in concepts.values():
        by_type[c.action_type_code].append(c)
    if by_type:
        used = PayrollLine.objects.filter(personnel_action__isnull=False)
        if exclude_payroll_id:
            used = used.exclude(payroll_id=exclude_payroll_id)
        used_pairs = set(used.values_list("personnel_action_id", "code"))
        actions = list(PersonnelAction.objects.filter(
            employee_id__in=ids, status=PersonnelAction.Status.APPROVED, action_type__effect=Effect.PAYROLL,
            action_type__code__in=list(by_type), effective_date__lte=hi,
        ).select_related("action_type").order_by("effective_date", "id"))
        values = defaultdict(dict)
        for v in ActionValue.objects.filter(action__in=actions).select_related("attribute"):
            values[v.action_id][v.attribute.key] = v.value_decimal
        by_id = {e.pk: e for e in employees}
        for a in actions:
            if a.effective_date < by_id[a.employee_id].hire_date:
                continue
            for c in by_type[a.action_type.code]:
                qty = values[a.pk].get(c.action_attribute_key)
                if qty is None or qty <= 0 or (a.pk, c.code) in used_pairs:
                    continue
                inputs[a.employee_id].actions.append(engine.ActionItem(a.pk, a.folio, c.code, Decimal(qty), a.effective_date))
    return Gathered(inputs=inputs, windows=per_windows)


def cutoff_scheduled_seconds(book, employee_id: int, windows, night_lookup) -> int:
    """Horas netas programadas (s) de TODAS las fechas de los cortes, proyectando el horario a los días fuera de la
    relación laboral para que el rate por hora sea el del puesto y no dependa del ingreso / retiro."""
    from apps.scheduling import engine as sch_engine
    from apps.scheduling.models import ScheduleAssignment

    primaries = [a for a in book.assignments(employee_id) if a.mode == ScheduleAssignment.Mode.PRIMARY]
    if not primaries:
        return 0
    total = 0
    for a, b in windows:
        d = a - timedelta(days=1)
        while d <= b:
            current = book.assignments_on(employee_id, d)
            if current:
                defs = [book.definition(x) for x in current]
            else:
                nearest = primaries[0] if d < primaries[0].effective_start_date else primaries[-1]
                defs = [book.definition(nearest)]
            for definition in defs:
                for inst in sch_engine.shift_instances(definition, d, night_lookup=night_lookup):
                    for seg in inst.segments:
                        if a <= seg.occurrence_date <= b:
                            total += seg.net_minutes * 60
            d += timedelta(days=1)
    return total


def contract_types(employee_ids, on: date) -> dict[int, str]:
    """Tipo de contrato vigente en el roster (atributo contract_type); sin valor = PERMANENTE."""
    from apps.roster.models import RosterAssignment

    rows = RosterAssignment.objects.current().filter(employee_id__in=list(employee_ids), attribute__code="contract_type",
                                                     effective_start__lte=on).filter(
        Q(effective_end__isnull=True) | Q(effective_end__gte=on))
    return {r.employee_id: r.value for r in rows}


def account_rules(employee_ids, on: date) -> dict[int, tuple[bool, str]]:
    """Regla de séptimo día de la cuenta (cliente del roster vigente en la fecha) de cada colaborador que tenga una."""
    from apps.payroll.models import PayrollAccountRule
    from apps.roster.models import RosterAssignment

    rules = {r.client.code: r for r in PayrollAccountRule.objects.filter(is_active=True).select_related("client")}
    if not rules:
        return {}
    out = {}
    rows = (RosterAssignment.objects.current().filter(employee_id__in=list(employee_ids), attribute__code="client",
                                                      effective_start__lte=on)
            .filter(Q(effective_end__isnull=True) | Q(effective_end__gte=on)))
    for row in rows:
        rule = rules.get(row.value) or (rules.get(row.item.code) if row.item_id else None)
        if rule:
            out[row.employee_id] = (rule.seventh_day_penalty, rule.client.name)
    return out


# ================================================================ cálculo
def _run_for(period: PayPeriod) -> PayrollRun | None:
    return PayrollRun.objects.filter(pay_period=period).select_related("payroll").first()


@transaction.atomic
def calculate(period: PayPeriod, *, user=None, request=None, trigger: str = "MANUAL") -> PayrollRun:
    period = PayPeriod.objects.select_for_update().select_related("cycle", "cycle__country").get(pk=period.pk)
    cycle = period.cycle
    if not (cycle.is_default and cycle.is_active):
        raise PayrollError(f"El ciclo {cycle.code} no es el predeterminado activo de su país y frecuencia: sus colaboradores se pagan "
                           "en el ciclo predeterminado.", "cycle_not_default")
    setting = setting_for(cycle.country_id, period.period_end)
    if setting is None:
        raise PayrollError("No hay parámetros salariales vigentes para el país en la fecha del periodo: configúrelos en Planillas › "
                           "Parámetros.", "no_setting")
    run = _run_for(period)
    if run and run.payroll.payroll_status in CLOSED_STATUSES:
        raise PayrollError(f"La planilla {run.payroll.payroll_code} ya está cerrada: no se recalcula.", "closed")
    employees, skipped = eligible_employees(cycle, period)
    windows = windows_for(period)
    if run:
        payroll = run.payroll
        _clear(payroll)
    else:
        payroll = Payroll.objects.create(
            payroll_code=payroll_code(period), country_id=cycle.country_id, pay_frequency=cycle.pay_frequency,
            period_start=period.period_start, period_end=period.period_end, payment_date=period.payment_date,
            payroll_status="DRAFT", currency_code=cycle.country.currency_code,
        )
        run = PayrollRun(payroll=payroll, pay_period=period)
    params = params_of(setting)
    gathered = gather_inputs(employees, period, windows, exclude_payroll_id=payroll.pk, params=params)
    rules = legal_rules(cycle.country_id, period.period_end, cycle.pay_frequency)
    concepts = concept_map()
    concept_ids = dict(PayConcept.objects.values_list("code", "id"))
    warnings: list[dict] = []
    if skipped:
        warnings.append({"employee_code": None, "message": f"{len(skipped)} colaborador(es) INACTIVO(S) (suspensión): solo se les paga lo "
                         f"laborado fuera de la suspensión: {', '.join(skipped[:10])}" + ("…" if len(skipped) > 10 else "")})
    if not rules:
        warnings.append({"employee_code": None, "message": "No hay retenciones de ley vigentes para el país (ISSS, AFP, Renta)."})
    totals = defaultdict(Decimal)
    for e in employees:
        result = engine.calculate(gathered.inputs[e.pk], params, rules, concepts)
        detail = PayrollDetail.objects.create(
            payroll=payroll, employee=e, base_salary=e.base_salary, paid_days=min(result.paid_days, Decimal("999.99")),
            worked_minutes=result.paid_seconds // 60, overtime_amount=result.overtime_amount,
            other_earnings=result.other_earnings, gross_pay=result.gross_pay, taxable_base=result.taxable_base,
            total_deductions=result.total_deductions, net_pay=result.net_pay, employer_contributions=result.employer_contributions,
        )
        legal = [ln for ln in result.lines if ln.kind in ("LEGAL", "EMPLOYER") and ln.deduction_type_id]
        PayrollDeduction.objects.bulk_create([PayrollDeduction(
            payroll_detail=detail, deduction_type_id=ln.deduction_type_id, party="EMPLOYEE" if ln.kind == "LEGAL" else "EMPLOYER",
            calculation_base=ln.base or 0, applied_rate=ln.rate, amount=ln.amount) for ln in legal])
        PayrollLine.objects.bulk_create([PayrollLine(
            payroll=payroll, detail=detail, employee=e, kind=ln.kind, code=ln.code, label=ln.label[:200],
            concept_id=concept_ids.get(ln.concept) if ln.concept else None, deduction_type_id=ln.deduction_type_id,
            quantity=ln.quantity, unit=ln.unit, rate=ln.rate, base=ln.base, amount=ln.amount, source=ln.source[:10],
            personnel_action_id=ln.action_id, notes=ln.notes[:300], sort=ln.sort) for ln in result.lines])
        for w in result.warnings:
            warnings.append({"employee_code": e.employee_code, "message": w})
        totals["gross"] += result.gross_pay
        totals["deductions"] += result.total_deductions
        totals["net"] += result.net_pay
        totals["employer"] += result.employer_contributions
        totals["scheduled"] += result.scheduled_seconds
        totals["paid"] += result.paid_seconds
    now = timezone.now()
    payroll.payroll_status = "CALCULATED"
    payroll.total_gross, payroll.total_deductions = totals["gross"], totals["deductions"]
    payroll.total_net = totals["net"]
    payroll.total_employer_cost = totals["gross"] + totals["employer"]
    payroll.updated_at, payroll.updated_by = now, (getattr(user, "username", "") or "system")[:100]
    payroll.save(update_fields=["payroll_status", "total_gross", "total_deductions", "total_net", "total_employer_cost",
                                "updated_at", "updated_by"])
    run.setting = setting
    run.windows = [{"start": a.isoformat(), "end": b.isoformat()} for a, b in windows]
    run.employees = len(employees)
    run.warnings = warnings
    run.calculated_at, run.calculated_by = now, user if getattr(user, "pk", None) else None
    run.cancel_reason = ""
    run.iterations = (run.iterations or 0) + 1
    if setting.publish_preliminary:
        run.preliminary_published_at = now
    run.save()
    open_exc = PayrollException.objects.filter(payroll=payroll, status=PayrollException.Status.OPEN).count()
    PayrollIteration.objects.create(
        run=run, number=run.iterations, trigger=trigger, calculated_at=now, calculated_by=run.calculated_by,
        employees=len(employees), scheduled_seconds=int(totals["scheduled"]), paid_seconds=int(totals["paid"]),
        gross=totals["gross"], deductions=totals["deductions"], net=totals["net"], warnings=len(warnings), open_exceptions=open_exc)
    record("payroll_calculated", Category.PAYROLL,
           f"Planilla {payroll.payroll_code} calculada: {len(employees)} colaboradores, líquido {money(totals['net'])} "
           f"{payroll.currency_code}.", request=request, actor=user, target_type="Payroll", target_id=str(payroll.pk),
           details={"period": period.code, "cycle": cycle.code, "employees": len(employees), "warnings": len(warnings)})
    return run


def _clear(payroll: Payroll) -> None:
    """Borra el resultado anterior (líneas, retenciones y detalle) de una planilla NO cerrada."""
    PayrollLine.objects.filter(payroll=payroll).delete()
    PayrollDeduction.objects.filter(payroll_detail__payroll=payroll).delete()
    PayrollDetail.objects.filter(payroll=payroll).delete()


# ================================================================ cierre, pago y anulación
@transaction.atomic
def approve(run: PayrollRun, *, user=None, request=None) -> dict:
    run = PayrollRun.objects.select_for_update().select_related("payroll", "pay_period", "pay_period__cycle", "setting").get(pk=run.pk)
    payroll, period = run.payroll, run.pay_period
    if payroll.payroll_status != "CALCULATED":
        raise PayrollError(f"Solo se cierra una planilla calculada (estado actual: {STATUS_LABELS[payroll.payroll_status]}).", "not_calculated")
    setting = run.setting or setting_for(period.cycle.country_id, period.period_end)
    cutoffs = list(period.cutoffs.order_by("cutoff_start"))
    if setting and setting.require_closed_cutoffs:
        open_cutoffs = [c.code for c in cutoffs if c.status != AttendanceCutoff.Status.CLOSED]
        if open_cutoffs:
            raise PayrollError(f"Cierre los cortes de asistencia del periodo antes de cerrar la planilla: {', '.join(open_cutoffs)}.",
                               "cutoffs_open")
    closed_at = max((c.closed_at for c in cutoffs if c.closed_at), default=None)
    if closed_at and run.calculated_at and run.calculated_at < closed_at:
        raise PayrollError("Un corte de asistencia se cerró después del último cálculo: recalcule la planilla antes de cerrarla.", "stale")
    if not payroll.details.exists():
        raise PayrollError("La planilla no tiene colaboradores: no hay boletas que generar.", "empty")
    open_exc = PayrollException.objects.filter(payroll=payroll, status=PayrollException.Status.OPEN).count()
    if open_exc:
        raise PayrollError(f"Hay {open_exc} excepción(es) reportada(s) por los agentes sin resolver: resuélvalas antes del cierre "
                           "(freeze).", "open_exceptions")
    now = timezone.now()
    payroll.payroll_status = "APPROVED"
    payroll.approved_at = now
    payroll.approved_by = (getattr(user, "username", "") or "system")[:100]
    payroll.updated_at, payroll.updated_by = now, payroll.approved_by
    payroll.save(update_fields=["payroll_status", "approved_at", "approved_by", "updated_at", "updated_by"])
    run.approved_by = user if getattr(user, "pk", None) else None
    run.save(update_fields=["approved_by"])
    out = generate_payslips(run, user=user)
    record("payroll_approved", Category.PAYROLL,
           f"Planilla {payroll.payroll_code} cerrada: {out['payslips']} boletas generadas en {out['batches']} lotes.",
           request=request, actor=user, target_type="Payroll", target_id=str(payroll.pk), details=out)
    return out


def payslip_content(detail: PayrollDetail, run: PayrollRun, folio: str, lines: list[PayrollLine]) -> dict:
    e, payroll, period = detail.employee, run.payroll, run.pay_period

    def ln(x: PayrollLine) -> dict:
        return {"kind": x.kind, "code": x.code, "label": x.label, "quantity": str(x.quantity) if x.quantity is not None else None,
                "unit": x.unit, "rate": str(x.rate) if x.rate is not None else None, "base": str(x.base) if x.base is not None else None,
                "amount": money(x.amount), "source": x.source, "folio_ap": x.personnel_action.folio if x.personnel_action_id else None,
                "notes": x.notes}

    return {
        "folio": folio, "payroll_code": payroll.payroll_code, "currency": payroll.currency_code,
        "employee": {"code": e.employee_code, "name": e.full_name, "national_id": f"{e.national_id_type} {e.national_id_number}",
                     "hire_date": e.hire_date.isoformat(), "cost_center": e.cost_center.code if e.cost_center_id else None,
                     "cost_center_name": e.cost_center.name if e.cost_center_id else None},
        "period": {"code": period.code, "cycle": period.cycle.code, "frequency": payroll.pay_frequency,
                   "frequency_label": FREQ_LABELS.get(payroll.pay_frequency, payroll.pay_frequency),
                   "start": period.period_start.isoformat(), "end": period.period_end.isoformat(),
                   "payment_date": period.payment_date.isoformat(), "attendance_windows": run.windows},
        "base_salary": money(detail.base_salary), "paid_days": str(detail.paid_days), "worked_minutes": detail.worked_minutes,
        "lines": [ln(x) for x in lines],
        "totals": {"gross": money(detail.gross_pay), "taxable_base": money(detail.taxable_base),
                   "deductions": money(detail.total_deductions), "net": money(detail.net_pay),
                   "employer": money(detail.employer_contributions)},
    }


def preview_payslip(run: PayrollRun, code: str) -> tuple[dict, str | None, bool]:
    """Fase 22: contenido de la boleta de un colaborador para el PDF: la boleta CONGELADA si ya se generó; si no, la
    vista previa del cálculo en curso (preliminar). Devuelve (contenido, sello, es_preliminar)."""
    d = PayrollDetail.objects.select_related("employee", "employee__cost_center").filter(
        payroll=run.payroll, employee__employee_code=code).first()
    if d is None:
        raise PayrollError("El colaborador no está en esta planilla.", "not_found", 404)
    s = Payslip.objects.filter(detail=d).first()
    if s is not None:
        return s.content, s.content_hash, False
    lines = list(PayrollLine.objects.filter(detail=d).select_related("personnel_action").order_by("sort", "id"))
    return payslip_content(d, run, None, lines), None, True


def content_hash(content: dict) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def generate_payslips(run: PayrollRun, *, user=None) -> dict:
    """Genera (idempotente) una boleta por colaborador y un lote por departamento de la planilla cerrada."""
    payroll = run.payroll
    details = list(PayrollDetail.objects.filter(payroll=payroll).select_related("employee", "employee__cost_center")
                   .order_by("employee__cost_center__code", "employee__employee_code"))
    existing = set(Payslip.objects.filter(payroll=payroll).values_list("detail_id", flat=True))
    lines = defaultdict(list)
    for x in PayrollLine.objects.filter(payroll=payroll).select_related("personnel_action").order_by("sort", "id"):
        lines[x.detail_id].append(x)
    batches: dict[int | None, PayslipBatch] = {b.cost_center_id: b for b in PayslipBatch.objects.filter(payroll=payroll)}
    seq = Payslip.objects.filter(payroll=payroll).count()
    now = timezone.now()
    created = 0
    for d in details:
        if d.payroll_detail_id in existing:
            continue
        cc = d.employee.cost_center if d.employee.cost_center_id else None
        batch = batches.get(d.employee.cost_center_id)
        if batch is None:
            batch = PayslipBatch.objects.create(payroll=payroll, cost_center=cc,
                                                code=f"LOTE-{payroll.payroll_code}-{cc.code if cc else 'SIN-CC'}"[:60])
            batches[d.employee.cost_center_id] = batch
        seq += 1
        folio = f"BOL-{payroll.payroll_code}-{seq:05d}"[:60]
        content = payslip_content(d, run, folio, lines[d.payroll_detail_id])
        Payslip.objects.create(
            folio=folio, payroll=payroll, detail=d, batch=batch, employee=d.employee, cost_center=cc,
            period_start=payroll.period_start, period_end=payroll.period_end, payment_date=payroll.payment_date,
            pay_frequency=payroll.pay_frequency, gross_pay=d.gross_pay, total_deductions=d.total_deductions, net_pay=d.net_pay,
            content=content, content_hash=content_hash(content), generated_at=now,
            generated_by=user if getattr(user, "pk", None) else None,
        )
        created += 1
    return {"payslips": created, "batches": len(batches), "payroll": payroll.payroll_code}


@transaction.atomic
def mark_paid(run: PayrollRun, *, user=None, request=None) -> PayrollRun:
    payroll = run.payroll
    if payroll.payroll_status != "APPROVED":
        raise PayrollError("Solo se marca como pagada una planilla cerrada.", "not_approved")
    now = timezone.now()
    payroll.payroll_status = "PAID"
    payroll.updated_at, payroll.updated_by = now, (getattr(user, "username", "") or "system")[:100]
    payroll.save(update_fields=["payroll_status", "updated_at", "updated_by"])
    run.paid_at, run.paid_by = now, user if getattr(user, "pk", None) else None
    run.save(update_fields=["paid_at", "paid_by"])
    record("payroll_paid", Category.PAYROLL, f"Planilla {payroll.payroll_code} marcada como pagada.", request=request, actor=user,
           target_type="Payroll", target_id=str(payroll.pk))
    return run


@transaction.atomic
def cancel(run: PayrollRun, *, reason: str, user=None, request=None) -> PayrollRun:
    payroll = run.payroll
    if payroll.payroll_status in CLOSED_STATUSES:
        raise PayrollError("Una planilla cerrada no se anula: sus boletas ya se generaron.", "closed")
    reason = (reason or "").strip()
    if not reason:
        raise PayrollError("Indique el motivo de la anulación.", "reason_required", 400)
    _clear(payroll)
    now = timezone.now()
    payroll.payroll_status = "CANCELLED"
    payroll.total_gross = payroll.total_deductions = payroll.total_net = payroll.total_employer_cost = Decimal(0)
    payroll.updated_at, payroll.updated_by = now, (getattr(user, "username", "") or "system")[:100]
    payroll.save(update_fields=["payroll_status", "total_gross", "total_deductions", "total_net", "total_employer_cost",
                                "updated_at", "updated_by"])
    run.cancel_reason, run.employees, run.warnings = reason[:500], 0, []
    run.save(update_fields=["cancel_reason", "employees", "warnings"])
    record("payroll_cancelled", Category.PAYROLL, f"Planilla {payroll.payroll_code} anulada: {reason[:200]}", request=request,
           actor=user, target_type="Payroll", target_id=str(payroll.pk))
    return run


# ================================================================ representación
def run_dict(run: PayrollRun, *, with_counts: bool = True) -> dict:
    p, period = run.payroll, run.pay_period
    out = {
        "id": run.pk, "payroll_id": p.pk, "code": p.payroll_code, "status": p.payroll_status,
        "status_label": STATUS_LABELS.get(p.payroll_status, p.payroll_status),
        "country": period.cycle.country_id, "cycle": period.cycle.code, "period_id": period.pk, "period_code": period.code,
        "pay_frequency": p.pay_frequency, "pay_frequency_label": FREQ_LABELS.get(p.pay_frequency, p.pay_frequency),
        "period_start": p.period_start, "period_end": p.period_end, "payment_date": p.payment_date, "currency": p.currency_code,
        "total_gross": p.total_gross, "total_deductions": p.total_deductions, "total_net": p.total_net,
        "total_employer_cost": p.total_employer_cost, "employees": run.employees, "windows": run.windows,
        "warnings": run.warnings, "calculated_at": run.calculated_at,
        "calculated_by": run.calculated_by.username if run.calculated_by_id and run.calculated_by else None,
        "approved_at": p.approved_at, "approved_by": p.approved_by, "paid_at": run.paid_at, "cancel_reason": run.cancel_reason,
        "setting": run.setting.name if run.setting_id else None,
        "iterations": run.iterations, "preliminary_published_at": run.preliminary_published_at,
    }
    last = run.iteration_log.order_by("-number").first() if run.pk else None
    out["hours"] = {"scheduled_seconds": last.scheduled_seconds, "paid_seconds": last.paid_seconds} if last else None
    out["open_exceptions"] = PayrollException.objects.filter(payroll_id=p.pk, status=PayrollException.Status.OPEN).count()
    if with_counts:
        out["payslips"] = inventory_counts(Payslip.objects.filter(payroll_id=p.pk))
    return out


def detail_rows(run: PayrollRun, *, search: str = "", cost_center: str = "") -> list[dict]:
    qs = PayrollDetail.objects.filter(payroll=run.payroll).select_related("employee", "employee__cost_center")
    if search:
        qs = qs.filter(Q(employee__employee_code__icontains=search) | Q(employee__first_name__icontains=search)
                       | Q(employee__last_name__icontains=search))
    if cost_center:
        qs = qs.filter(employee__cost_center__code=cost_center)
    details = list(qs.order_by("employee__employee_code"))
    flags = defaultdict(dict)
    codes = ["HORAS_PROGRAMADAS", "HORAS_PAGADAS", "HORAS_NO_PAGADAS", "NOCTURNIDAD", "FERIADO", "SEPTIMO_DIA"]
    for row in (PayrollLine.objects.filter(detail__in=details, code__in=codes).values("detail_id", "code")
                .annotate(q=Sum("quantity"), a=Sum("amount"))):
        flags[row["detail_id"]][row["code"]] = row
    rates = dict(PayrollLine.objects.filter(detail__in=details, code="SALARIO").values_list("detail_id", "rate"))
    slips = {s.detail_id: s for s in Payslip.objects.filter(detail__in=details)}
    out = []
    for d in details:
        e, s = d.employee, slips.get(d.payroll_detail_id)
        out.append({
            "detail_id": d.payroll_detail_id, "employee_code": e.employee_code, "full_name": e.full_name,
            "cost_center": e.cost_center.code if e.cost_center_id else None, "base_salary": d.base_salary, "paid_days": d.paid_days,
            "worked_minutes": d.worked_minutes, "overtime_amount": d.overtime_amount, "other_earnings": d.other_earnings,
            "gross_pay": d.gross_pay, "taxable_base": d.taxable_base, "total_deductions": d.total_deductions, "net_pay": d.net_pay,
            "employer_contributions": d.employer_contributions,
            "hourly_rate": rates.get(d.payroll_detail_id),
            **{f"{k.lower()}_hours": (flags[d.payroll_detail_id].get(k) or {}).get("q") for k in codes[:5]},
            "holiday_amount": (flags[d.payroll_detail_id].get("FERIADO") or {}).get("a"),
            "seventh_day_amount": (flags[d.payroll_detail_id].get("SEPTIMO_DIA") or {}).get("a"),
            "payslip": {"id": s.pk, "folio": s.folio, **slip_state(s)} if s else None,
        })
    return out


def line_dict(x: PayrollLine) -> dict:
    return {"kind": x.kind, "kind_label": x.get_kind_display(), "code": x.code, "label": x.label, "quantity": x.quantity, "unit": x.unit,
            "rate": x.rate, "base": x.base, "amount": x.amount, "source": x.source, "notes": x.notes,
            "folio_ap": x.personnel_action.folio if x.personnel_action_id else None}


def employee_breakdown(run: PayrollRun, code: str) -> dict:
    d = PayrollDetail.objects.select_related("employee", "employee__cost_center").filter(
        payroll=run.payroll, employee__employee_code=code).first()
    if d is None:
        raise PayrollError("El colaborador no está en esta planilla.", "not_found", 404)
    lines = PayrollLine.objects.filter(detail=d).select_related("personnel_action").order_by("sort", "id")
    s = Payslip.objects.filter(detail=d).first()
    e = d.employee
    return {
        "run": run_dict(run, with_counts=False),
        "employee": {"code": e.employee_code, "name": e.full_name, "national_id": f"{e.national_id_type} {e.national_id_number}",
                     "cost_center": e.cost_center.code if e.cost_center_id else None,
                     "cost_center_name": e.cost_center.name if e.cost_center_id else None,
                     "hire_date": e.hire_date, "termination_date": e.termination_date},
        "detail": {"base_salary": d.base_salary, "paid_days": d.paid_days, "worked_minutes": d.worked_minutes,
                   "gross_pay": d.gross_pay, "taxable_base": d.taxable_base, "total_deductions": d.total_deductions,
                   "net_pay": d.net_pay, "employer_contributions": d.employer_contributions},
        "lines": [line_dict(x) for x in lines],
        "payslip": {"id": s.pk, "folio": s.folio, **slip_state(s)} if s else None,
    }


def period_rows(year: int, *, country_id: int | None = None) -> list[dict]:
    """Periodos de pago de los ciclos predeterminados del año con el estado de su planilla."""
    qs = PayPeriod.objects.filter(cycle__is_default=True, cycle__is_active=True, period_start__year=year).select_related("cycle")
    if country_id:
        qs = qs.filter(cycle__country_id=country_id)
    runs = {r.pay_period_id: r for r in PayrollRun.objects.filter(pay_period__in=qs).select_related("payroll", "pay_period", "pay_period__cycle", "calculated_by", "setting")}
    cutoffs = defaultdict(list)
    for c in AttendanceCutoff.objects.filter(pay_period__in=qs).order_by("cutoff_start"):
        cutoffs[c.pay_period_id].append(c)
    out = []
    for p in qs.order_by("cycle__code", "period_start"):
        cs = cutoffs[p.pk]
        out.append({
            "id": p.pk, "code": p.code, "cycle": p.cycle.code, "cycle_name": p.cycle.name, "pay_frequency": p.cycle.pay_frequency,
            "pay_frequency_label": p.cycle.get_pay_frequency_display(), "period_start": p.period_start, "period_end": p.period_end,
            "payment_date": p.payment_date, "cutoffs": [{"code": c.code, "start": c.cutoff_start, "end": c.cutoff_end,
                                                         "status": c.status} for c in cs],
            "cutoffs_closed": bool(cs) and all(c.status == AttendanceCutoff.Status.CLOSED for c in cs),
            "run": run_dict(runs[p.pk], with_counts=False) if p.pk in runs else None,
        })
    return out


# ================================================================ inventario de boletas físicas (RRHH)
SIGNATURE_FILTERS = {"SIGNED": Q(signed_on__isnull=False), "PENDING": Q(signed_on__isnull=True)}
PRINT_FILTERS = {"PRINTED": Q(printed_at__isnull=False), "MISSING": Q(printed_at__isnull=True)}
ARCHIVE_FILTERS = {"ARCHIVED": Q(archived_at__isnull=False), "NOT_ARCHIVED": Q(archived_at__isnull=True)}


def slip_state(s: Payslip) -> dict:
    return {"printed": s.printed_at is not None, "signed": s.signed_on is not None, "archived": s.archived_at is not None}


def filter_payslips(params) -> "Q":
    q = Q()
    get = lambda k: str(params.get(k) or "").strip()  # noqa: E731
    if get("payroll"):
        q &= Q(payroll_id=get("payroll")) if get("payroll").isdigit() else Q(payroll__payroll_code=get("payroll"))
    if get("batch"):
        q &= Q(batch_id=get("batch")) if get("batch").isdigit() else Q(batch__code=get("batch"))
    if get("year").isdigit():
        q &= Q(period_end__year=int(get("year")))
    if get("month").isdigit():
        q &= Q(period_end__month=int(get("month")))
    if get("frequency"):
        q &= Q(pay_frequency=get("frequency"))
    if get("cost_center"):
        q &= Q(cost_center__isnull=True) if get("cost_center") == "NONE" else Q(cost_center__code=get("cost_center"))
    for key, table in (("signature", SIGNATURE_FILTERS), ("printed", PRINT_FILTERS), ("archived", ARCHIVE_FILTERS)):
        if get(key) in table:
            q &= table[get(key)]
    if get("search"):
        s = get("search")
        q &= (Q(folio__icontains=s) | Q(employee__employee_code__icontains=s) | Q(employee__first_name__icontains=s)
              | Q(employee__last_name__icontains=s))
    return q


def inventory_counts(qs) -> dict:
    agg = qs.aggregate(total=Count("id"), printed=Count("id", filter=Q(printed_at__isnull=False)),
                       signed=Count("id", filter=Q(signed_on__isnull=False)), archived=Count("id", filter=Q(archived_at__isnull=False)))
    total = agg["total"] or 0
    return {"total": total, "printed": agg["printed"], "missing_print": total - agg["printed"], "signed": agg["signed"],
            "pending_signature": total - agg["signed"], "archived": agg["archived"], "not_archived": total - agg["archived"]}


def payslip_row(s: Payslip) -> dict:
    e = s.employee
    return {
        "id": s.pk, "folio": s.folio, "payroll_code": s.payroll.payroll_code, "batch": s.batch.code, "batch_id": s.batch_id,
        "employee_code": e.employee_code, "full_name": e.full_name,
        "cost_center": s.cost_center.code if s.cost_center_id else None, "cost_center_name": s.cost_center.name if s.cost_center_id else None,
        "period_start": s.period_start, "period_end": s.period_end, "payment_date": s.payment_date,
        "pay_frequency": s.pay_frequency, "pay_frequency_label": FREQ_LABELS.get(s.pay_frequency, s.pay_frequency),
        "net_pay": s.net_pay, "currency": s.payroll.currency_code,
        "printed_at": s.printed_at, "printed_by": s.printed_by.username if s.printed_by_id and s.printed_by else None,
        "print_count": s.print_count, "signed_on": s.signed_on,
        "signed_recorded_by": s.signed_recorded_by.username if s.signed_recorded_by_id and s.signed_recorded_by else None,
        "archived_at": s.archived_at, "archived_by": s.archived_by.username if s.archived_by_id and s.archived_by else None,
        "archive_location": s.archive_location, "notes": s.notes, **slip_state(s),
    }


def payslip_queryset():
    return Payslip.objects.select_related("employee", "cost_center", "batch", "payroll", "printed_by", "signed_recorded_by", "archived_by")


def batch_rows(params) -> list[dict]:
    q = Q()
    if str(params.get("year") or "").isdigit():
        q &= Q(payroll__period_end__year=int(params["year"]))
    if str(params.get("month") or "").isdigit():
        q &= Q(payroll__period_end__month=int(params["month"]))
    if params.get("cost_center"):
        q &= Q(cost_center__isnull=True) if params["cost_center"] == "NONE" else Q(cost_center__code=params["cost_center"])
    if params.get("payroll"):
        q &= Q(payroll_id=params["payroll"]) if str(params["payroll"]).isdigit() else Q(payroll__payroll_code=params["payroll"])
    batches = list(PayslipBatch.objects.filter(q).select_related("payroll", "cost_center").order_by("-payroll__period_start", "code"))
    counts = {}
    for b in batches:
        counts[b.pk] = inventory_counts(Payslip.objects.filter(batch=b))
    return [{
        "id": b.pk, "code": b.code, "payroll_id": b.payroll_id, "payroll_code": b.payroll.payroll_code,
        "period_start": b.payroll.period_start, "period_end": b.payroll.period_end, "payment_date": b.payroll.payment_date,
        "pay_frequency_label": FREQ_LABELS.get(b.payroll.pay_frequency, b.payroll.pay_frequency),
        "cost_center": b.cost_center.code if b.cost_center_id else None, "cost_center_name": b.cost_center.name if b.cost_center_id else "Sin centro de costos",
        "archive_location": b.archive_location, "notes": b.notes, "counts": counts[b.pk],
        "status": ("ARCHIVED" if counts[b.pk]["archived"] == counts[b.pk]["total"] else
                   "SIGNED" if counts[b.pk]["signed"] == counts[b.pk]["total"] else
                   "PRINTED" if counts[b.pk]["printed"] == counts[b.pk]["total"] else "PENDING") if counts[b.pk]["total"] else "EMPTY",
    } for b in batches]


INVENTORY_ACTIONS = {
    "PRINT": "impresas", "SIGN": "firmadas por el colaborador", "ARCHIVE": "archivadas",
    "UNPRINT": "devueltas a «faltante por imprimir»", "UNSIGN": "devueltas a «pendiente de firma»", "UNARCHIVE": "sacadas del archivo",
}


@transaction.atomic
def inventory_action(ids: list[int], action: str, *, user, data: dict, request=None) -> dict:
    action = str(action or "").upper()
    if action not in INVENTORY_ACTIONS:
        raise PayrollError("Acción de inventario no válida.", "invalid_action", 400)
    if not ids:
        raise PayrollError("Seleccione al menos una boleta.", "empty_selection", 400)
    if len(ids) > 1000:
        raise PayrollError("Máximo 1000 boletas por operación.", "too_many", 400)
    reason = str(data.get("reason") or "").strip()
    if action.startswith("UN") and not reason:
        raise PayrollError("Indique el motivo para revertir el estado (queda en la auditoría).", "reason_required", 400)
    slips = list(Payslip.objects.select_for_update().filter(pk__in=ids).select_related("batch"))
    if len(slips) != len(set(ids)):
        raise PayrollError("Alguna boleta no existe.", "not_found", 404)
    now, today = timezone.now(), timezone.localdate()
    signed_on = None
    if action == "SIGN":
        raw = str(data.get("signed_on") or "").strip()
        try:
            signed_on = date.fromisoformat(raw) if raw else today
        except ValueError:
            raise PayrollError("Fecha de firma inválida (AAAA-MM-DD).", "invalid_date", 400) from None
        if signed_on > today:
            raise PayrollError("La fecha de firma no puede ser futura.", "invalid_date", 400)
    location = str(data.get("location") or "").strip()[:150]
    changed, skipped = [], []
    for s in slips:
        if action == "PRINT":
            s.printed_at = s.printed_at or now
            s.printed_by = user
            s.print_count += 1
        elif action == "SIGN":
            if s.printed_at is None:
                skipped.append(f"{s.folio}: aún no está impresa")
                continue
            if signed_on < s.generated_at.date():
                skipped.append(f"{s.folio}: la firma no puede ser anterior a la emisión ({fmt(s.generated_at.date())})")
                continue
            s.signed_on, s.signed_recorded_at, s.signed_recorded_by = signed_on, now, user
        elif action == "ARCHIVE":
            if s.printed_at is None:
                skipped.append(f"{s.folio}: aún no está impresa")
                continue
            s.archived_at, s.archived_by = now, user
            s.archive_location = location or s.archive_location or s.batch.archive_location
        elif action == "UNPRINT":
            if s.signed_on or s.archived_at:
                skipped.append(f"{s.folio}: está firmada o archivada")
                continue
            s.printed_at, s.printed_by, s.print_count = None, None, 0
        elif action == "UNSIGN":
            if s.archived_at:
                skipped.append(f"{s.folio}: está archivada (sáquela del archivo primero)")
                continue
            s.signed_on, s.signed_recorded_at, s.signed_recorded_by = None, None, None
        elif action == "UNARCHIVE":
            s.archived_at, s.archived_by = None, None
        s.save()
        changed.append(s.folio)
    if changed:
        record(f"payslip_{action.lower()}", Category.PAYROLL,
               f"{len(changed)} boleta(s) {INVENTORY_ACTIONS[action]}" + (f": {reason[:200]}" if reason else "."),
               request=request, actor=user, target_type="Payslip", target_id=changed[0] if len(changed) == 1 else "",
               details={"folios": changed[:200], "reason": reason, "signed_on": signed_on.isoformat() if signed_on else None,
                        "location": location})
    return {"changed": len(changed), "skipped": skipped,
            "feedback": f"{len(changed)} boleta(s) {INVENTORY_ACTIONS[action]}." + (f" {len(skipped)} omitida(s)." if skipped else "")}


# ================================================================ parámetros (pantalla de configuración)
def setting_dict(s: PayrollSetting) -> dict:
    used = s.runs.filter(payroll__payroll_status__in=CLOSED_STATUSES).exists()
    return {
        "id": s.pk, "country": s.country_id, "name": s.name, "effective_start_date": s.effective_start_date,
        "effective_end_date": s.effective_end_date, "days_per_month": s.days_per_month, "hours_per_day": s.hours_per_day,
        "overtime_surcharge_percent": s.overtime_surcharge_percent, "vacation_premium_percent": s.vacation_premium_percent,
        **{f: getattr(s, f) for f in PHASE21_FIELDS},
        "require_closed_cutoffs": s.require_closed_cutoffs, "legal_reference": s.legal_reference, "is_active": s.is_active,
        "used_by_closed_payroll": used,
    }


def deduction_type_dict(t: DeductionType) -> dict:
    return {
        "id": t.deduction_type_id, "country": t.country_id, "code": t.code, "name": t.name, "category": t.category, "party": t.party,
        "method": t.calculation_method, "rate": t.rate, "fixed_amount": t.fixed_amount, "base_cap": t.base_cap,
        "reduces_taxable_base": t.reduces_taxable_base, "calculation_order": t.calculation_order,
        "effective_start_date": t.effective_start_date, "effective_end_date": t.effective_end_date,
        "legal_reference": t.legal_reference, "is_active": t.is_active,
        "brackets": [{"id": b.deduction_bracket_id, "pay_frequency": b.pay_frequency, "lower_bound": b.lower_bound,
                      "upper_bound": b.upper_bound, "rate": b.rate, "fixed_fee": b.fixed_fee, "excess_over": b.excess_over}
                     for b in t.brackets.order_by("pay_frequency", "lower_bound")],
    }


def concept_dict(c: PayConcept) -> dict:
    return {"id": c.pk, "code": c.code, "name": c.name, "kind": c.kind, "kind_label": c.get_kind_display(), "source": c.source,
            "source_label": c.get_source_display(), "calculation": c.calculation, "calculation_label": c.get_calculation_display(),
            "action_type_code": c.action_type_code, "action_attribute_key": c.action_attribute_key,
            "affects_social_security": c.affects_social_security, "affects_income_tax": c.affects_income_tax,
            "display_order": c.display_order, "is_active": c.is_active, "description": c.description}


PHASE21_FIELDS = ("seventh_day_penalty", "holiday_premium_percent", "preliminary_lead_days", "publish_preliminary",
                  "minimum_wage_monthly", "indemnity_days_per_year", "indemnity_cap_multiplier", "indemnity_min_days",
                  "resignation_days_per_year", "resignation_cap_multiplier", "resignation_min_years", "vacation_days_per_year",
                  "aguinaldo_tiers", "aguinaldo_exempt_multiplier")
SETTING_FIELDS = ("name", "days_per_month", "hours_per_day", "overtime_surcharge_percent", "vacation_premium_percent",
                  *PHASE21_FIELDS, "require_closed_cutoffs", "legal_reference", "is_active", "effective_end_date")


def _apply_fields(obj, data: dict, fields) -> dict:
    from django.core.exceptions import ValidationError

    for f in fields:
        if f in data:
            value = data[f]
            if f == "effective_end_date":
                value = date.fromisoformat(value) if value else None
            setattr(obj, f, value)
    try:
        obj.full_clean(exclude=["country"])
    except ValidationError as exc:
        return exc.message_dict
    return {}


@transaction.atomic
def save_setting(data: dict, *, instance: PayrollSetting | None = None, user=None, request=None) -> PayrollSetting:
    """Edita una vigencia que ninguna planilla cerrada usó, o crea una nueva (cierra la anterior el día previo)."""
    if instance is not None:
        if instance.runs.filter(payroll__payroll_status__in=CLOSED_STATUSES).exists():
            raise PayrollError("Esta vigencia ya respaldó una planilla cerrada: cree una nueva vigencia en lugar de editarla.", "in_use")
        errors = _apply_fields(instance, data, SETTING_FIELDS)
        if errors:
            raise PayrollError(_first(errors), "invalid", 400)
        instance.save()
        s = instance
        action = "payroll_setting_updated"
    else:
        try:
            start = date.fromisoformat(str(data.get("effective_start_date") or ""))
            country_id = int(data.get("country"))
        except (TypeError, ValueError):
            raise PayrollError("Indique el país y la fecha «vigente desde».", "invalid", 400) from None
        base = setting_for(country_id, start)
        s = PayrollSetting(country_id=country_id, effective_start_date=start)
        if base:
            for f in SETTING_FIELDS:
                setattr(s, f, getattr(base, f))
            s.effective_end_date = None
        errors = _apply_fields(s, data, SETTING_FIELDS)
        if errors:
            raise PayrollError(_first(errors), "invalid", 400)
        if PayrollSetting.objects.filter(country_id=country_id, effective_start_date=start).exists():
            raise PayrollError("Ya hay una vigencia del país que inicia esa fecha.", "duplicate")
        prev = PayrollSetting.objects.filter(country_id=country_id, effective_start_date__lt=start, is_active=True).filter(
            Q(effective_end_date__isnull=True) | Q(effective_end_date__gte=start)).order_by("-effective_start_date").first()
        if prev:
            prev.effective_end_date = start - timedelta(days=1)
            prev.save(update_fields=["effective_end_date", "updated_at"])
        s.save()
        action = "payroll_setting_created"
    record(action, Category.PAYROLL, f"Parámetros salariales «{s.name}» vigentes desde el {fmt(s.effective_start_date)}.",
           request=request, actor=user, target_type="PayrollSetting", target_id=str(s.pk), details=setting_dict(s) | {
               "hours_per_day": str(s.hours_per_day), "overtime_surcharge_percent": str(s.overtime_surcharge_percent),
               "vacation_premium_percent": str(s.vacation_premium_percent), "effective_start_date": str(s.effective_start_date),
               **{f: str(getattr(s, f)) for f in PHASE21_FIELDS if f != "aguinaldo_tiers"},
               "effective_end_date": str(s.effective_end_date) if s.effective_end_date else None})
    return s


def _first(errors: dict) -> str:
    for field_name, messages in errors.items():
        return f"{field_name}: {messages[0]}" if field_name != "__all__" else messages[0]
    return "Datos inválidos."


def _dec(value, field_name: str, *, required: bool = False, lo: Decimal | None = None, hi: Decimal | None = None):
    if value in (None, ""):
        if required:
            raise PayrollError(f"Indique {field_name}.", "invalid", 400)
        return None
    try:
        out = Decimal(str(value))
    except Exception:  # noqa: BLE001
        raise PayrollError(f"{field_name}: número inválido.", "invalid", 400) from None
    if (lo is not None and out < lo) or (hi is not None and out > hi):
        raise PayrollError(f"{field_name}: fuera de rango.", "invalid", 400)
    return out


@transaction.atomic
def new_deduction_version(source: DeductionType, data: dict, *, user=None, request=None) -> DeductionType:
    """Nueva vigencia de una retención de ley (cambio de tasa, tope o tabla). La anterior se cierra el día previo; las
    planillas ya calculadas conservan la versión que usaron (fin.PayrollDeduction apunta a ella)."""
    try:
        start = date.fromisoformat(str(data.get("effective_start_date") or ""))
    except ValueError:
        raise PayrollError("Indique la fecha «vigente desde» de la nueva versión.", "invalid", 400) from None
    if start <= source.effective_start_date:
        raise PayrollError(f"La nueva versión debe iniciar después del {fmt(source.effective_start_date)}.", "invalid", 400)
    if DeductionType.objects.filter(country_id=source.country_id, code=source.code, effective_start_date=start).exists():
        raise PayrollError("Ya hay una versión de esa retención que inicia esa fecha.", "duplicate")
    rate = _dec(data.get("rate", source.rate), "la tasa", lo=Decimal(0), hi=Decimal(1))
    fixed = _dec(data.get("fixed_amount", source.fixed_amount), "el monto fijo", lo=Decimal(0))
    cap = _dec(data.get("base_cap", source.base_cap), "el tope", lo=Decimal("0.01"))
    if source.calculation_method == "PERCENTAGE" and rate is None:
        raise PayrollError("Una retención porcentual necesita la tasa.", "invalid", 400)
    if source.calculation_method == "FIXED" and fixed is None:
        raise PayrollError("Una retención fija necesita el monto.", "invalid", 400)
    brackets = data.get("brackets")
    if source.calculation_method == "BRACKET":
        if not isinstance(brackets, list) or not brackets:
            brackets = [{"pay_frequency": b.pay_frequency, "lower_bound": b.lower_bound, "upper_bound": b.upper_bound, "rate": b.rate,
                         "fixed_fee": b.fixed_fee, "excess_over": b.excess_over} for b in source.brackets.all()]
    new = DeductionType.objects.create(
        country_id=source.country_id, code=source.code, name=str(data.get("name") or source.name)[:150], category=source.category,
        party=source.party, calculation_method=source.calculation_method, rate=rate, fixed_amount=fixed, base_cap=cap,
        reduces_taxable_base=bool(data.get("reduces_taxable_base", source.reduces_taxable_base)),
        calculation_order=int(data.get("calculation_order") or source.calculation_order), effective_start_date=start,
        legal_reference=str(data.get("legal_reference") or source.legal_reference or "")[:300] or None, is_active=True,
    )
    if source.calculation_method == "BRACKET":
        seen = set()
        for i, b in enumerate(brackets, start=1):
            freq = str(b.get("pay_frequency") or "MONTHLY").upper()
            if freq not in ("MONTHLY", "BIWEEKLY", "WEEKLY"):
                raise PayrollError(f"Tramo {i}: frecuencia inválida.", "invalid", 400)
            lower = _dec(b.get("lower_bound"), f"tramo {i}: límite inferior", required=True, lo=Decimal(0))
            upper = _dec(b.get("upper_bound"), f"tramo {i}: límite superior", lo=Decimal(0))
            if upper is not None and upper <= lower:
                raise PayrollError(f"Tramo {i}: el límite superior debe ser mayor que el inferior.", "invalid", 400)
            if (freq, lower) in seen:
                raise PayrollError(f"Tramo {i}: límite inferior repetido.", "invalid", 400)
            seen.add((freq, lower))
            DeductionBracket.objects.create(
                deduction_type=new, pay_frequency=freq, lower_bound=lower, upper_bound=upper,
                rate=_dec(b.get("rate"), f"tramo {i}: tasa", required=True, lo=Decimal(0), hi=Decimal(1)),
                fixed_fee=_dec(b.get("fixed_fee"), f"tramo {i}: cuota fija", lo=Decimal(0)) or Decimal(0),
                excess_over=_dec(b.get("excess_over"), f"tramo {i}: exceso sobre", lo=Decimal(0)) or Decimal(0),
            )
    if source.effective_end_date is None or source.effective_end_date >= start:
        DeductionType.objects.filter(pk=source.pk).update(effective_end_date=start - timedelta(days=1))
    record("deduction_version_created", Category.PAYROLL,
           f"Nueva vigencia de {source.code} desde el {fmt(start)} (tasa {rate}, tope {cap}).", request=request, actor=user,
           target_type="DeductionType", target_id=str(new.deduction_type_id),
           details={"previous": source.deduction_type_id, "rate": str(rate) if rate is not None else None,
                    "base_cap": str(cap) if cap is not None else None})
    return new
