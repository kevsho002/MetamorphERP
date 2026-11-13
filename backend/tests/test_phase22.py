"""Fase 22: justificaciones y permisos con / sin goce en el módulo regular de AP, roster automático por AP, planilla
alineada a los cortes internos (prorrateo con las horas del corte completo), tipos de contrato del Optimum ES Payroll
Hours, boletas en PDF, monedas por país, centro de notificaciones, apariencia, estadísticas de datos / ERD y retiro del
módulo mock de asistencias (esquema wfm)."""

from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

import pytest
from django.db import connection
from django.utils import timezone

from apps.adherence.models import ActivityType, AdherenceException, ScheduleSegment
from apps.common.currency import money
from apps.common.models import CostCenter
from apps.payroll import services, settlements
from apps.personnel_actions import services as pa_services
from apps.personnel_actions.models import ActionType, PersonnelAction
from apps.roster import services as roster
from apps.roster.models import RosterAssignment, RosterAttribute
from apps.scheduling.models import PayPeriod, ScheduleAssignment, TimeRecord, TimeRecordDay

pytestmark = pytest.mark.django_db
PA = "/api/v1/personnel-actions"
P = "/api/v1/payroll"
D = Decimal
DAY = {"days": {d: {"start": "08:00", "end": "17:00", "lunch_minutes": 60} for d in ("mon", "tue", "wed", "thu", "fri")}}


def _ap(api, user, type_code, employee, effective, values, **extra):
    api.force_login(user)
    return api.post(f"{PA}/", {"action_type": type_code, "employee_code": employee.employee_code, "effective_date": effective.isoformat(),
                               "justification": "Fase 22", "values": values, "submit": True, **extra}, format="json")


def _sign(api, user, folio):
    api.force_login(user)
    return api.post(f"{PA}/{folio}/sign/", {"decision": "APPROVED", "comment": "OK"}, format="json")


def _biweekly(make_employee, hire=date(2026, 9, 1), **kw):
    emp = make_employee("SV", hire_date=hire, base_salary=kw.pop("base_salary", D("880.00")), pay_frequency="BIWEEKLY", **kw)
    ScheduleAssignment.objects.create(employee=emp, definition=DAY, effective_start_date=hire)
    return emp


def _worked(emp, d, h0=8, h1=17):
    start, end = datetime(d.year, d.month, d.day, h0), datetime(d.year, d.month, d.day, h1)
    rec = TimeRecord.objects.create(employee=emp, kind="INTERVAL", start_at=start, end_at=end, occurrence_date=d,
                                    minutes=(h1 - h0) * 60, source="WEB_TIMER")
    TimeRecordDay.objects.create(record=rec, employee=emp, occurrence_date=d, start_at=start, end_at=end, minutes=(h1 - h0) * 60)


def _period():
    return PayPeriod.objects.get(cycle__code="SV_QUINCENAL", code="2026-10-Q1")


def _weekdays(windows, lo=None, hi=None):
    out = []
    for a, b in windows:
        d = max(a, lo or a)
        while d <= min(b, hi or b):
            if d.weekday() < 5:
                out.append(d)
            d += timedelta(days=1)
    return out


# ================================================================== retiro del mock de asistencias
def test_wfm_mock_schema_was_dropped():
    with connection.cursor() as c:
        c.execute("SELECT SCHEMA_ID(N'wfm'), OBJECT_ID(N'wfm.Attendance'), OBJECT_ID(N'wfm.catDowntimeType')")
        assert c.fetchone() == (None, None, None)


