"""Fase 21 — Motor de planilla 100 % POR HORAS (estándar BPO), funciones puras sin acceso a la base de datos.

El motor no calcula por días: calcula por horas programadas y reales.

    salario del periodo   = salario mensual × fracción de la frecuencia (quincena = 50 %) × fracción contratada (días del
                            periodo contratado y no suspendido)
    rate por hora         = salario del periodo ÷ horas PROGRAMADAS del colaborador en los cortes internos del periodo
                            (horario vigente)
    salario por horas     = rate × horas reales PAGABLES (validadas: Web Timer / adherencia guardada y AP; nunca más que lo
                            programado: el exceso sin AP de horas extra es Unpaid Excess Login)
    recargos              = nocturnidad (rate × % de la regla del país, 25 % de 19:00 a 06:00) + feriado laborado (rate ×
                            recargo del feriado: pago doble) + horas extra de AP (rate × (1 + 100 %), nocturnas × (1 + 25 %))
    séptimo día           = OPCIONAL: si la cuenta lo activa, cada semana con Unjustified Absence pierde las horas de un día
    retenciones de ley    = ISSS / AFP (tope proporcional al periodo) y Renta por tramos sobre devengado gravado − ISSS − AFP
    líquido               = devengado − retenciones − descuentos autorizados por AP (nunca negativo)

Las horas no laboradas (ausencias, Lateness, permisos sin goce, suspensiones) no se pagan: no hay descuentos por días.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
CENT = Decimal("0.01")
HOUR = Decimal(3600)


def q2(value) -> Decimal:
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def q4(value) -> Decimal:
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def hours(seconds) -> Decimal:
    return Decimal(seconds or 0) / HOUR


# Fase 22 — «Contract Type» del Optimum ES Payroll Hours (columnas AA–AC): qué retenciones aplican por contrato.
#   PERMANENTE                     ISSS 3 % (tope) + AFP 7.25 % + Renta por tabla
#   PERMANENTE JB                  sin ISSS; AFP 7.25 % + Renta por tabla
#   SERVICIOS PROFESIONALES        sin ISSS ni AFP; Renta 10 % fija sobre lo gravado
#   SERVICIOS PROF. INTERNACIONAL  sin ISSS ni AFP; Renta 20 % fija sobre lo gravado
CONTRACT_RULES: dict[str, dict] = {
    "PERMANENTE": {"social_security": True, "pension": True, "flat_tax": None},
    "PERMANENTE JB": {"social_security": False, "pension": True, "flat_tax": None},
    "SERVICIOS PROFESIONALES": {"social_security": False, "pension": False, "flat_tax": Decimal("0.10")},
    "SERVICIOS PROF. INTERNACIONAL": {"social_security": False, "pension": False, "flat_tax": Decimal("0.20")},
}
DEFAULT_CONTRACT = "PERMANENTE"


def contract_rule(contract_type: str | None) -> dict:
    return CONTRACT_RULES.get((contract_type or DEFAULT_CONTRACT).upper(), CONTRACT_RULES[DEFAULT_CONTRACT])


@dataclass(frozen=True)
class Params:
    days_per_month: int = 30
    hours_per_day: Decimal = Decimal(8)
    overtime_surcharge_percent: Decimal = Decimal(100)
    vacation_premium_percent: Decimal = Decimal(30)
    seventh_day_penalty: bool = False
    holiday_premium_percent: Decimal = Decimal(100)


@dataclass(frozen=True)
class Bracket:
    lower: Decimal
    upper: Decimal | None
    rate: Decimal
    fixed_fee: Decimal
    excess_over: Decimal


@dataclass(frozen=True)
class LegalRule:
    id: int
    code: str
    name: str
    category: str  # SOCIAL_SECURITY | PENSION | INCOME_TAX | OTHER
    party: str  # EMPLOYEE | EMPLOYER
    method: str  # PERCENTAGE | BRACKET | FIXED
    rate: Decimal | None = None
    fixed_amount: Decimal | None = None
    base_cap: Decimal | None = None  # tope MENSUAL de la base
    reduces_taxable_base: bool = False
    order: int = 100
    brackets: tuple[Bracket, ...] = ()  # de la frecuencia del periodo
    monthly_brackets: tuple[Bracket, ...] = ()  # respaldo: se proyecta el periodo a un mes


@dataclass(frozen=True)
class Concept:
    code: str
    name: str
    kind: str  # EARNING | TIME_DISCOUNT | DEDUCTION
    source: str
    affects_social_security: bool = True
    affects_income_tax: bool = True
    calculation: str = "ENGINE"
    sort: int = 100


@dataclass(frozen=True)
class ActionItem:
    action_id: int
    folio: str
    concept: str
    quantity: Decimal
    effective_date: date


@dataclass(frozen=True)
class HolidayItem:
    date: date
    name: str
    seconds: int
    premium_percent: Decimal


@dataclass
class EmployeeInput:
    monthly_salary: Decimal
    frequency: str  # MONTHLY | BIWEEKLY | WEEKLY
    period_calendar_days: int
    employed_calendar_days: int  # contratado y NO suspendido dentro del periodo
    scheduled_seconds: int = 0  # programado (horario vigente) en los cortes, días contratados y no suspendidos
    # Fase 22: programado del CORTE COMPLETO (aunque ingrese a mitad o se retire antes): base del rate por hora
    cutoff_scheduled_seconds: int = 0
    contract_type: str = DEFAULT_CONTRACT
    paid_seconds: int = 0  # pagable validado (incluye feriados laborados y vacaciones gozadas)
    worked_seconds: int = 0  # Web Timer y demás registros (bruto)
    night_seconds: int = 0  # pagable nocturno
    night_surcharge_percent: Decimal = ZERO
    vacation_seconds: int = 0  # programado en días de vacaciones (AP): se paga como tiempo
    holidays: list[HolidayItem] = field(default_factory=list)
    absence_dates: list[date] = field(default_factory=list)
    lateness_seconds: int = 0
    unpaid_leave_seconds: int = 0
    out_of_adherence_seconds: int = 0
    unpaid_excess_seconds: int = 0
    suspended_days: int = 0
    adherence_days: int = 0
    seventh_day_penalty: bool | None = None  # regla de la cuenta; None = la de los parámetros
    account: str = ""
    actions: list[ActionItem] = field(default_factory=list)


@dataclass
class Line:
    kind: str  # EARNING | TIME_DISCOUNT | LEGAL | DEDUCTION | EMPLOYER | INFO
    code: str
    label: str
    amount: Decimal = ZERO
    quantity: Decimal | None = None
    unit: str = ""
    rate: Decimal | None = None
    base: Decimal | None = None
    source: str = ""
    concept: str | None = None
    deduction_type_id: int | None = None
    action_id: int | None = None
    notes: str = ""
    sort: int = 100


@dataclass
class Result:
    lines: list[Line]
    period_salary: Decimal
    hourly_rate: Decimal
    scheduled_seconds: int
    paid_seconds: int
    paid_days: Decimal
    gross_pay: Decimal
    social_security_base: Decimal
    taxable_base: Decimal
    legal_deductions: Decimal
    other_deductions: Decimal
    total_deductions: Decimal
    net_pay: Decimal
    employer_contributions: Decimal
    overtime_amount: Decimal
    other_earnings: Decimal
    warnings: list[str]


def period_fraction(frequency: str, days_per_month: int) -> Decimal:
    """Parte del salario MENSUAL que corresponde al periodo: quincena 50 %, mes 100 %, semana 7 / 30."""
    return {"MONTHLY": Decimal(1), "BIWEEKLY": Decimal("0.5"), "WEEKLY": Decimal(7) / Decimal(days_per_month)}.get(frequency, Decimal(1))


def bracket_tax(base: Decimal, brackets: tuple[Bracket, ...]) -> tuple[Decimal, Bracket | None]:
    """Monto = cuota fija + (base − exceso sobre) × tasa, con el tramo de mayor límite inferior ≤ base."""
    chosen = None
    for b in sorted(brackets, key=lambda x: x.lower):
        if b.lower <= base:
            chosen = b
    if chosen is None:
        return ZERO, None
    return max(ZERO, chosen.fixed_fee + (base - chosen.excess_over) * chosen.rate), chosen


def weeks_with(dates: list[date]) -> int:
    return len({d.isocalendar()[:2] for d in dates})


def legal_lines(gross: Decimal, ss_base: Decimal, tax_gross: Decimal, rules: list[LegalRule], fraction: Decimal,
                warnings: list[str], contract_type: str | None = None) -> tuple[list[Line], Decimal, Decimal, Decimal]:
    """Retenciones de ley y aportes patronales en su orden de cálculo. Devuelve (líneas, laboral, patronal, base Renta).

    Fase 22: el tipo de contrato (roster) decide qué retenciones aplican (CONTRACT_RULES, Optimum ES Payroll Hours)."""
    lines: list[Line] = []
    reducing = legal_employee = employer = ZERO
    taxable_base = tax_gross
    contract = contract_rule(contract_type)
    for r in sorted(rules, key=lambda x: (x.order, x.code)):
        if (r.category == "SOCIAL_SECURITY" and not contract["social_security"]) or (r.category == "PENSION" and not contract["pension"]):
            continue
        if r.category == "INCOME_TAX" and contract["flat_tax"] is not None and r.party == "EMPLOYEE":
            base = q2(tax_gross)
            taxable_base = base
            amount = q2(base * contract["flat_tax"])
            lines.append(Line(kind="LEGAL", code=r.code, label=r.name, amount=amount, base=base, rate=contract["flat_tax"], source="LAW",
                              deduction_type_id=r.id, sort=500 + r.order,
                              notes=f"Contrato {(contract_type or DEFAULT_CONTRACT).upper()}: retención fija del "
                                    f"{(contract['flat_tax'] * 100).normalize():f} % sobre lo gravado."))
            legal_employee += amount
            continue
        if r.category == "INCOME_TAX":
            base = q2(max(ZERO, tax_gross - reducing))
            taxable_base = base
        else:
            base = ss_base
        rate = r.rate
        notes = ""
        if r.method == "PERCENTAGE":
            capped = base
            if r.base_cap:
                cap = q2(Decimal(r.base_cap) * fraction)
                if base > cap:
                    capped, notes = cap, f"Base limitada al tope de {cap} del periodo."
            amount = capped * Decimal(r.rate or 0)
            base = capped
        elif r.method == "FIXED":
            amount = Decimal(r.fixed_amount or 0) * fraction
        else:  # BRACKET
            if r.brackets:
                amount, b = bracket_tax(base, r.brackets)
            elif r.monthly_brackets:
                monthly, b = bracket_tax(q2(base / fraction), r.monthly_brackets)
                amount = monthly * fraction
                notes = "Tabla mensual proyectada al periodo (no hay tramos de esta frecuencia)."
            else:
                amount, b = ZERO, None
                warnings.append(f"{r.name}: no hay tramos configurados; no se retuvo.")
            rate = b.rate if b else None
            if b:
                notes = (notes + " " if notes else "") + (f"Tramo desde {b.lower}: cuota {b.fixed_fee} + {b.rate * 100:.2f} % "
                                                          f"sobre el exceso de {b.excess_over}.")
        amount = q2(max(ZERO, amount))
        if amount == 0 and r.method == "FIXED":
            continue
        kind = "LEGAL" if r.party == "EMPLOYEE" else "EMPLOYER"
        lines.append(Line(kind=kind, code=r.code, label=r.name, amount=amount, base=base, rate=rate, source="LAW",
                          deduction_type_id=r.id, notes=notes, sort=500 + r.order if kind == "LEGAL" else 800 + r.order))
        if kind == "LEGAL":
            legal_employee += amount
            if r.reduces_taxable_base:
                reducing += amount
        else:
            employer += amount
    return lines, legal_employee, employer, taxable_base


def calculate(inp: EmployeeInput, params: Params, rules: list[LegalRule], concepts: dict[str, Concept]) -> Result:
    warnings: list[str] = []
    dpm = Decimal(params.days_per_month)
    hpd = Decimal(params.hours_per_day)
    fraction = period_fraction(inp.frequency, params.days_per_month)
    salary = Decimal(inp.monthly_salary)
    employed = min(Decimal(1), Decimal(inp.employed_calendar_days) / Decimal(max(inp.period_calendar_days, 1)))
    # Fase 22: con el programado del corte COMPLETO el rate no depende de la fecha de ingreso / retiro: el salario del
    # periodo (50 % del mensual en quincenal) ÷ las horas que el puesto tiene programadas en todo el corte; el
    # colaborador cobra rate × sus horas pagables (prorrateo exacto de los actuals). Sin ese dato: proporción de días.
    full_cutoff = inp.cutoff_scheduled_seconds > 0
    period_salary = q2(salary * fraction) if full_cutoff else q2(salary * fraction * employed)
    scheduled_h = hours(inp.cutoff_scheduled_seconds if full_cutoff else inp.scheduled_seconds)
    if scheduled_h > 0:
        rate = period_salary / scheduled_h
    else:
        rate = salary / dpm / hpd
        if inp.paid_seconds or inp.actions:
            warnings.append("Sin horas programadas en el periodo: se usó el valor hora de referencia (salario mensual / 30 / 8).")
    paid_seconds = min(inp.paid_seconds, inp.scheduled_seconds) if inp.scheduled_seconds else inp.paid_seconds
    if inp.paid_seconds > inp.scheduled_seconds and inp.scheduled_seconds:
        warnings.append("Las horas pagables superaban las programadas: el exceso solo se paga con AP de horas extra.")
    vacation_seconds = min(inp.vacation_seconds, paid_seconds)
    regular_seconds = paid_seconds - vacation_seconds

    def concept(code: str) -> Concept:
        return concepts.get(code) or Concept(code, code, "EARNING", "SALARY")

    lines: list[Line] = []

    def add(kind: str, code: str, amount, **kw) -> Line:
        c = concepts.get(code)
        line = Line(kind=kind, code=code, label=kw.pop("label", c.name if c else code), amount=q2(amount), concept=code if c else None,
                    sort=kw.pop("sort", c.sort if c else 100), source=kw.pop("source", c.source if c else ""), **kw)
        lines.append(line)
        return line

    notes = f"Rate = {period_salary} ÷ {q2(scheduled_h)} h programadas" + (" del corte completo." if full_cutoff else ".")
    if full_cutoff and inp.cutoff_scheduled_seconds > inp.scheduled_seconds:
        notes += (f" Prorrateo: programado {q2(hours(inp.scheduled_seconds))} h de {q2(scheduled_h)} h del corte (ingreso, retiro o "
                  "suspensión dentro del corte).")
    elif not full_cutoff and employed < 1:
        notes += f" Proporcional: {inp.employed_calendar_days} de {inp.period_calendar_days} días contratado y no suspendido."
    add("EARNING", "SALARIO", rate * hours(regular_seconds), quantity=q4(hours(regular_seconds)), unit="horas",
        rate=q4(rate), notes=notes)
    if vacation_seconds:
        add("EARNING", "VACACIONES_GOCE", rate * hours(vacation_seconds), quantity=q4(hours(vacation_seconds)), unit="horas",
            rate=q4(rate), notes="Horas programadas en los días de vacaciones de la AP (tiempo pagado).")

    # ---- séptimo día OPCIONAL (regla de la cuenta o de los parámetros)
    absences = sorted(set(inp.absence_dates))
    seventh = params.seventh_day_penalty if inp.seventh_day_penalty is None else inp.seventh_day_penalty
    if absences and seventh:
        w = Decimal(weeks_with(absences))
        h = w * hpd
        amount = q2(rate * h)
        available = q2(sum((ln.amount for ln in lines), ZERO))
        if amount > available:
            warnings.append(f"Séptimo día: el descuento ({amount}) superaba el salario por horas; se limitó a {available}.")
            amount = available
        if amount > 0:
            add("TIME_DISCOUNT", "SEPTIMO_DIA", -amount, quantity=q4(h), unit="horas", rate=q4(rate),
                notes=f"{int(w)} semana(s) con Unjustified Absence" + (f" · regla de la cuenta {inp.account}" if inp.account else "") + ".")

    # ---- recargos: nocturnidad y feriados laborados
    night_h = hours(min(inp.night_seconds, paid_seconds))
    if night_h > 0 and inp.night_surcharge_percent:
        pct = Decimal(inp.night_surcharge_percent)
        add("EARNING", "NOCTURNIDAD", rate * pct / 100 * night_h, quantity=q4(night_h), unit="horas", rate=q4(rate * pct / 100),
            notes=f"Recargo nocturno del {pct.normalize():f} % sobre las horas laboradas en la franja nocturna del país.")
    for hol in sorted(inp.holidays, key=lambda x: x.date):
        h = hours(hol.seconds)
        if h <= 0:
            continue
        pct = Decimal(hol.premium_percent)
        add("EARNING", "FERIADO", rate * pct / 100 * h, quantity=q4(h), unit="horas", rate=q4(rate * pct / 100),
            label=f"Feriado laborado: {hol.name} ({hol.date:%d/%m})",
            notes=f"Holiday Segment: las horas se pagan como salario regular + {pct.normalize():f} % (pago doble).")

    # ---- AP: horas extra, bonificaciones, prima de vacaciones
    ot_factor = 1 + Decimal(params.overtime_surcharge_percent) / 100
    night_factor = 1 + Decimal(inp.night_surcharge_percent) / 100
    daily = salary / dpm
    post_deductions: list[tuple[ActionItem, Concept]] = []
    for item in inp.actions:
        c = concepts.get(item.concept)
        if c is None:
            continue
        qty = Decimal(item.quantity)
        if c.kind == "DEDUCTION":
            post_deductions.append((item, c))
            continue
        if c.calculation == "OVERTIME_DAY":
            r = rate * ot_factor
            amount, unit = r * qty, "horas"
        elif c.calculation == "OVERTIME_NIGHT":
            r = rate * night_factor * ot_factor
            amount, unit = r * qty, "horas"
        elif c.calculation == "VACATION":
            r = daily * Decimal(params.vacation_premium_percent) / 100
            amount, unit = r * qty, "días"
        else:
            r, amount, unit = None, qty, ""
        add("EARNING", c.code, amount, quantity=q4(qty) if unit else None, unit=unit, rate=q4(r) if r is not None else None,
            action_id=item.action_id, notes=f"AP {item.folio} ({item.effective_date:%d/%m/%Y})")

    earnings = [ln for ln in lines if ln.kind in ("EARNING", "TIME_DISCOUNT")]
    gross = q2(sum((ln.amount for ln in earnings), ZERO))
    ss_base = q2(max(ZERO, sum((ln.amount for ln in earnings if concept(ln.code).affects_social_security), ZERO)))
    tax_gross = q2(max(ZERO, sum((ln.amount for ln in earnings if concept(ln.code).affects_income_tax), ZERO)))

    legal, legal_employee, employer, taxable_base = legal_lines(gross, ss_base, tax_gross, rules, fraction, warnings,
                                                                inp.contract_type)
    lines += legal

    # ---- descuentos autorizados por AP (después de retenciones; el líquido nunca queda negativo)
    available = gross - legal_employee
    other = ZERO
    for item, c in post_deductions:
        amount = q2(item.quantity)
        if amount > available:
            warnings.append(f"{c.name} de la AP {item.folio}: {amount} excede el líquido disponible; se descontó {q2(max(available, ZERO))}.")
            amount = q2(max(available, ZERO))
        if amount <= 0:
            continue
        available -= amount
        other += amount
        lines.append(Line(kind="DEDUCTION", code=c.code, label=c.name, amount=amount, concept=c.code, source=c.source,
                          action_id=item.action_id, notes=f"AP {item.folio} ({item.effective_date:%d/%m/%Y})", sort=c.sort))

    # ---- información (sin monto): de dónde salen las horas
    def info(code: str, label: str, qty, unit: str = "horas", notes: str = "", source: str = "") -> None:
        lines.append(Line(kind="INFO", code=code, label=label, quantity=q4(qty), unit=unit, notes=notes, source=source, sort=900))

    if full_cutoff:
        info("HORAS_PROGRAMADAS_CORTE", "Horas programadas del corte completo", scheduled_h, notes="Base del rate por hora.",
             source="SALARY")
    info("HORAS_PROGRAMADAS", "Horas programadas (horario vigente)", hours(inp.scheduled_seconds),
         notes="Días contratados y no suspendidos dentro de los cortes." if full_cutoff else "Base del rate por hora.", source="SALARY")
    if (inp.contract_type or DEFAULT_CONTRACT).upper() != DEFAULT_CONTRACT:
        info("TIPO_CONTRATO", f"Tipo de contrato: {inp.contract_type.upper()}", Decimal(0), "", source="SALARY",
             notes="Define las retenciones de ley aplicadas.")
    info("HORAS_PAGADAS", "Horas pagables validadas", hours(paid_seconds),
         notes="Web Timer / adherencia guardada y AP; incluye feriados laborados y vacaciones.", source="WEB_TIMER")
    if inp.worked_seconds:
        info("WEB_TIMER_HORAS", "Horas registradas (Web Timer)", hours(inp.worked_seconds), source="WEB_TIMER")
    missing = max(0, inp.scheduled_seconds - paid_seconds)
    if missing:
        parts = []
        if absences:
            parts.append(f"{len(absences)} día(s) de Unjustified Absence ({', '.join(f'{d:%d/%m}' for d in absences)})")
        if inp.lateness_seconds:
            parts.append(f"Lateness {q2(hours(inp.lateness_seconds))} h")
        if inp.unpaid_leave_seconds:
            parts.append(f"permisos sin goce {q2(hours(inp.unpaid_leave_seconds))} h")
        info("HORAS_NO_PAGADAS", "Horas programadas no laboradas (no se pagan)", hours(missing), notes="; ".join(parts), source="ADHERENCE")
    if inp.suspended_days:
        info("SUSPENSION", "Días de suspensión disciplinaria (sin goce)", Decimal(inp.suspended_days), "días", source="AP")
    if inp.out_of_adherence_seconds:
        info("OUT_OF_ADHERENCE", "Out of Adherence (adherencia guardada)", hours(inp.out_of_adherence_seconds),
             notes=f"{inp.adherence_days} días calculados; solo se paga el tiempo validado para pago.", source="ADHERENCE")
    if inp.unpaid_excess_seconds:
        info("UNPAID_EXCESS", "Unpaid Excess Login (no se paga sin AP de horas extra)", hours(inp.unpaid_excess_seconds), source="ADHERENCE")

    total_deductions = q2(legal_employee + other)
    net = q2(gross - total_deductions)
    overtime = q2(sum((ln.amount for ln in lines if ln.kind == "EARNING" and concept(ln.code).calculation in ("OVERTIME_DAY", "OVERTIME_NIGHT")), ZERO))
    base_codes = {"SALARIO", "VACACIONES_GOCE"}
    other_earnings = q2(sum((ln.amount for ln in lines if ln.kind == "EARNING" and ln.code not in base_codes), ZERO) - overtime)
    lines.sort(key=lambda ln: (ln.sort, ln.code))
    return Result(
        lines=lines, period_salary=period_salary, hourly_rate=q4(rate), scheduled_seconds=inp.scheduled_seconds,
        paid_seconds=paid_seconds, paid_days=q2(hours(paid_seconds) / hpd), gross_pay=gross, social_security_base=ss_base,
        taxable_base=taxable_base, legal_deductions=q2(legal_employee), other_deductions=q2(other), total_deductions=total_deductions,
        net_pay=net, employer_contributions=q2(employer), overtime_amount=overtime, other_earnings=max(ZERO, other_earnings),
        warnings=warnings,
    )
