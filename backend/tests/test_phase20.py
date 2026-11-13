"""Fase 20: cálculo automático de planilla (Web Timer, AP de pago, segmentos y adherencia), cierre con generación masiva
de boletas e inventario físico de boletas por periodo (impresas, firmadas, archivadas)."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.db import DatabaseError, connection
from django.utils import timezone

from apps.adherence.models import ActivityType, AdherenceDay, ScheduleSegment
from apps.payroll import engine, services
from apps.payroll.models import DeductionType, PayConcept, Payroll, PayrollLine, PayrollSetting, Payslip, PayslipBatch
from apps.personnel_actions.models import ActionAttribute, ActionType, ActionValue, PersonnelAction
from apps.personnel_actions.services import validate
from apps.scheduling.models import AttendanceCutoff, NightRule, PayPeriod, ScheduleAssignment, TimeRecord, TimeRecordDay
from apps.system.models import AuditEvent

pytestmark = pytest.mark.django_db
P = "/api/v1/payroll"
DAY = {"days": {d: {"start": "08:00", "end": "17:00", "lunch_minutes": 60} for d in ("mon", "tue", "wed", "thu", "fri")}}
_FOLIO = iter(range(920001, 920999))
D = Decimal


# ================================================================== motor puro
def _rules(with_biweekly=True):
    monthly = (engine.Bracket(D("0"), D("550"), D("0"), D("0"), D("0")), engine.Bracket(D("550.01"), D("895.24"), D("0.10"), D("17.67"), D("550")),
               engine.Bracket(D("895.25"), D("2038.10"), D("0.20"), D("60"), D("895.24")), engine.Bracket(D("2038.11"), None, D("0.30"), D("288.57"), D("2038.10")))
    biweekly = (engine.Bracket(D("0"), D("275"), D("0"), D("0"), D("0")), engine.Bracket(D("275.01"), D("447.62"), D("0.10"), D("8.83"), D("275")),
                engine.Bracket(D("447.63"), D("1019.05"), D("0.20"), D("30"), D("447.62")), engine.Bracket(D("1019.06"), None, D("0.30"), D("144.28"), D("1019.05")))
    return [
        engine.LegalRule(1, "ISSS_EMP", "ISSS", "SOCIAL_SECURITY", "EMPLOYEE", "PERCENTAGE", rate=D("0.03"), base_cap=D("1000"), reduces_taxable_base=True, order=10),
        engine.LegalRule(2, "ISSS_PAT", "ISSS patronal", "SOCIAL_SECURITY", "EMPLOYER", "PERCENTAGE", rate=D("0.075"), base_cap=D("1000"), order=11),
        engine.LegalRule(3, "AFP_EMP", "AFP", "PENSION", "EMPLOYEE", "PERCENTAGE", rate=D("0.0725"), reduces_taxable_base=True, order=20),
        engine.LegalRule(4, "AFP_PAT", "AFP patronal", "PENSION", "EMPLOYER", "PERCENTAGE", rate=D("0.0875"), order=21),
        engine.LegalRule(5, "ISR_SV", "Renta", "INCOME_TAX", "EMPLOYEE", "BRACKET", order=90,
                         brackets=biweekly if with_biweekly else (), monthly_brackets=monthly),
    ]


def _concepts():
    return {c.code: engine.Concept(c.code, c.name, c.kind, c.source, c.affects_social_security, c.affects_income_tax, c.calculation, c.display_order)
            for c in PayConcept.objects.all()}


H = 3600


def test_engine_salvadoran_rules():
    """Fase 21: el motor es 100 % por horas (rate = salario del periodo ÷ horas programadas)."""
    inp = engine.EmployeeInput(monthly_salary=D("850"), frequency="BIWEEKLY", period_calendar_days=15, employed_calendar_days=15,
                               scheduled_seconds=80 * H, paid_seconds=80 * H)
    r = engine.calculate(inp, engine.Params(), _rules(), _concepts())
    amounts = {ln.code: ln.amount for ln in r.lines}
    assert (r.period_salary, r.gross_pay, r.hourly_rate) == (D("425.00"), D("425.00"), D("5.3125"))
    assert (amounts["ISSS_EMP"], amounts["AFP_EMP"]) == (D("12.75"), D("30.81"))
    assert r.taxable_base == D("381.44") and amounts["ISR_SV"] == D("19.47")  # 8.83 + 10 % sobre el exceso de 275
    assert (r.total_deductions, r.net_pay) == (D("63.03"), D("361.97"))
    assert r.employer_contributions == amounts["ISSS_PAT"] + amounts["AFP_PAT"] == D("31.88") + D("37.19")
    # Sin tramos quincenales se proyecta la tabla mensual (la cuota fija mensual 17.67 / 2 = 8.835 redondea distinto).
    assert {ln.code: ln.amount for ln in engine.calculate(inp, engine.Params(), _rules(False), _concepts()).lines}["ISR_SV"] == D("19.48")
    # Tope del ISSS proporcional al periodo (1000 al mes → 500 en la quincena).
    rich = engine.calculate(engine.EmployeeInput(D("3000"), "BIWEEKLY", 15, 15, scheduled_seconds=80 * H, paid_seconds=80 * H),
                            engine.Params(), _rules(), _concepts())
    assert {ln.code: ln.amount for ln in rich.lines}["ISSS_EMP"] == D("15.00")
    # Ingreso a mitad de periodo (10 de 15 días): salario del periodo 300 entre 64 h programadas; las horas no laboradas
    # (dos ausencias) no se pagan. Séptimo día opcional: apagado por defecto, la cuenta lo activa.
    inp = engine.EmployeeInput(D("900"), "BIWEEKLY", 15, 10, scheduled_seconds=64 * H, paid_seconds=48 * H, night_seconds=2 * H,
                               night_surcharge_percent=D(25), absence_dates=[date(2026, 10, 6), date(2026, 10, 7)],
                               holidays=[engine.HolidayItem(date(2026, 10, 12), "Feriado", 8 * H, D(100))])
    r = engine.calculate(inp, engine.Params(), _rules(), _concepts())
    amounts = {ln.code: ln.amount for ln in r.lines}
    assert (r.period_salary, r.hourly_rate, amounts["SALARIO"]) == (D("300.00"), D("4.6875"), D("225.00"))
    assert (amounts["NOCTURNIDAD"], amounts["FERIADO"]) == (D("2.34"), D("37.50"))  # 25 % nocturno · feriado = pago doble
    assert "SEPTIMO_DIA" not in amounts and {ln.code: ln.quantity for ln in r.lines}["HORAS_NO_PAGADAS"] == D("16.0000")
    inp.seventh_day_penalty = True  # regla de la cuenta
    assert {ln.code: ln.amount for ln in engine.calculate(inp, engine.Params(), _rules(), _concepts()).lines}["SEPTIMO_DIA"] == D("-37.50")
    assert "SEPTIMO_DIA" in {ln.code for ln in engine.calculate(
        engine.EmployeeInput(D("900"), "BIWEEKLY", 15, 15, scheduled_seconds=80 * H, paid_seconds=72 * H, absence_dates=[date(2026, 10, 6)]),
        engine.Params(seventh_day_penalty=True), _rules(), _concepts()).lines}


# ================================================================== datos de prueba
def _employee(make_employee, cost_center, salary="900.00"):
    emp = make_employee("SV", hire_date=date(2026, 9, 1), base_salary=D(salary), pay_frequency="BIWEEKLY", cost_center=cost_center("SV-OPS"))
    ScheduleAssignment.objects.create(employee=emp, definition=DAY, effective_start_date=date(2026, 9, 1))
    return emp


def _payroll_ap(emp, type_code, values: dict, effective=date(2026, 10, 9), status="APPROVED") -> PersonnelAction:
    t = ActionType.objects.get(code=type_code)
    a = PersonnelAction.objects.create(folio=f"{t.folio_prefix}-2026-{next(_FOLIO)}", action_type=t, employee=emp, effective_date=effective,
                                       justification="Planilla", status="DRAFT", content_hash="0" * 64)
    for key, value in values.items():
        attr = ActionAttribute.objects.get(action_type=t, key=key)
        kw = {"value_decimal": D(str(value))} if attr.data_type == "DECIMAL" else {"value_text": str(value)}
        ActionValue.objects.create(action=a, attribute=attr, **kw)
    PersonnelAction.objects.filter(pk=a.pk).update(status=status)
    a.refresh_from_db()
    return a


def _segment(emp, code, d, h0, m0, h1, m1):
    return ScheduleSegment.objects.create(employee=emp, shift_date=d, activity=ActivityType.objects.get(code=code), origin="SYSTEM",
                                          is_locked=True, start_at=datetime(d.year, d.month, d.day, h0, m0), end_at=datetime(d.year, d.month, d.day, h1, m1))


def _seed_inputs(emp):
    """Una quincena con todo: ausencia, Lateness, tiempo no laborado, nocturnidad del Web Timer y 4 AP de pago."""
    _segment(emp, "UNJUSTIFIED_ABSENCE", date(2026, 10, 6), 8, 0, 12, 0)
    _segment(emp, "LATENESS", date(2026, 10, 7), 8, 0, 8, 30)
    AdherenceDay.objects.create(employee=emp, shift_date=date(2026, 10, 8), scheduled_seconds=32400, scheduled_paid_seconds=28800,
                                paid_valid_seconds=27000, out_of_adherence_seconds=2400, computed_at=timezone.now())
    rec = TimeRecord.objects.create(employee=emp, kind="INTERVAL", start_at=datetime(2026, 10, 9, 18, 0), end_at=datetime(2026, 10, 9, 20, 0),
                                    occurrence_date=date(2026, 10, 9), minutes=120, source="WEB_TIMER")
    TimeRecordDay.objects.create(record=rec, employee=emp, occurrence_date=date(2026, 10, 9), start_at=rec.start_at, end_at=rec.end_at,
                                 minutes=120, night_minutes=60, night_rule=NightRule.objects.filter(country_id=emp.country_id).first())
    return {
        "overtime": _payroll_ap(emp, "AP_HORAS_EXTRA", {"motivo": "Volumen de contactos", "horas_diurnas": 2, "horas_nocturnas": 1}),
        "bonus": _payroll_ap(emp, "AP_BONIFICACION", {"concepto": "Comisión", "monto": 50}),
        "vacation": _payroll_ap(emp, "AP_VACACIONES", {"dias": 15}, effective=date(2026, 10, 12)),
        "discount": _payroll_ap(emp, "AP_DESCUENTO", {"concepto": "Préstamo", "monto": 20}),
        "pending": _payroll_ap(emp, "AP_BONIFICACION", {"concepto": "Otro", "monto": 999}, status="PENDING"),
    }


def _worked(emp, d, h0, h1):
    """Tiempo del Web Timer en un día (sin franja nocturna)."""
    start, end = datetime(d.year, d.month, d.day, h0), datetime(d.year, d.month, d.day, h1)
    minutes = (h1 - h0) * 60
    rec = TimeRecord.objects.create(employee=emp, kind="INTERVAL", start_at=start, end_at=end, occurrence_date=d, minutes=minutes,
                                    source="WEB_TIMER")
    TimeRecordDay.objects.create(record=rec, employee=emp, occurrence_date=d, start_at=start, end_at=end, minutes=minutes)


def _period(code="2026-10-Q1"):
    return PayPeriod.objects.get(cycle__code="SV_QUINCENAL", code=code)


def _close_cutoffs(period):
    AttendanceCutoff.objects.filter(pay_period=period).update(status="CLOSED", closed_at=timezone.now())


def _approved(emp):
    period = _period()
    _close_cutoffs(period)
    run = services.calculate(period)
    services.approve(run)
    return run


# ================================================================== 1. motor con insumos reales
def test_payroll_from_web_timer_aps_segments_and_adherence(api, hr_user, make_employee, cost_center):
    emp = _employee(make_employee, cost_center)
    aps = _seed_inputs(emp)
    for d in (date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)):
        _worked(emp, d, 8, 17)  # 9 h de sesión; se paga hasta lo programado (8 h netas)
    _worked(emp, date(2026, 10, 7), 9, 16)  # llegó tarde (Lateness): 7 h con sesión
    period = _period()
    api.force_login(hr_user)
    periods = api.get(f"{P}/periods/", {"year": 2026}).json()["results"]
    assert any(p["id"] == period.pk and p["run"] is None for p in periods)
    r = api.post(f"{P}/runs/", {"period_id": period.pk}, format="json")
    assert r.status_code == 201, r.json()
    run = r.json()["run"]
    assert (run["status"], run["code"], run["employees"]) == ("CALCULATED", "SV_QUINCENAL-2026-10-Q1", 1)
    b = api.get(f"{P}/runs/{run['id']}/employees/{emp.employee_code}/").json()
    lines = {ln["code"]: ln for ln in b["lines"]}
    amount = lambda code: D(str(lines[code]["amount"]))  # noqa: E731
    qty = lambda code: D(str(lines[code]["quantity"]))  # noqa: E731
    # Fase 21 — por horas: 11 días hábiles × 8 h = 88 h programadas; rate = 450 ÷ 88. Pagables: 3 días completos (24 h),
    # el día con Lateness (7 h), el de la adherencia guardada (7.5 h) y 2 h del Web Timer el viernes = 40.5 h; más 32 h
    # programadas de vacaciones (12–15 de octubre). La ausencia del 6 no se paga (sin descuentos por días).
    assert (qty("HORAS_PROGRAMADAS"), qty("HORAS_PAGADAS"), qty("HORAS_NO_PAGADAS")) == (D("88"), D("72.5"), D("15.5"))
    assert D(str(lines["SALARIO"]["rate"])) == D("5.1136")  # rate redondeado a 4 decimales (el monto usa el exacto)
    assert (amount("SALARIO"), amount("VACACIONES_GOCE")) == (D("207.10"), D("163.64"))
    assert amount("NOCTURNIDAD") == D("1.28")  # 1 h nocturna × 25 % × rate
    assert (amount("HORAS_EXTRA_DIURNAS"), amount("HORAS_EXTRA_NOCTURNAS")) == (D("20.45"), D("12.78"))
    assert (amount("BONIFICACION"), amount("PRIMA_VACACIONES")) == (D("50.00"), D("135.00"))
    assert "SEPTIMO_DIA" not in lines  # opcional: apagado por defecto
    assert lines["BONIFICACION"]["folio_ap"] == aps["bonus"].folio and "WEB_TIMER_HORAS" in lines and "OUT_OF_ADHERENCE" in lines
    assert not any(ln["folio_ap"] == aps["pending"].folio for ln in b["lines"])  # solo AP aprobadas
    d = b["detail"]
    assert D(str(d["gross_pay"])) == D("590.25")
    assert (amount("ISSS_EMP"), amount("AFP_EMP"), amount("ISR_SV")) == (D("15.00"), D("42.79"), D("46.97"))
    assert amount("DESCUENTO_AP") == D("20.00")
    assert (D(str(d["total_deductions"])), D(str(d["net_pay"]))) == (D("124.76"), D("465.49"))
    assert D(str(d["paid_days"])) == D("9.06") and d["worked_minutes"] == 4350
    # El resultado vive en fin.* (vista para reportería).
    with connection.cursor() as cursor:
        cursor.execute("SELECT GrossPay, IsssEmployee, AfpEmployee, IncomeTax, NetPay FROM dbo.vw_PayPayrollDetail WHERE EmployeeId = %s",
                       [emp.employee_code])
        assert cursor.fetchone() == (D("590.25"), D("15.00"), D("42.79"), D("46.97"), D("465.49"))
    # Recalcular es idempotente.
    assert api.post(f"{P}/runs/{run['id']}/recalculate/").status_code == 200
    assert PayrollLine.objects.filter(personnel_action=aps["bonus"]).count() == 1
    # Cerrar exige los cortes cerrados y un cálculo posterior a su cierre.
    r = api.post(f"{P}/runs/{run['id']}/approve/")
    assert r.status_code == 409 and r.json()["code"] == "cutoffs_open"
    for c in AttendanceCutoff.objects.filter(pay_period=period):
        assert api.post(f"/api/v1/scheduling/cutoffs/{c.pk}/close/").status_code == 200
    r = api.post(f"{P}/runs/{run['id']}/approve/")
    assert r.status_code == 409 and r.json()["code"] == "stale"
    api.post(f"{P}/runs/{run['id']}/recalculate/")
    r = api.post(f"{P}/runs/{run['id']}/approve/")
    assert r.status_code == 200, r.json()
    assert r.json()["run"]["status"] == "APPROVED" and r.json()["run"]["payslips"]["total"] == 1
    slip = Payslip.objects.get(employee=emp)
    assert slip.folio == "BOL-SV_QUINCENAL-2026-10-Q1-00001" and slip.net_pay == D("465.49")
    assert slip.batch.code == "LOTE-SV_QUINCENAL-2026-10-Q1-SV-OPS" and slip.content["totals"]["net"] == "465.49"
    assert slip.content_hash == services.content_hash(slip.content)
    assert api.post(f"{P}/runs/{run['id']}/recalculate/").json()["code"] == "closed"
    assert api.post(f"{P}/runs/{run['id']}/cancel/", {"reason": "x"}, format="json").json()["code"] == "closed"
    # Las AP ya pagadas no se vuelven a pagar en la planilla siguiente.
    nxt = services.calculate(_period("2026-10-Q2"))
    assert not PayrollLine.objects.filter(payroll=nxt.payroll, personnel_action__isnull=False).exists()
    assert api.post(f"{P}/runs/{run['id']}/pay/").json()["run"]["status"] == "PAID"
    assert AuditEvent.objects.filter(category="PAYROLL", action__in=["payroll_calculated", "payroll_approved", "payroll_paid"]).count() >= 4


def test_cancel_frees_aps_and_permissions(api, hr_user, wfm_user, employee_user, make_employee, cost_center):
    emp = _employee(make_employee, cost_center)
    bonus = _payroll_ap(emp, "AP_BONIFICACION", {"concepto": "Comisión", "monto": 50})
    run = services.calculate(_period())
    api.force_login(hr_user)
    assert api.post(f"{P}/runs/{run.pk}/cancel/", {}, format="json").status_code == 400
    r = api.post(f"{P}/runs/{run.pk}/cancel/", {"reason": "Error de insumos"}, format="json")
    assert r.status_code == 200 and r.json()["run"]["status"] == "CANCELLED"
    assert not PayrollLine.objects.filter(personnel_action=bonus).exists()
    run = services.calculate(_period())  # una planilla anulada se puede volver a calcular
    assert run.payroll.payroll_status == "CALCULATED" and PayrollLine.objects.filter(personnel_action=bonus).count() == 1
    # La BPO no es el ciclo predeterminado: no se calcula.
    bpo = PayPeriod.objects.filter(cycle__code="SV_QUINCENAL_BPO").first()
    assert api.post(f"{P}/runs/", {"period_id": bpo.pk}, format="json").json()["code"] == "cycle_not_default"
    # Planillas e inventario: solo RRHH / Administración.
    for user in (wfm_user, employee_user):
        api.force_login(user)
        assert api.get(f"{P}/runs/").status_code == 403
        assert api.get(f"{P}/payslips/").status_code == 403


# ================================================================== 2. SQL Server (una violación por prueba)
def test_sql_locks_closed_payroll_detail(make_employee, cost_center):
    emp = _employee(make_employee, cost_center)
    run = _approved(emp)
    with pytest.raises(DatabaseError, match="50090"), connection.cursor() as cursor:
        cursor.execute("UPDATE fin.PayrollDetail SET OtherEarnings = OtherEarnings + 1 WHERE PayrollId = %s", [run.payroll_id])


def test_sql_payroll_status_only_moves_forward(make_employee, cost_center):
    run = _approved(_employee(make_employee, cost_center))
    with pytest.raises(DatabaseError, match="50091"), connection.cursor() as cursor:
        cursor.execute("UPDATE fin.Payroll SET PayrollStatus = N'CALCULATED' WHERE PayrollId = %s", [run.payroll_id])


def test_sql_payslip_is_not_deleted(make_employee, cost_center):
    run = _approved(_employee(make_employee, cost_center))
    with pytest.raises(DatabaseError, match="50092"), connection.cursor() as cursor:
        cursor.execute("DELETE FROM dbo.pay_payslip WHERE payroll_id = %s", [run.payroll_id])


def test_sql_payslip_content_is_frozen(make_employee, cost_center):
    run = _approved(_employee(make_employee, cost_center))
    with pytest.raises(DatabaseError, match="50092"), connection.cursor() as cursor:
        cursor.execute("UPDATE dbo.pay_payslip SET net_pay = net_pay + 1, gross_pay = gross_pay + 1 WHERE payroll_id = %s", [run.payroll_id])


def test_sql_line_requires_approved_payroll_ap(make_employee, cost_center):
    emp = _employee(make_employee, cost_center)
    run = services.calculate(_period())
    pending = _payroll_ap(emp, "AP_BONIFICACION", {"concepto": "Otro", "monto": 5}, status="PENDING")
    detail = run.payroll.details.get()
    with pytest.raises(DatabaseError, match="50093"):
        PayrollLine.objects.create(payroll=run.payroll, detail=detail, employee=emp, kind="EARNING", code="BONIFICACION", label="x",
                                   amount=D("5"), personnel_action=pending)


# ================================================================== 3. inventario de boletas físicas
def test_payslip_inventory_print_sign_archive_and_filters(api, hr_user, make_employee, cost_center):
    emps = [_employee(make_employee, cost_center), _employee(make_employee, cost_center, "1200.00")]
    emps[1].cost_center = cost_center("SV-ADM")
    emps[1].save()
    run = _approved(emps[0])
    api.force_login(hr_user)
    inv = api.get(f"{P}/payslips/", {"year": 2026, "month": 10}).json()
    assert inv["count"] == 2 and inv["summary"] == {"total": 2, "printed": 0, "missing_print": 2, "signed": 0, "pending_signature": 2,
                                                    "archived": 0, "not_archived": 2}
    batches = api.get(f"{P}/batches/", {"year": 2026}).json()["results"]
    assert {b["cost_center"] for b in batches} == {"SV-OPS", "SV-ADM"} and all(b["status"] == "PENDING" for b in batches)
    ids = [row["id"] for row in inv["results"]]
    ops = next(row for row in inv["results"] if row["cost_center"] == "SV-OPS")
    # Firmar o archivar antes de imprimir: se omite.
    r = api.post(f"{P}/payslips/actions/", {"ids": ids, "action": "SIGN"}, format="json").json()
    assert r["changed"] == 0 and len(r["skipped"]) == 2
    printed = api.get(f"{P}/payslips/print/", {"ids": ",".join(map(str, ids))}).json()["results"]
    assert len(printed) == 2 and printed[0]["content"]["totals"]["net"]
    assert api.post(f"{P}/payslips/actions/", {"ids": ids, "action": "PRINT"}, format="json").json()["changed"] == 2
    assert api.post(f"{P}/payslips/actions/", {"ids": [ops["id"]], "action": "PRINT"}, format="json").json()["changed"] == 1  # reimpresión
    assert api.post(f"{P}/payslips/actions/", {"ids": [ops["id"]], "action": "SIGN", "signed_on": "2099-01-01"}, format="json").status_code == 400
    today = timezone.localdate().isoformat()
    assert api.post(f"{P}/payslips/actions/", {"ids": [ops["id"]], "action": "SIGN", "signed_on": today}, format="json").json()["changed"] == 1
    r = api.post(f"{P}/payslips/actions/", {"ids": [ops["id"]], "action": "ARCHIVE", "location": "Caja 12 / Ampo OPS"}, format="json")
    assert r.json()["changed"] == 1
    s = Payslip.objects.get(pk=ops["id"])
    assert (s.print_count, s.signed_on.isoformat(), s.archive_location) == (2, today, "Caja 12 / Ampo OPS")
    # Filtros: departamento, firma, impresión y archivo.
    get = lambda **kw: api.get(f"{P}/payslips/", {"year": 2026, **kw}).json()  # noqa: E731
    assert [x["folio"] for x in get(signature="SIGNED")["results"]] == [ops["folio"]]
    assert get(signature="PENDING")["count"] == 1 and get(cost_center="SV-ADM")["count"] == 1
    assert get(printed="MISSING")["count"] == 0 and get(archived="ARCHIVED")["count"] == 1
    assert get(signature="PENDING")["summary"]["signed"] == 1  # los contadores muestran el avance de todo el alcance
    assert get(payroll=run.payroll.payroll_code)["count"] == 2 and get(month=11)["count"] == 0
    batch = next(b for b in api.get(f"{P}/batches/").json()["results"] if b["cost_center"] == "SV-OPS")
    assert batch["status"] == "ARCHIVED" and batch["counts"]["archived"] == 1
    assert api.patch(f"{P}/batches/{batch['id']}/", {"archive_location": "Estante B"}, format="json").status_code == 200
    # Revertir exige motivo; no se quita la firma de una boleta archivada.
    assert api.post(f"{P}/payslips/actions/", {"ids": [ops["id"]], "action": "UNSIGN"}, format="json").status_code == 400
    r = api.post(f"{P}/payslips/actions/", {"ids": [ops["id"]], "action": "UNSIGN", "reason": "Firma ilegible"}, format="json").json()
    assert r["changed"] == 0 and "archivada" in r["skipped"][0]
    detail = api.get(f"{P}/payslips/{ops['id']}/").json()
    assert detail["verified"] is True and detail["content"]["employee"]["code"] == emps[0].employee_code
    with connection.cursor() as cursor:
        cursor.execute("SELECT PrintStatus, SignatureStatus, IsArchived, Department FROM dbo.vw_PayPayslipInventory WHERE Folio = %s", [ops["folio"]])
        assert cursor.fetchone() == ("Impresa", "Firmada en físico", True, cost_center("SV-OPS").name)
    assert AuditEvent.objects.filter(action__in=["payslip_print", "payslip_sign", "payslip_archive"]).count() == 4


# ================================================================== 4. parámetros, vigencias y AP de pago
def test_settings_versions_and_payroll_ap_validation(api, hr_user, make_employee, cost_center):
    api.force_login(hr_user)
    data = api.get(f"{P}/settings/").json()
    sv = next(s for s in data["settings"] if s["name"].startswith("El Salvador"))
    assert {c["code"] for c in data["concepts"]} >= {"SALARIO", "AUSENCIA", "LATENESS", "HORAS_EXTRA_DIURNAS", "DESCUENTO_AP"}
    assert {t["code"] for t in data["deduction_types"]} >= {"ISSS_EMP", "AFP_EMP", "ISR_SV", "INSAFORP_PAT"} and data["night_rules"]
    r = api.patch(f"{P}/settings/{sv['id']}/", {"seventh_day_penalty": False}, format="json")
    assert r.status_code == 200 and r.json()["setting"]["seventh_day_penalty"] is False
    assert api.patch(f"{P}/settings/{sv['id']}/", {"days_per_month": 45}, format="json").status_code == 400
    # Una vigencia que respaldó una planilla cerrada ya no se edita: se crea otra.
    _approved(_employee(make_employee, cost_center))
    assert api.patch(f"{P}/settings/{sv['id']}/", {"deduct_lateness": False}, format="json").json()["code"] == "in_use"
    r = api.post(f"{P}/settings/", {"country": sv["country"], "effective_start_date": "2027-01-01", "name": "SV 2027",
                                    "overtime_surcharge_percent": "150"}, format="json")
    assert r.status_code == 201, r.json()
    assert PayrollSetting.objects.get(pk=sv["id"]).effective_end_date == date(2026, 12, 31)
    assert services.setting_for(sv["country"], date(2027, 3, 1)).overtime_surcharge_percent == D("150")
    # Nueva vigencia del ISSS: la anterior se cierra el día previo y el motor usa la nueva desde su fecha.
    isss = DeductionType.objects.get(code="ISSS_EMP", effective_start_date=date(2026, 1, 1))
    r = api.post(f"{P}/deduction-types/{isss.pk}/versions/", {"effective_start_date": "2027-01-01", "rate": "0.035"}, format="json")
    assert r.status_code == 201, r.json()
    assert DeductionType.objects.get(pk=isss.pk).effective_end_date == date(2026, 12, 31)
    assert next(t for t in services.legal_types(sv["country"], date(2027, 2, 1)) if t.code == "ISSS_EMP").rate == D("0.035")
    assert api.patch(f"{P}/concepts/BONIFICACION/", {"affects_income_tax": False}, format="json").json()["concept"]["affects_income_tax"] is False
    # AP de pago: monto obligatorio y aviso si la planilla de esa fecha ya está cerrada.
    emp = _employee(make_employee, cost_center)
    t = ActionType.objects.get(code="AP_BONIFICACION")
    check = validate(t, emp, {"effective_date": "2026-10-09", "justification": "x", "values": {"concepto": "Comisión", "monto": "0"}})
    assert not check.ok
    check = validate(t, emp, {"effective_date": "2026-10-09", "justification": "x", "values": {"concepto": "Comisión", "monto": "10"}})
    assert check.ok and any(w["code"] == "payroll_closed" for w in check.warnings)


def test_management_command_calculates_and_closes(make_employee, cost_center, capsys):
    emp = _employee(make_employee, cost_center)
    _close_cutoffs(_period())
    call_command("payroll_calculate", "--cycle", "SV_QUINCENAL", "--date", "2026-10-09", "--approve")
    out = capsys.readouterr().out
    assert "SV_QUINCENAL-2026-10-Q1" in out and "1 boletas" in out
    assert Payroll.objects.get(payroll_code="SV_QUINCENAL-2026-10-Q1").payroll_status == "APPROVED"
    assert Payslip.objects.filter(employee=emp).count() == 1 and PayslipBatch.objects.count() == 1