# ================================================================== permisos y justificaciones por AP
def test_paid_leave_full_day_justifies_grid_adherence_and_payroll(api, wfm_user, hr_user, make_employee):
    from apps.adherence.attendance import reconcile

    emp = _biweekly(make_employee)
    t = ActionType.objects.get(code="AP_PERMISO_CON_GOCE")
    attrs = {a.key: a for a in t.attributes.all()}
    assert attrs["actividad"].data_type == "ACTIVITY" and attrs["desde"].data_type == "TIME"
    options = pa_services.type_dict(t, hr_user)["attributes"]
    act_opts = next(a for a in options if a["key"] == "actividad")["options"]
    assert act_opts and all(o["value"].startswith("HRP_") and o["paid"] for o in act_opts)

    # Por horas sin indicar la ventana: error de validación.
    r = _ap(api, wfm_user, "AP_PERMISO_CON_GOCE", emp, date(2026, 10, 5), {"actividad": "HRP_PAID_SICK_TIME", "alcance": "HORAS"})
    assert r.status_code == 400 and {e["field"] for e in r.json()["errors"]} >= {"values.desde", "values.hasta"}

    # Día completo del lunes 5 al martes 6: WFM la elabora (firma su paso) y RRHH la aprueba.
    r = _ap(api, wfm_user, "AP_PERMISO_CON_GOCE", emp, date(2026, 10, 5),
            {"actividad": "HRP_PAID_SICK_TIME", "alcance": "DIA", "fecha_fin": "2026-10-06"})
    assert r.status_code == 201, r.json()
    assert any(w["code"] == "time_preview" for w in r.json()["warnings"])
    folio = r.json()["action"]["folio"]
    assert _sign(api, hr_user, folio).json()["action"]["status"] == "APPROVED"
    pa = PersonnelAction.objects.get(folio=folio)
    assert pa.applied_at is not None

    # Grilla: el turno completo de cada día queda cubierto por Paid Sick Time respaldado por la AP.
    segs = list(ScheduleSegment.objects.filter(employee=emp, personnel_action=pa).order_by("start_at"))
    assert [(s.shift_date, s.start_at.hour, s.end_at.hour, s.activity.code) for s in segs] == [
        (date(2026, 10, 5), 8, 17, "HRP_PAID_SICK_TIME"), (date(2026, 10, 6), 8, 17, "HRP_PAID_SICK_TIME")]
    # Adherencia: justificación pagada por día; la asistencia automática no marca Unjustified Absence.
    assert AdherenceException.objects.filter(employee=emp, personnel_action=pa, is_paid=True).count() == 2
    out = reconcile([emp], date(2026, 10, 5))
    assert out["absences"] == 0
    absence = ActivityType.objects.get(system_role="ABSENCE")
    assert not ScheduleSegment.objects.filter(employee=emp, activity=absence).exists()

    # Planilla (sin adherencia guardada ni Web Timer esos días): las horas del permiso con goce se pagan.
    _worked(emp, date(2026, 10, 7))
    run = services.calculate(_period())
    lines = {ln["code"]: ln for ln in services.employee_breakdown(run, emp.employee_code)["lines"]}
    assert D(str(lines["HORAS_PAGADAS"]["quantity"])) == D("24")  # 2 días de permiso + 1 laborado (8 h netas c/u)


def test_unpaid_leave_by_hours_and_time_justification(api, wfm_user, hr_user, make_employee):
    emp = _biweekly(make_employee)
    # Unpaid Time Off por horas: la ventana se recorta dentro del turno; no se paga.
    opts = next(a for a in pa_services.type_dict(ActionType.objects.get(code="AP_PERMISO_SIN_GOCE"), hr_user)["attributes"]
                if a["key"] == "actividad")["options"]
    assert "HRU_ATTRITION" not in {o["value"] for o in opts} and "HRU_SUSPENSION" not in {o["value"] for o in opts}
    r = _ap(api, wfm_user, "AP_PERMISO_SIN_GOCE", emp, date(2026, 10, 7),
            {"actividad": "HRU_VOLUNTARY_TIME_OFF", "alcance": "HORAS", "desde": "08:00", "hasta": "10:30"})
    assert r.status_code == 201, r.json()
    assert _sign(api, hr_user, r.json()["action"]["folio"]).json()["action"]["status"] == "APPROVED"
    x = AdherenceException.objects.get(employee=emp)
    assert (x.start_at.time().isoformat(), x.end_at.time().isoformat(), x.is_paid) == ("08:00:00", "10:30:00", False)
    seg = ScheduleSegment.objects.get(employee=emp, activity__code="HRU_VOLUNTARY_TIME_OFF")
    assert seg.seconds == 9000 and seg.origin == "SYSTEM" and not seg.is_locked

    # Justificación de tiempo (módulo regular de AP): ventana + actividad del Time Utilization.
    t = ActionType.objects.get(code="AP_JUSTIFICACION_TIEMPO")
    assert t.effect == "JUSTIFY"
    active = {a["key"] for a in pa_services.type_dict(t, hr_user)["attributes"]}
    assert {"desde", "hasta", "actividad", "pagado"} <= active and not {"fecha", "horario"} & active
    r = _ap(api, wfm_user, "AP_JUSTIFICACION_TIEMPO", emp, date(2026, 10, 8),
            {"motivo": "Falla de sistema", "desde": "14:00", "hasta": "15:15:30", "actividad": "ITP_SKYCOM_TOOLS", "pagado": True})
    assert r.status_code == 201, r.json()
    assert _sign(api, hr_user, r.json()["action"]["folio"]).json()["action"]["status"] == "APPROVED"
    seg = ScheduleSegment.objects.get(employee=emp, activity__code="ITP_SKYCOM_TOOLS")
    assert seg.seconds == 4530 and seg.personnel_action.folio == r.json()["action"]["folio"]
    assert AdherenceException.objects.filter(employee=emp, is_paid=True).count() == 1
    # La ventana debe caber en el turno.
    r = _ap(api, wfm_user, "AP_JUSTIFICACION_TIEMPO", emp, date(2026, 10, 9), {"motivo": "Otro", "desde": "18:00", "hasta": "19:00"})
    assert r.status_code == 400 and any(e["code"] == "outside_container" for e in r.json()["errors"])


