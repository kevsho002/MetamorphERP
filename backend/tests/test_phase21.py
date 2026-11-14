"""Fase 21: ciclo de vida (suspensión, terminación, reingreso con alerta de recontratación), control de AP por roles,
motor de planilla por horas con pre-cierre (corridas, boletas preliminares, excepciones), séptimo opcional por cuenta,
calendario de feriados con Holiday Segments y liquidaciones / indemnizaciones con lotes de pago."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from django.db import DatabaseError, connection
from django.utils import timezone

from apps.adherence.models import ScheduleSegment
from apps.hcm.models import Employee
from apps.holidays.models import Holiday, HolidaySegment
from apps.payroll import portal, services, settlements
from apps.payroll.models import PayrollException, PayrollIteration, Settlement, SettlementBatch
from apps.personnel_actions import lifecycle
from apps.personnel_actions.models import ActionType, EmploymentEvent
from apps.scheduling.models import AttendanceCutoff, PayPeriod, ScheduleAssignment, TimeRecord, TimeRecordDay
from apps.system.models import AuditEvent

pytestmark = pytest.mark.django_db
PA = "/api/v1/personnel-actions"
P = "/api/v1/payroll"
D = Decimal
DAY = {"days": {d: {"start": "08:00", "end": "17:00", "lunch_minutes": 60} for d in ("mon", "tue", "wed", "thu", "fri")}}


def _ap(api, user, type_code, employee, effective, values, **extra):
    api.force_login(user)
    return api.post(f"{PA}/", {"action_type": type_code, "employee_code": employee.employee_code, "effective_date": effective.isoformat(),
                               "justification": "Fase 21", "values": values, "submit": True, **extra}, format="json")


def _sign(api, user, folio):
    api.force_login(user)
    return api.post(f"{PA}/{folio}/sign/", {"decision": "APPROVED", "comment": "OK"}, format="json")


# ================================================================== ciclo de vida
def test_suspension_freezes_tenure_and_reactivates(api, hr_user, admin_user, make_employee):
    today = timezone.localdate()
    emp = make_employee("SV", hire_date=date(2026, 3, 1))
    r = _ap(api, hr_user, "AP_SUSPENSION", emp, today - timedelta(days=2), {"dias": 5, "falta": "Reincidencia"})
    assert r.status_code == 201, r.json()
    folio = r.json()["action"]["folio"]
    assert r.json()["action"]["status"] == "PENDING"  # el generalista firmó el paso 1; falta Administración
    assert _sign(api, admin_user, folio).json()["action"]["status"] == "APPROVED"
    emp.refresh_from_db()
    assert emp.employment_status == Employee.Status.INACTIVE
    t = lifecycle.tenure(emp, today)
    assert t["frozen"] and t["suspended_days"] == 3 and t["days"] == t["calendar_days"] - 3
    # Una segunda suspensión que se cruza se rechaza.
    r = _ap(api, hr_user, "AP_SUSPENSION", emp, today, {"dias": 2, "falta": "Otra"})
    assert r.status_code == 400 and any(e["code"] == "overlap" for e in r.json()["errors"])
    # Al terminar la suspensión, la tarea diaria lo reactiva y la antigüedad vuelve a correr (sin los 5 días).
    out = lifecycle.sync_statuses(today + timedelta(days=3))
    emp.refresh_from_db()
    assert emp.employee_code in out["reactivated"] and emp.employment_status == Employee.Status.ACTIVE
    later = lifecycle.tenure(emp, today + timedelta(days=10))
    assert later["suspended_days"] == 5 and not later["frozen"]
    with pytest.raises(DatabaseError, match="50094"), connection.cursor() as cursor:
        cursor.execute("DELETE FROM pa.pa_employment_event WHERE employee_id = %s", [emp.pk])


def test_termination_rehire_alert_and_tenure_restart(api, hr_user, admin_user, wfm_user, make_employee):
    today = timezone.localdate()
    emp = make_employee("SV", hire_date=date(2026, 3, 1), base_salary=D("1000.00"))
    r = _ap(api, hr_user, "AP_TERMINACION", emp, today - timedelta(days=10),
            {"motivo_terminacion": "DESPIDO_CON_CAUSA", "recomendable_recontratacion": False, "observaciones_rrhh": "Faltas graves"})
    assert r.status_code == 201, r.json()
    assert any(w["code"] == "not_rehirable" for w in r.json()["warnings"])
    assert _sign(api, admin_user, r.json()["action"]["folio"]).json()["action"]["status"] == "APPROVED"
    emp.refresh_from_db()
    assert (emp.employment_status, emp.termination_date) == ("TERMINATED", today - timedelta(days=10))
    assert Settlement.objects.filter(employee=emp, status="CALCULATED").exists()  # la liquidación se abre sola
    # El indicador de recontratación solo lo ve RRHH (WFM ve el ciclo de vida sin él).
    api.force_login(wfm_user)
    body = api.get(f"{PA}/employees/{emp.employee_code}/lifecycle/").json()
    assert "rehire_eligible" not in body and all("rehire_eligible" not in h for h in body["history"])
    api.force_login(hr_user)
    body = api.get(f"{PA}/employees/{emp.employee_code}/lifecycle/").json()
    assert body["rehire_eligible"] is False and body["rehire_alert"]["code"] == "rehire_not_recommended"
    # Reingreso de un NO recomendado: alerta formal con historial; exige reconocerla para continuar.
    values = {"new_base_salary": "1100", "motivo": "Campaña nueva"}
    r = _ap(api, hr_user, "AP_REINGRESO", emp, today, values)
    assert r.status_code == 400 and any(e["code"] == "ack_required" for e in r.json()["errors"])
    alert = next(w for w in r.json()["warnings"] if w["code"] == "rehire_not_recommended")
    assert alert["history"] and "NO recomendable" in " ".join(alert["details"])
    r = _ap(api, hr_user, "AP_REINGRESO", emp, today, values, acknowledge=["rehire_not_recommended"])
    assert r.status_code == 201, r.json()
    assert r.json()["action"]["status"] == "APPROVED"  # un solo paso (RRHH), firmado al enviarla
    emp.refresh_from_db()
    assert (emp.employment_status, emp.hire_date, emp.termination_date, emp.base_salary) == ("ACTIVE", today, None, D("1100.00"))
    assert lifecycle.tenure(emp, today)["days"] == 1  # la antigüedad se reinicia
    assert AuditEvent.objects.filter(action="rehire_alert_acknowledged").exists()
    ev = EmploymentEvent.objects.get(employee=emp, kind="REHIRE")
    assert ev.previous_hire_date == date(2026, 3, 1) and ev.rehire_acknowledged


def test_ap_role_control_is_strict(api, hr_user, admin_user, wfm_user, make_employee):
    emp = make_employee("SV")
    api.force_login(wfm_user)
    assert api.patch(f"{PA}/role-matrix/AP_SUSPENSION/", {"creator_roles": ["WFM"]}, format="json").status_code == 403
    api.force_login(admin_user)
    m = api.get(f"{PA}/role-matrix/").json()
    assert m["can_edit"] and set(next(t for t in m["results"] if t["code"] == "AP_SUSPENSION")["creator_roles"]) == {"ADMIN", "HR"}
    r = api.patch(f"{PA}/role-matrix/AP_SUSPENSION/", {"creator_roles": ["ADMIN"], "admin_signs_any_step": False}, format="json")
    assert r.status_code == 200
    # El generalista ya no la elabora.
    r = _ap(api, hr_user, "AP_SUSPENSION", emp, timezone.localdate() + timedelta(days=5), {"dias": 1, "falta": "Otra"})
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "forbidden"
    # Firma estricta: el Administrador elabora pero no firma el paso de RRHH.
    r = _ap(api, admin_user, "AP_SUSPENSION", emp, timezone.localdate() + timedelta(days=5), {"dias": 1, "falta": "Otra"})
    folio = r.json()["action"]["folio"]
    assert r.json()["action"]["status"] == "PENDING" and r.json()["action"]["steps_signed"] == 0
    assert _sign(api, admin_user, folio).status_code == 400
    assert _sign(api, hr_user, folio).status_code == 200
    assert ActionType.objects.get(code="AP_SUSPENSION").creator_roles == ["ADMIN"]


# ================================================================== feriados y Holiday Segments
def _biweekly(make_employee, **kw):
    emp = make_employee("SV", hire_date=date(2026, 9, 1), base_salary=D("900.00"), pay_frequency="BIWEEKLY", **kw)
    ScheduleAssignment.objects.create(employee=emp, definition=DAY, effective_start_date=date(2026, 9, 1))
    return emp


def _worked(emp, d, h0, h1):
    start, end = datetime(d.year, d.month, d.day, h0), datetime(d.year, d.month, d.day, h1)
    rec = TimeRecord.objects.create(employee=emp, kind="INTERVAL", start_at=start, end_at=end, occurrence_date=d,
                                    minutes=(h1 - h0) * 60, source="WEB_TIMER")
    TimeRecordDay.objects.create(record=rec, employee=emp, occurrence_date=d, start_at=start, end_at=end, minutes=(h1 - h0) * 60)


def test_holiday_segments_double_pay_without_absences(api, hr_user, wfm_user, make_employee):
    from apps.adherence.attendance import reconcile

    emp = _biweekly(make_employee)
    sv = emp.country_id
    hol = Holiday.objects.create(country_id=sv, date=date(2026, 10, 7), name="Asueto de prueba", kind="COMPANY", premium_percent=100)
    # Sin sesión en el feriado: la conciliación NO marca Unjustified Absence ni Lateness.
    out = reconcile([emp], date(2026, 10, 7))
    assert out["holiday"] == 1 and out["absences"] == 0
    assert not ScheduleSegment.objects.filter(employee=emp, shift_date=date(2026, 10, 7)).exists()
    # Laboró el feriado: se genera el contenedor Holiday Segment y la planilla paga el recargo (pago doble).
    _worked(emp, date(2026, 10, 7), 8, 17)
    run = services.calculate(PayPeriod.objects.get(cycle__code="SV_QUINCENAL", code="2026-10-Q1"))
    seg = HolidaySegment.objects.get(employee=emp, holiday=hol)
    assert (seg.worked_seconds, seg.scheduled_seconds) == (9 * 3600, 8 * 3600)
    lines = {ln["code"]: ln for ln in services.employee_breakdown(run, emp.employee_code)["lines"]}
    rate = D("450") / D("88")
    assert D(str(lines["FERIADO"]["amount"])) == (rate * 8).quantize(D("0.01"))  # 8 h pagables × 100 %
    assert D(str(lines["SALARIO"]["quantity"])) == D("8")  # además se pagan como horas regulares
    # API: lectura para WFM; altas, cambios y bajas solo con planillas.
    api.force_login(wfm_user)
    assert api.get("/api/v1/holidays/", {"year": 2026, "country": "SV"}).status_code == 200
    assert api.post("/api/v1/holidays/", {"country": "SV", "date": "2026-12-31", "name": "x"}, format="json").status_code == 403
    api.force_login(hr_user)
    body = api.get("/api/v1/holidays/", {"year": 2026, "country": "SV"}).json()
    assert any(h["name"] == "Navidad" for h in body["results"])  # feriados legales sembrados
    assert api.delete(f"/api/v1/holidays/{hol.pk}/").status_code == 409  # ya generó Holiday Segments
    with pytest.raises(DatabaseError, match="50097"), connection.cursor() as cursor:
        cursor.execute("UPDATE wfm.hol_holiday SET date = '2026-10-08' WHERE id = %s", [hol.pk])


# ================================================================== pre-cierre: corridas, boletas preliminares y excepciones
def test_preliminary_payslips_exceptions_and_freeze(api, hr_user, make_user, make_employee):
    emp = _biweekly(make_employee)
    agent = make_user("agente.p21", "EMPLOYEE", employee=emp)
    period = PayPeriod.objects.get(cycle__code="SV_QUINCENAL", code="2026-10-Q1")
    _worked(emp, date(2026, 10, 1), 8, 17)
    run = services.calculate(period)
    run = services.calculate(period, trigger=PayrollIteration.Trigger.SCHEDULED)
    assert run.iterations == 2 and run.preliminary_published_at is not None
    assert list(PayrollIteration.objects.filter(run=run).values_list("number", "trigger")) == [(2, "SCHEDULED"), (1, "MANUAL")]
    api.force_login(agent)
    mine = api.get(f"{P}/me/payslips/").json()
    assert mine["preliminary"][0]["preliminary"] and mine["preliminary"][0]["employee"]["code"] == emp.employee_code
    r = api.post(f"{P}/exceptions/", {"payroll_id": run.payroll_id, "category": "HOURS", "work_date": "2026-10-02",
                                     "description": "Trabajé el 2 de octubre y no aparece."}, format="json")
    assert r.status_code == 201
    x = PayrollException.objects.get()
    assert api.post(f"{P}/exceptions/{x.pk}/resolve/", {"status": "RESOLVED", "response": "x"}, format="json").status_code == 403
    assert api.get(f"{P}/runs/").status_code == 403  # el agente solo ve su portal
    # Freeze: no se cierra con excepciones abiertas.
    AttendanceCutoff.objects.filter(pay_period=period).update(status="CLOSED", closed_at=timezone.now() - timedelta(minutes=5))
    run = services.calculate(period)
    api.force_login(hr_user)
    r = api.post(f"{P}/runs/{run.pk}/approve/")
    assert r.status_code == 409 and r.json()["code"] == "open_exceptions"
    assert api.get(f"{P}/exceptions/", {"status": "OPEN"}).json()["open"] == 1
    its = api.get(f"{P}/runs/{run.pk}/iterations/").json()["results"]
    assert [i["number"] for i in its] == [3, 2, 1] and its[0]["open_exceptions"] == 1
    r = api.post(f"{P}/exceptions/{x.pk}/resolve/", {"status": "RESOLVED", "response": "Se agregó el registro."}, format="json")
    assert r.status_code == 200
    assert api.post(f"{P}/runs/{run.pk}/approve/").status_code == 200
    api.force_login(agent)
    mine = api.get(f"{P}/me/payslips/").json()
    assert not mine["preliminary"] and mine["final"][0]["folio"].startswith("BOL-")
    # Corridas diarias automáticas: solo periodos abiertos dentro de la anticipación configurada.
    assert period not in portal.due_periods(date(2026, 10, 10))


def test_account_rule_controls_seventh_day(api, hr_user, make_employee):
    from apps.operations.models import Client
    from apps.roster.models import RosterAssignment, RosterAttribute

    client = Client.objects.create(code="ACME_P21", name="Acme Fase 21")
    emp = _biweekly(make_employee)
    attr = RosterAttribute.objects.get(code="client")
    RosterAssignment.objects.create(employee=emp, attribute=attr, value=client.code, effective_start=date(2026, 9, 1))
    api.force_login(hr_user)
    assert api.patch(f"{P}/account-rules/{client.pk}/", {"seventh_day_penalty": True}, format="json").status_code == 200
    assert services.account_rules([emp.pk], date(2026, 10, 15)) == {emp.pk: (True, "Acme Fase 21")}


# ================================================================== liquidaciones e indemnizaciones
def test_settlement_dismissal_batch_and_checks(api, hr_user, make_employee):
    emp = make_employee("SV", hire_date=date(2024, 1, 15), base_salary=D("1200.00"))
    Employee.objects.filter(pk=emp.pk).update(employment_status="TERMINATED", termination_date=date(2026, 11, 10))
    emp.refresh_from_db()
    api.force_login(hr_user)
    pending = api.get(f"{P}/settlements/").json()["pending_terminations"]
    assert any(p["employee_code"] == emp.employee_code for p in pending)
    r = api.post(f"{P}/settlements/", {"employee_code": emp.employee_code, "reason": "DESPIDO_SIN_CAUSA"}, format="json")
    assert r.status_code == 201, r.json()
    s = r.json()["settlement"]
    lines = {ln["code"]: ln for ln in s["lines"]}
    years = D(s["service_days"]) / D(365)
    assert D(str(lines["INDEMNIZACION"]["amount"])) == (D("1200") / 30 * 30 * years).quantize(D("0.01"))  # 30 días por año
    assert {"VACACION_PROPORCIONAL", "AGUINALDO_PROPORCIONAL"} <= set(lines)
    assert "ISSS_EMP" in lines  # las vacaciones cotizan; la indemnización no
    sid = s["id"]
    r = api.post(f"{P}/settlements/{sid}/lines/", {"kind": "DEDUCTION", "label": "Saldo de préstamo", "amount": "50"}, format="json")
    assert r.status_code == 200 and D(str(r.json()["settlement"]["deductions"])) > D("50")
    assert api.post(f"{P}/settlements/{sid}/approve/").json()["settlement"]["status"] == "APPROVED"
    st = Settlement.objects.get(pk=sid)
    assert st.content_hash and st.content["net_in_words"].endswith("DÓLARES DE LOS ESTADOS UNIDOS DE AMÉRICA")
    assert api.post(f"{P}/settlements/{sid}/lines/", {"kind": "EARNING", "label": "x", "amount": "1"}, format="json").status_code == 409
    # Lote de pago por cheque: números correlativos, cierre, pago.
    r = api.post(f"{P}/settlement-batches/", {"country": "SV", "payment_date": "2026-11-20", "method": "CHECK", "first_check": "1001",
                                              "settlements": [sid]}, format="json")
    assert r.status_code == 201, r.json()
    b = r.json()["batch"]
    assert b["settlements"][0]["check_number"] == "1001"
    assert api.post(f"{P}/settlement-batches/{b['id']}/pay/").status_code == 409  # primero se cierra
    assert api.post(f"{P}/settlement-batches/{b['id']}/close/").json()["batch"]["status"] == "CLOSED"
    assert api.post(f"{P}/settlement-batches/{b['id']}/pay/").json()["batch"]["status"] == "PAID"
    assert Settlement.objects.get(pk=sid).status == "PAID"
    # SQL Server: el contenido de una liquidación aprobada / pagada no cambia (el error aborta la transacción: va al final).
    with pytest.raises(DatabaseError, match="50095"), connection.cursor() as cursor:
        cursor.execute("UPDATE fin.pay_settlement SET gross = gross + 1, net = net + 1 WHERE id = %s", [sid])


def test_settlement_rules_and_amount_in_words(make_employee):
    emp = make_employee("SV", hire_date=date(2025, 6, 1), base_salary=D("800.00"))
    Employee.objects.filter(pk=emp.pk).update(employment_status="TERMINATED", termination_date=date(2026, 11, 1))
    emp.refresh_from_db()
    s = settlements.open_settlement(emp, reason="RENUNCIA", termination_date=date(2026, 11, 1))
    codes = {ln.code: ln for ln in s.lines.all()}
    assert codes["PRESTACION_RENUNCIA"].kind == "INFO"  # menos de 2 años: no aplica la prestación
    assert settlements.amount_in_words(D("1234.50")) == "MIL DOSCIENTOS TREINTA Y CUATRO 50/100 DÓLARES DE LOS ESTADOS UNIDOS DE AMÉRICA"
    assert settlements.amount_in_words(D("21.00")).startswith("VEINTIÚN 00/100")
    assert settlements.amount_in_words(D("100")).startswith("CIEN 00/100")
    # Vista de antigüedad para reportería (desde el ingreso vigente hasta la terminación, sin suspensiones).
    with connection.cursor() as cursor:
        cursor.execute("SELECT TenureDays, SuspendedDays FROM hcm.vw_EmployeeTenure WHERE EmployeeId = %s", [emp.pk])
        assert cursor.fetchone() == ((date(2026, 11, 1) - date(2025, 6, 1)).days + 1, 0)
    assert s.service_days == (date(2026, 11, 1) - date(2025, 6, 1)).days + 1
    # Una liquidación en borrador no entra a un lote (SQL 50096).
    batch = SettlementBatch.objects.create(code="LT-P21-TEST", country_id=emp.country_id, payment_date=date(2026, 11, 20))
    with pytest.raises(DatabaseError, match="50096"), connection.cursor() as cursor:
        cursor.execute("UPDATE fin.pay_settlement SET batch_id = %s WHERE id = %s", [batch.pk, s.pk])
