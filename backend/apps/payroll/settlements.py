"""Fase 21 — Liquidaciones e indemnizaciones (separadas de la planilla ordinaria).

Flujo:  BORRADOR (se abre al aplicarse la AP de terminación) → CALCULADA (se puede recalcular y ajustar) → APROBADA
        (contenido sellado SHA-256; SQL 50095) → PAGADA (en un LOTE de pago propio: cheques o transferencias, SQL 50096).
        BORRADOR / CALCULADA → ANULADA (con motivo).

Cálculo de referencia (El Salvador; parámetros en `pay_setting`, valídelos contra la normativa vigente):
  * Indemnización por despido sin causa (CT art. 58): 30 días de salario por año de servicio y proporcional por fracción;
    el salario se limita a 4 salarios mínimos; nunca menos de 15 días. Exenta de ISSS, AFP y Renta.
  * Prestación por renuncia voluntaria (Ley de 2013): con 2 o más años de servicio, 15 días por año; salario limitado a 2
    salarios mínimos. Exenta.
  * Vacaciones proporcionales: 15 días por año + prima del 30 %, desde el último aniversario. Cotiza y es gravada.
  * Aguinaldo proporcional: 15 / 19 / 21 días según la antigüedad, desde el 12 de diciembre anterior. No cotiza ISSS / AFP;
    exento de Renta hasta 2 salarios mínimos.
  * El salario de los días laborados hasta la terminación lo paga la planilla ordinaria del periodo (por horas).
  * Ajustes manuales (bonos pendientes, saldos de préstamos…) con su afectación; ISSS / AFP / Renta con las tablas mensuales.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.hcm.models import Employee
from apps.payroll import engine
from apps.payroll.engine import ZERO, q2, q4
from apps.payroll.models import PayrollSetting, Settlement, SettlementBatch, SettlementLine
from apps.system.audit import record
from apps.system.models import AuditEvent

Category = AuditEvent.Category
S = Settlement.Status
REASON_LABELS = {
    "RENUNCIA": "Renuncia voluntaria", "DESPIDO_SIN_CAUSA": "Despido sin causa justificada",
    "DESPIDO_CON_CAUSA": "Despido con causa justificada", "FIN_CONTRATO": "Fin de contrato a plazo",
    "MUTUO_ACUERDO": "Mutuo acuerdo", "ABANDONO": "Abandono de labores",
}
DEFAULT_AGUINALDO = [{"min_years": 0, "days": 15}, {"min_years": 3, "days": 19}, {"min_years": 10, "days": 21}]


class SettlementError(Exception):
    def __init__(self, message: str, code: str = "invalid", status: int = 409):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def fmt(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


# ================================================================ monto en letras (cheques)
_UNITS = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce", "trece",
          "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve", "veinte", "veintiuno", "veintidós",
          "veintitrés", "veinticuatro", "veinticinco", "veintiséis", "veintisiete", "veintiocho", "veintinueve"]
_TENS = ["", "", "", "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa"]
_HUNDREDS = ["", "ciento", "doscientos", "trescientos", "cuatrocientos", "quinientos", "seiscientos", "setecientos",
             "ochocientos", "novecientos"]


def _below_1000(n: int) -> str:
    if n == 100:
        return "cien"
    h, rest = divmod(n, 100)
    out = [_HUNDREDS[h]] if h else []
    if rest:
        if rest < 30:
            out.append(_UNITS[rest])
        else:
            t, u = divmod(rest, 10)
            out.append(_TENS[t] + (f" y {_UNITS[u]}" if u else ""))
    return " ".join(out)


def number_to_words(n: int) -> str:
    if n == 0:
        return "cero"
    parts = []
    millions, rest = divmod(n, 1_000_000)
    thousands, units = divmod(rest, 1000)
    if millions:
        parts.append("un millón" if millions == 1 else f"{number_to_words(millions)} millones")
    if thousands:
        parts.append("mil" if thousands == 1 else f"{_below_1000(thousands)} mil")
    if units:
        parts.append(_below_1000(units))
    text = " ".join(parts)
    return text.replace("uno mil", "un mil").replace("veintiuno mil", "veintiún mil")


def amount_in_words(amount, currency: str = "USD") -> str:
    """1234.5 → «MIL DOSCIENTOS TREINTA Y CUATRO 50/100 DÓLARES»."""
    value = q2(amount)
    whole = int(value)
    cents = int((value - whole) * 100)
    from apps.common.currency import words_name

    name = words_name(currency)  # Fase 22: moneda del país (dólares, quetzales, pesos…)
    words = number_to_words(whole)
    if words.endswith("veintiuno"):
        words = words[:-9] + "veintiún"  # «veintiún dólares»
    elif words.endswith("uno"):
        words = words[:-1]  # «un dólar», «treinta y un dólares»
    return f"{words} {cents:02d}/100 {name}".upper()


# ================================================================ cálculo
def setting_for(country_id: int, on: date) -> PayrollSetting | None:
    from apps.payroll.services import setting_for as _setting_for

    return _setting_for(country_id, on)


def _years(days: int) -> Decimal:
    return Decimal(days) / Decimal(365)


def _last_anniversary(hire: date, end: date) -> date:
    years = end.year - hire.year
    for y in (years, years - 1):
        try:
            candidate = hire.replace(year=hire.year + y)
        except ValueError:  # 29 de febrero
            candidate = date(hire.year + y, 2, 28)
        if candidate <= end:
            return max(candidate, hire)
    return hire


def compute(settlement: Settlement, setting: PayrollSetting) -> tuple[list[dict], list[str]]:
    """Líneas automáticas (sin las manuales) de la liquidación."""
    from apps.personnel_actions.lifecycle import tenure

    warnings: list[str] = []
    e = settlement.employee
    end = settlement.termination_date
    salary = Decimal(settlement.base_salary)
    daily = salary / Decimal(setting.days_per_month)
    min_wage = Decimal(setting.minimum_wage_monthly)
    t = tenure(e, end)
    service_days = t["days"]
    settlement.service_days = service_days
    years = _years(service_days)
    lines: list[dict] = []

    def add(kind, code, label, amount, **kw):
        lines.append({"kind": kind, "code": code, "label": label, "amount": q2(max(ZERO, amount)), **kw})

    reason = settlement.reason
    if reason == "DESPIDO_SIN_CAUSA":
        cap = min_wage * Decimal(setting.indemnity_cap_multiplier)
        base = min(salary, cap)
        d = base / Decimal(setting.days_per_month)
        days = Decimal(setting.indemnity_days_per_year) * years
        amount = d * days
        minimum = d * Decimal(setting.indemnity_min_days)
        note = f"{q2(years)} año(s) de servicio × {setting.indemnity_days_per_year} días; salario base {q2(base)}"
        if salary > cap:
            note += f" (limitado a {setting.indemnity_cap_multiplier} salarios mínimos = {q2(cap)})"
        if amount < minimum:
            amount, days = minimum, Decimal(setting.indemnity_min_days)
            note += f"; se aplica el mínimo de {setting.indemnity_min_days} días"
        add("EARNING", "INDEMNIZACION", "Indemnización por despido sin causa (CT art. 58)", amount, quantity=q4(days), unit="días",
            rate=q4(d), notes=note + ".")
    elif reason == "RENUNCIA":
        if years >= setting.resignation_min_years:
            cap = min_wage * Decimal(setting.resignation_cap_multiplier)
            base = min(salary, cap)
            d = base / Decimal(setting.days_per_month)
            days = Decimal(setting.resignation_days_per_year) * years
            add("EARNING", "PRESTACION_RENUNCIA", "Prestación económica por renuncia voluntaria", d * days, quantity=q4(days),
                unit="días", rate=q4(d), notes=f"{q2(years)} año(s) × {setting.resignation_days_per_year} días; salario base "
                f"{q2(base)} (tope {setting.resignation_cap_multiplier} salarios mínimos).")
        else:
            add("INFO", "PRESTACION_RENUNCIA", "Prestación por renuncia voluntaria: no aplica", ZERO,
                notes=f"Requiere {setting.resignation_min_years} años de servicio (tiene {q2(years)}).")
    elif reason == "MUTUO_ACUERDO":
        warnings.append("Mutuo acuerdo: registre el monto pactado como ajuste manual.")

    # Vacaciones proporcionales (con prima)
    anniversary = _last_anniversary(settlement.hire_date, end)
    since = (end - anniversary).days + 1
    vac_days = Decimal(setting.vacation_days_per_year) * Decimal(since) / Decimal(365)
    premium = 1 + Decimal(setting.vacation_premium_percent) / 100
    if vac_days > 0:
        add("EARNING", "VACACION_PROPORCIONAL", "Vacaciones proporcionales (con prima)", daily * vac_days * premium,
            quantity=q4(vac_days), unit="días", rate=q4(daily * premium), ss=True, tax=True,
            notes=f"{since} días desde el último aniversario ({fmt(anniversary)}) · prima del {setting.vacation_premium_percent} %.")

    # Aguinaldo proporcional (desde el 12 de diciembre anterior)
    start = date(end.year - 1, 12, 12) if end < date(end.year, 12, 12) else date(end.year, 12, 12)
    start = max(start, settlement.hire_date)
    agu_period = (end - start).days + 1
    tiers = sorted(setting.aguinaldo_tiers or DEFAULT_AGUINALDO, key=lambda x: x["min_years"])
    entitled = next((Decimal(t["days"]) for t in reversed(tiers) if years >= Decimal(str(t["min_years"]))), Decimal(tiers[0]["days"]))
    agu_days = entitled * Decimal(agu_period) / Decimal(365)
    agu = q2(daily * agu_days)
    if agu > 0:
        exempt = min_wage * Decimal(setting.aguinaldo_exempt_multiplier)
        taxable = q2(max(ZERO, agu - exempt))
        add("EARNING", "AGUINALDO_PROPORCIONAL", "Aguinaldo proporcional", agu, quantity=q4(agu_days), unit="días", rate=q4(daily),
            tax_amount=taxable, notes=f"{agu_period} días desde el {fmt(start)} · {entitled.normalize():f} días por año · exento de Renta "
            f"hasta {q2(exempt)}.")
    add("INFO", "SALARIO_PERIODO", "Salario de los días laborados", ZERO,
        notes="Lo paga la planilla ordinaria (por horas) del periodo que contiene la terminación.")
    return lines, warnings


def _legal_rules(country_id: int, on: date):
    from apps.payroll.services import legal_rules

    return legal_rules(country_id, on, "MONTHLY")


@transaction.atomic
def calculate(settlement: Settlement, *, user=None, request=None) -> Settlement:
    settlement = Settlement.objects.select_for_update().select_related("employee").get(pk=settlement.pk)
    if settlement.status not in (S.DRAFT, S.CALCULATED):
        raise SettlementError("Solo se calcula una liquidación en borrador o calculada.", "locked")
    setting = setting_for(settlement.employee.country_id, settlement.termination_date)
    if setting is None:
        raise SettlementError("No hay parámetros salariales vigentes para el país en la fecha de terminación.", "no_setting")
    auto, warnings = compute(settlement, setting)
    manual = list(settlement.lines.filter(is_manual=True))
    settlement.lines.filter(is_manual=False).delete()
    sort = 10
    rows = []
    for ln in auto:
        rows.append(SettlementLine(
            settlement=settlement, kind=ln["kind"], code=ln["code"], label=ln["label"], amount=ln["amount"], quantity=ln.get("quantity"),
            unit=ln.get("unit", ""), rate=ln.get("rate"), affects_social_security=bool(ln.get("ss")),
            affects_income_tax=bool(ln.get("tax")) or bool(ln.get("tax_amount")), notes=ln.get("notes", "")[:300], sort=sort,
            base=ln.get("tax_amount")))
        sort += 10
    SettlementLine.objects.bulk_create(rows)
    # Retenciones de ley sobre lo que cotiza / es gravado (tablas mensuales)
    earnings = [x for x in rows if x.kind == "EARNING"] + [x for x in manual if x.kind == "EARNING"]
    gross = q2(sum((x.amount for x in earnings), ZERO))
    ss_base = q2(sum((x.amount for x in earnings if x.affects_social_security), ZERO))
    tax_gross = q2(sum(((x.base if x.code == "AGUINALDO_PROPORCIONAL" and x.base is not None else x.amount)
                        for x in earnings if x.affects_income_tax), ZERO))
    rules = [r for r in _legal_rules(settlement.employee.country_id, settlement.termination_date) if r.party == "EMPLOYEE"]
    legal, legal_total, _employer, _taxable = engine.legal_lines(gross, ss_base, tax_gross, rules, Decimal(1), warnings)
    SettlementLine.objects.bulk_create([SettlementLine(
        settlement=settlement, kind="LEGAL", code=x.code, label=x.label, amount=x.amount, base=x.base, rate=x.rate,
        notes=x.notes[:300], sort=500 + i) for i, x in enumerate(legal) if x.amount > 0])
    other = q2(sum((x.amount for x in manual if x.kind == "DEDUCTION"), ZERO))
    deductions = q2(legal_total + other)
    if deductions > gross:
        raise SettlementError(f"Los descuentos ({deductions}) superan el devengado ({gross}): revise los ajustes manuales.", "negative", 400)
    settlement.gross, settlement.deductions, settlement.net = gross, deductions, q2(gross - deductions)
    settlement.status = S.CALCULATED
    settlement.calculated_at, settlement.calculated_by = timezone.now(), user if getattr(user, "pk", None) else None
    settlement.save()
    record("settlement_calculated", Category.PAYROLL,
           f"Liquidación {settlement.folio} de {settlement.employee.employee_code} calculada: líquido {settlement.net} {settlement.currency}.",
           request=request, actor=user, target=settlement.employee, details={"folio": settlement.folio, "warnings": warnings})
    settlement._warnings = warnings
    return settlement


def _next_folio(prefix: str) -> str:
    from apps.personnel_actions.services import next_folio

    return next_folio(prefix, timezone.localdate())


@transaction.atomic
def open_settlement(employee: Employee, *, reason: str, termination_date: date, action=None, user=None, request=None) -> Settlement:
    existing = Settlement.objects.filter(employee=employee, termination_date=termination_date).exclude(status=S.CANCELLED).first()
    if existing:
        return existing
    if reason not in REASON_LABELS:
        raise SettlementError("Motivo de terminación inválido.", "invalid_reason", 400)
    settlement = Settlement.objects.create(
        folio=_next_folio("LIQ"), employee=employee, termination_action=action, reason=reason, hire_date=employee.hire_date,
        termination_date=termination_date, base_salary=employee.base_salary, currency=employee.country.currency_code,
        created_by=user if getattr(user, "pk", None) else None)
    record("settlement_opened", Category.PAYROLL,
           f"Liquidación {settlement.folio} abierta para {employee.employee_code} ({REASON_LABELS[reason]}, terminación "
           f"{fmt(termination_date)}).", request=request, actor=user, target=employee, details={"folio": settlement.folio})
    try:
        settlement = calculate(settlement, user=user, request=request)
    except SettlementError:
        pass  # queda en borrador; RRHH la calcula cuando haya parámetros
    return settlement


def open_from_termination(action, *, user=None) -> Settlement | None:
    """Al aplicarse la AP de terminación se abre (y calcula) la liquidación del colaborador."""
    values = {v.attribute.key: v for v in action.values.select_related("attribute")}
    reason = values["motivo_terminacion"].value_text if "motivo_terminacion" in values else "RENUNCIA"
    employee = Employee.objects.select_related("country").get(pk=action.employee_id)
    return open_settlement(employee, reason=reason, termination_date=action.effective_date, action=action, user=user)


@transaction.atomic
def add_manual_line(settlement: Settlement, data: dict, *, user=None, request=None) -> Settlement:
    if settlement.status not in (S.DRAFT, S.CALCULATED):
        raise SettlementError("La liquidación ya está aprobada: no admite ajustes.", "locked")
    kind = str(data.get("kind") or "EARNING").upper()
    if kind not in ("EARNING", "DEDUCTION"):
        raise SettlementError("Tipo de ajuste inválido (EARNING o DEDUCTION).", "invalid", 400)
    label = str(data.get("label") or "").strip()[:200]
    try:
        amount = q2(Decimal(str(data.get("amount"))))
    except Exception:
        raise SettlementError("Monto inválido.", "invalid", 400) from None
    if not label or amount <= 0:
        raise SettlementError("Indique la descripción y un monto mayor que cero.", "invalid", 400)
    SettlementLine.objects.create(
        settlement=settlement, kind=kind, code="AJUSTE_MANUAL" if kind == "EARNING" else "DESCUENTO_MANUAL", label=label, amount=amount,
        affects_social_security=kind == "EARNING" and bool(data.get("affects_social_security")),
        affects_income_tax=kind == "EARNING" and bool(data.get("affects_income_tax")), is_manual=True,
        notes=str(data.get("notes") or "")[:300], sort=700 if kind == "DEDUCTION" else 300)
    record("settlement_adjusted", Category.PAYROLL, f"Ajuste manual «{label}» ({amount}) en la liquidación {settlement.folio}.",
           request=request, actor=user, target=settlement.employee, details={"folio": settlement.folio, "kind": kind})
    return calculate(settlement, user=user, request=request)


@transaction.atomic
def remove_manual_line(settlement: Settlement, line_id: int, *, user=None, request=None) -> Settlement:
    if settlement.status not in (S.DRAFT, S.CALCULATED):
        raise SettlementError("La liquidación ya está aprobada: no admite ajustes.", "locked")
    deleted, _ = settlement.lines.filter(pk=line_id, is_manual=True).delete()
    if not deleted:
        raise SettlementError("Solo se quitan los ajustes manuales.", "not_found", 404)
    return calculate(settlement, user=user, request=request)


def content_of(settlement: Settlement) -> dict:
    e = settlement.employee

    def ln(x: SettlementLine) -> dict:
        return {"kind": x.kind, "code": x.code, "label": x.label, "quantity": str(x.quantity) if x.quantity is not None else None,
                "unit": x.unit, "rate": str(x.rate) if x.rate is not None else None, "amount": f"{x.amount:.2f}", "notes": x.notes,
                "manual": x.is_manual}

    return {
        "folio": settlement.folio, "currency": settlement.currency,
        "employee": {"code": e.employee_code, "name": e.full_name, "national_id": f"{e.national_id_type} {e.national_id_number}"},
        "reason": settlement.reason, "reason_label": REASON_LABELS.get(settlement.reason, settlement.reason),
        "hire_date": settlement.hire_date.isoformat(), "termination_date": settlement.termination_date.isoformat(),
        "base_salary": f"{settlement.base_salary:.2f}", "service_days": settlement.service_days,
        "lines": [ln(x) for x in settlement.lines.order_by("sort", "id")],
        "totals": {"gross": f"{settlement.gross:.2f}", "deductions": f"{settlement.deductions:.2f}", "net": f"{settlement.net:.2f}"},
        "net_in_words": amount_in_words(settlement.net, settlement.currency),
    }


@transaction.atomic
def approve(settlement: Settlement, *, user=None, request=None) -> Settlement:
    settlement = Settlement.objects.select_for_update().select_related("employee").get(pk=settlement.pk)
    if settlement.status != S.CALCULATED:
        raise SettlementError("Solo se aprueba una liquidación calculada.", "not_calculated")
    if settlement.net <= 0:
        raise SettlementError("La liquidación no tiene monto a pagar.", "empty")
    content = content_of(settlement)
    settlement.content = content
    settlement.content_hash = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    settlement.status = S.APPROVED
    settlement.approved_at, settlement.approved_by = timezone.now(), user if getattr(user, "pk", None) else None
    settlement.save()
    record("settlement_approved", Category.PAYROLL, f"Liquidación {settlement.folio} aprobada y sellada ({settlement.net} {settlement.currency}).",
           request=request, actor=user, target=settlement.employee, details={"folio": settlement.folio, "hash": settlement.content_hash})
    return settlement


@transaction.atomic
def cancel(settlement: Settlement, *, reason: str, user=None, request=None) -> Settlement:
    if settlement.status not in (S.DRAFT, S.CALCULATED):
        raise SettlementError("Solo se anula una liquidación en borrador o calculada.", "locked")
    reason = (reason or "").strip()
    if not reason:
        raise SettlementError("Indique el motivo de la anulación.", "reason_required", 400)
    settlement.status, settlement.cancel_reason = S.CANCELLED, reason[:500]
    settlement.save(update_fields=["status", "cancel_reason"])
    record("settlement_cancelled", Category.PAYROLL, f"Liquidación {settlement.folio} anulada: {reason[:200]}", request=request,
           actor=user, target=settlement.employee, details={"folio": settlement.folio})
    return settlement


# ================================================================ lotes de pago (cheques / transferencias)
@transaction.atomic
def create_batch(data: dict, *, user=None, request=None) -> SettlementBatch:
    from apps.common.models import Country
    from apps.personnel_actions.services import parse_date

    country = Country.objects.filter(Q(country_code=str(data.get("country") or "SV").upper())).first()
    pay = parse_date(data.get("payment_date"))
    if country is None or pay is None:
        raise SettlementError("Indique el país y la fecha de pago del lote.", "invalid", 400)
    method = str(data.get("method") or "CHECK").upper()
    if method not in SettlementBatch.Method.values:
        raise SettlementError("Forma de pago inválida.", "invalid", 400)
    batch = SettlementBatch.objects.create(code=_next_folio("LTLQ"), country_id=country.pk, payment_date=pay, method=method,
                                           bank_account=str(data.get("bank_account") or "")[:60], notes=str(data.get("notes") or "")[:300],
                                           created_by=user if getattr(user, "pk", None) else None)
    ids = data.get("settlements") or []
    if ids:
        add_to_batch(batch, ids, user=user, request=request, first_check=data.get("first_check"))
    record("settlement_batch_created", Category.PAYROLL, f"Lote de pago de liquidaciones {batch.code} ({batch.get_method_display()}).",
           request=request, actor=user, target_type="SettlementBatch", target_id=str(batch.pk))
    return batch


@transaction.atomic
def add_to_batch(batch: SettlementBatch, ids, *, user=None, request=None, first_check=None) -> dict:
    if batch.status != SettlementBatch.Status.OPEN:
        raise SettlementError("El lote ya está cerrado.", "batch_closed")
    rows = list(Settlement.objects.select_for_update().filter(pk__in=[int(i) for i in ids]).order_by("folio"))
    bad = [s.folio for s in rows if s.status != S.APPROVED or (s.batch_id and s.batch_id != batch.pk)]
    if bad:
        raise SettlementError(f"Solo entran liquidaciones aprobadas y sin lote: {', '.join(bad)}.", "invalid_settlements", 400)
    number = None
    if first_check not in (None, "") and batch.method == SettlementBatch.Method.CHECK:
        try:
            number = int(str(first_check))
        except ValueError:
            raise SettlementError("El número de cheque inicial debe ser numérico.", "invalid", 400) from None
    for s in rows:
        s.batch = batch
        if number is not None:
            s.check_number = str(number)
            number += 1
        s.save(update_fields=["batch", "check_number"])
    return {"added": len(rows)}


@transaction.atomic
def remove_from_batch(batch: SettlementBatch, settlement_id: int, *, user=None, request=None) -> None:
    if batch.status != SettlementBatch.Status.OPEN:
        raise SettlementError("El lote ya está cerrado.", "batch_closed")
    Settlement.objects.filter(pk=settlement_id, batch=batch).update(batch=None, check_number="")


@transaction.atomic
def set_check(settlement: Settlement, number: str) -> Settlement:
    if not settlement.batch_id or settlement.batch.status != SettlementBatch.Status.OPEN:
        raise SettlementError("El número de cheque se asigna con el lote abierto.", "batch_closed")
    settlement.check_number = str(number or "").strip()[:30]
    settlement.save(update_fields=["check_number"])
    return settlement


@transaction.atomic
def batch_transition(batch: SettlementBatch, action: str, *, user=None, request=None) -> SettlementBatch:
    items = list(batch.settlements.all())
    if action == "close":
        if batch.status != SettlementBatch.Status.OPEN or not items:
            raise SettlementError("Solo se cierra un lote abierto con liquidaciones.", "invalid")
        if batch.method == SettlementBatch.Method.CHECK and any(not s.check_number for s in items):
            raise SettlementError("Asigne el número de cheque de cada liquidación antes de cerrar el lote.", "checks_missing", 400)
        batch.status, batch.closed_at = SettlementBatch.Status.CLOSED, timezone.now()
    elif action == "reopen":
        if batch.status != SettlementBatch.Status.CLOSED:
            raise SettlementError("Solo se reabre un lote cerrado (no pagado).", "invalid")
        batch.status, batch.closed_at = SettlementBatch.Status.OPEN, None
    elif action == "pay":
        if batch.status != SettlementBatch.Status.CLOSED:
            raise SettlementError("Cierre el lote antes de marcarlo como pagado.", "invalid")
        now = timezone.now()
        batch.status, batch.paid_at = SettlementBatch.Status.PAID, now
        Settlement.objects.filter(batch=batch, status=S.APPROVED).update(status=S.PAID, paid_at=now)
    else:
        raise SettlementError("Acción inválida.", "invalid", 400)
    batch.save()
    record(f"settlement_batch_{action}", Category.PAYROLL, f"Lote {batch.code}: {action}.", request=request, actor=user,
           target_type="SettlementBatch", target_id=str(batch.pk), details={"settlements": len(items)})
    return batch


# ================================================================ representación
def line_dict(x: SettlementLine) -> dict:
    return {"id": x.pk, "kind": x.kind, "kind_label": x.get_kind_display(), "code": x.code, "label": x.label, "quantity": x.quantity,
            "unit": x.unit, "rate": x.rate, "amount": x.amount, "affects_social_security": x.affects_social_security,
            "affects_income_tax": x.affects_income_tax, "is_manual": x.is_manual, "notes": x.notes}


def settlement_dict(s: Settlement, *, detail: bool = False) -> dict:
    e = s.employee
    out = {
        "id": s.pk, "folio": s.folio, "employee_code": e.employee_code, "full_name": e.full_name, "reason": s.reason,
        "reason_label": REASON_LABELS.get(s.reason, s.reason), "hire_date": s.hire_date, "termination_date": s.termination_date,
        "base_salary": s.base_salary, "service_days": s.service_days, "service_years": q2(_years(s.service_days)),
        "status": s.status, "status_label": s.get_status_display(), "gross": s.gross, "deductions": s.deductions, "net": s.net,
        "currency": s.currency, "batch": s.batch.code if s.batch_id else None, "batch_id": s.batch_id, "check_number": s.check_number,
        "termination_folio": s.termination_action.folio if s.termination_action_id else None,
        "calculated_at": s.calculated_at, "approved_at": s.approved_at, "paid_at": s.paid_at, "cancel_reason": s.cancel_reason,
    }
    if detail:
        out["lines"] = [line_dict(x) for x in s.lines.order_by("sort", "id")]
        out["content_hash"] = s.content_hash
        out["net_in_words"] = amount_in_words(s.net, s.currency)
        out["warnings"] = getattr(s, "_warnings", [])
    return out


def batch_dict(b: SettlementBatch, *, detail: bool = False) -> dict:
    items = list(b.settlements.select_related("employee").order_by("folio"))
    out = {"id": b.pk, "code": b.code, "payment_date": b.payment_date, "method": b.method, "method_label": b.get_method_display(),
           "bank_account": b.bank_account, "status": b.status, "status_label": b.get_status_display(), "notes": b.notes,
           "count": len(items), "total": q2(sum((s.net for s in items), ZERO)), "closed_at": b.closed_at, "paid_at": b.paid_at}
    if detail:
        out["settlements"] = [{**settlement_dict(s), "net_in_words": amount_in_words(s.net, s.currency)} for s in items]
    return out


def pending_terminations() -> list[dict]:
    """Colaboradores TERMINADOS sin liquidación vigente (p. ej. terminados antes de la Fase 21)."""
    have = Settlement.objects.exclude(status=S.CANCELLED).values_list("employee_id", "termination_date")
    have = set(have)
    rows = Employee.objects.filter(employment_status=Employee.Status.TERMINATED, termination_date__isnull=False).order_by("-termination_date")[:200]
    return [{"employee_code": e.employee_code, "full_name": e.full_name, "termination_date": e.termination_date}
            for e in rows if (e.pk, e.termination_date) not in have]


__all__ = ["amount_in_words", "approve", "calculate", "cancel", "open_from_termination", "open_settlement"]