# ================================================================== roster automático
def test_roster_automation_by_ap(api, wfm_user, hr_user, admin_user, make_employee):
    today = timezone.localdate()
    emp = make_employee("SV", hire_date=date(2026, 3, 1), base_salary=D("700.00"))
    cc = CostCenter.objects.filter(country_id=emp.country_id, is_active=True).exclude(pk=emp.cost_center_id).first()
    # Cambio organizacional (WFM → RRHH): puesto, tipo de contrato y centro de costos del expediente.
    r = _ap(api, wfm_user, "AP_CAMBIO_ORGANIZACIONAL", emp, today,
            {"job_title": "Agente bilingüe", "contract_type": "Permanente JB", "cost_center": cc.code})
    assert r.status_code == 201, r.json()
    assert _sign(api, hr_user, r.json()["action"]["folio"]).json()["action"]["status"] == "APPROVED"
    emp.refresh_from_db()
    assert emp.cost_center_id == cc.pk
    snap = {row["code"]: row["current"]["label"] for row in roster.snapshot(emp, today) if row["current"]}
    assert snap["job_title"] == "Agente bilingüe" and snap["contract_type"] == "PERMANENTE JB"
    row = RosterAssignment.objects.current().get(employee=emp, attribute__code="job_title")
    assert row.effective_start == today and row.reason.startswith("AP APCO-")
    # Un valor inválido del roster se detecta al elaborar la AP (no al aprobarla).
    r = _ap(api, wfm_user, "AP_CAMBIO_ORGANIZACIONAL", emp, today, {"contract_type": "Temporal"})
    assert r.status_code == 400 and r.json()["errors"][0]["field"] == "values.contract_type"
    r = _ap(api, wfm_user, "AP_CAMBIO_ORGANIZACIONAL", emp, today, {})
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "required"

    # Promoción futura (RRHH → Administración): se aplica en su fecha (puesto en el roster + salario del expediente).
    eff = today + timedelta(days=3)
    r = _ap(api, hr_user, "AP_PROMOCION", emp, eff, {"job_title": "Team Lead", "new_base_salary": "950"})
    assert r.status_code == 201, r.json()
    folio = r.json()["action"]["folio"]
    assert _sign(api, admin_user, folio).json()["action"]["status"] == "APPROVED"
    emp.refresh_from_db()
    assert emp.base_salary == D("700.00") and PersonnelAction.objects.get(folio=folio).applied_at is None
    assert folio in pa_services.apply_due_actions(eff)
    emp.refresh_from_db()
    assert emp.base_salary == D("950.00")
    rows = list(RosterAssignment.objects.current().filter(employee=emp, attribute__code="job_title").order_by("effective_start"))
    assert [(x.value, x.effective_end) for x in rows] == [("Agente bilingüe", eff - timedelta(days=1)), ("Team Lead", None)]

    # Ajuste salarial con puesto: también actualiza el roster.
    r = _ap(api, hr_user, "AP_AJUSTE_SALARIAL", emp, eff + timedelta(days=1),
            {"tipo_ajuste": next(o["value"] for o in ActionType.objects.get(code="AP_AJUSTE_SALARIAL").attributes.get(key="tipo_ajuste").option_list()),
             "new_base_salary": "990", "job_title": "Supervisor"})
    assert r.status_code == 201, r.json()
    _sign(api, admin_user, r.json()["action"]["folio"])
    pa_services.apply_due_actions(eff + timedelta(days=1))
    emp.refresh_from_db()
    assert emp.base_salary == D("990.00")
    assert RosterAssignment.objects.current().get(employee=emp, attribute__code="job_title", effective_end__isnull=True).value == "Supervisor"


# ================================================================== planilla: cortes internos, prorrateo y contratos
def test_payroll_prorates_with_full_cutoff_hours_and_contract_types(make_employee):
    period = _period()
    windows = services.windows_for(period)
    full_days = _weekdays(windows)
    hire = full_days[5]
    emp = _biweekly(make_employee, hire=hire)  # ingresa a mitad del corte
    for d in _weekdays(windows, lo=hire):
        _worked(emp, d)
    pro = _biweekly(make_employee, base_salary=D("1000.00"))
    RosterAssignment.objects.create(employee=pro, attribute=RosterAttribute.objects.get(code="contract_type"),
                                    value="SERVICIOS PROFESIONALES", effective_start=date(2026, 9, 1))
    _worked(pro, full_days[0])

    run = services.calculate(period)
    lines = {ln["code"]: ln for ln in services.employee_breakdown(run, emp.employee_code)["lines"]}
    full_h = D(len(full_days) * 8)
    rate = D("440") / full_h  # 50 % del mensual ÷ horas programadas del corte COMPLETO
    paid_h = D(len(_weekdays(windows, lo=hire)) * 8)
    assert D(str(lines["HORAS_PROGRAMADAS_CORTE"]["quantity"])) == full_h
    assert D(str(lines["HORAS_PROGRAMADAS"]["quantity"])) == paid_h
    assert D(str(lines["SALARIO"]["rate"])) == rate.quantize(D("0.0001"))
    assert D(str(lines["SALARIO"]["amount"])) == (rate * paid_h).quantize(D("0.01"))
    assert "Prorrateo" in lines["SALARIO"]["notes"]

    # Servicios profesionales: sin ISSS ni AFP; Renta fija del 10 % sobre lo gravado (Optimum ES Payroll Hours).
    b = services.employee_breakdown(run, pro.employee_code)
    codes = {ln["code"]: ln for ln in b["lines"]}
    assert not {"ISSS_EMP", "AFP_EMP", "ISSS_PAT", "AFP_PAT"} & set(codes)
    # Redondeo ROUND(…, 2) de Excel (mitad hacia arriba)
    assert D(str(codes["ISR_SV"]["amount"])) == (D(str(b["detail"]["gross_pay"])) * D("0.10")).quantize(D("0.01"), ROUND_HALF_UP)
    assert "TIPO_CONTRATO" in codes


# ================================================================== boletas en PDF y moneda
def test_payslip_pdf_downloads_and_currency(api, hr_user, make_user, make_employee):
    emp = _biweekly(make_employee)
    agent = make_user("agente.p22", "EMPLOYEE", employee=emp)
    _worked(emp, date(2026, 10, 1))
    run = services.calculate(_period())
    api.force_login(hr_user)
    r = api.get(f"{P}/runs/{run.pk}/employees/{emp.employee_code}/pdf/")
    assert r.status_code == 200 and r["Content-Type"] == "application/pdf" and r.content.startswith(b"%PDF-1.4")
    assert "boleta-preliminar" in r["Content-Disposition"] and r.content.rstrip().endswith(b"%%EOF")
    api.force_login(agent)
    assert api.get(f"{P}/runs/{run.pk}/employees/{emp.employee_code}/pdf/").status_code == 403
    r = api.get(f"{P}/me/payslips/preliminary/{run.pk}/pdf/")
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    # Moneda por país: símbolo y monto en letras.
    assert money(D("1234.5"), "GTQ") == "Q 1,234.50" and money(D("-12"), "USD") == "-$12.00"
    assert settlements.amount_in_words(D("21.05"), "GTQ") == "VEINTIÚN 05/100 QUETZALES"


# ================================================================== notificaciones
def test_notifications_center(api, wfm_user, hr_user, make_employee):
    today = timezone.localdate()
    emp = _biweekly(make_employee, hire=today - timedelta(days=1))
    # AP elaborada por WFM: queda pendiente del paso de RRHH.
    r = _ap(api, wfm_user, "AP_CAMBIO_ORGANIZACIONAL", emp, today, {"job_title": "Agente"})
    assert r.status_code == 201, r.json()
    folio = r.json()["action"]["folio"]
    # No-show de hoy.
    absence = ActivityType.objects.get(system_role="ABSENCE")
    ScheduleSegment.objects.create(employee=emp, shift_date=today, activity=absence, origin="SYSTEM", is_locked=True,
                                   start_at=datetime.combine(today, datetime.min.time()).replace(hour=8),
                                   end_at=datetime.combine(today, datetime.min.time()).replace(hour=17))
    api.force_login(hr_user)
    body = api.get("/api/v1/system/notifications/").json()
    kinds = {i["kind"] for i in body["results"]}
    assert {"ap", "hire", "noshow"} <= kinds and body["unread"] >= 3
    ap_item = next(i for i in body["results"] if i["kind"] == "ap")
    assert folio in ap_item["body"] and ap_item["link"] == f"/personnel-actions/{folio}"
    r = api.post("/api/v1/system/notifications/", {"keys": [ap_item["key"]]}, format="json")
    assert r.json()["unread"] == body["unread"] - 1
    assert api.post("/api/v1/system/notifications/", {"all": True}, format="json").json()["unread"] == 0
    # WFM (creador) no tiene la AP pendiente de su firma.
    api.force_login(wfm_user)
    assert not any(i["kind"] == "ap" for i in api.get("/api/v1/system/notifications/").json()["results"])


# ================================================================== apariencia, datos y ERD
def test_appearance_data_stats_and_erd(api, admin_user, hr_user):
    api.force_login(hr_user)
    assert api.get("/api/v1/system/appearance/").json()["can_manage"] is False
    assert api.patch("/api/v1/system/appearance/", {"brand_palette": "TEAL"}, format="json").status_code == 403
    assert api.get("/api/v1/system/data/stats/").status_code == 403
    api.force_login(admin_user)
    r = api.patch("/api/v1/system/appearance/", {"brand_palette": "CUSTOM"}, format="json")
    assert r.status_code == 400
    r = api.patch("/api/v1/system/appearance/", {"brand_palette": "CUSTOM", "brand_accent": "#aa3355"}, format="json")
    assert r.status_code == 200
    cfg = api.get("/api/v1/system/client-config/").json()
    assert (cfg["brand_palette"], cfg["brand_accent"]) == ("CUSTOM", "#aa3355")

    stats = api.get("/api/v1/system/data/stats/").json()
    names = {t["name"]: t for t in stats["tables"]}
    assert "hcm.Employee" in names and "dbo.pay_payroll_line" in names and not any(n.startswith("wfm.") for n in names)
    assert names["hcm.Employee"]["module"] == "Capital Humano" and names["dbo.pa_action"]["fk_out"] >= 1
    assert stats["totals"]["procedures"] >= 2 and stats["totals"]["tables"] == len(stats["tables"])
    erd = api.get("/api/v1/system/data/erd/").json()
    rel = [x for x in erd["relations"] if x["from"] == "dbo.pa_action" and x["to"] == "hcm.Employee"]
    assert rel and rel[0]["columns"][0] == ["employee_id", "EmployeeId"]
    emp_t = next(t for t in erd["tables"] if t["name"] == "hcm.Employee")
    assert any(c["pk"] and c["name"] == "EmployeeId" for c in emp_t["columns"])
