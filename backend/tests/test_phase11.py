"""Fase 11: periodos de pago y cortes internos de asistencia desacoplados; módulo de estados y auxiliares ACD."""

import csv
import io
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, transaction

from apps.acd import services as acd
from apps.acd.models import AgentGroup, AgentSession, AuxCode, PrimaryStatus, StatusSegment
from apps.scheduling import engine
from apps.scheduling import services as sch
from apps.scheduling.models import AttendanceCutoff, PayCycle, PayPeriod, TimeRecord, TimeRecordDay

pytestmark = pytest.mark.django_db
S = "/api/v1/scheduling"
A = "/api/v1/acd"
SV = ZoneInfo("America/El_Salvador")


def local(y, m, d, hh, mm=0, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=SV)


# ================================================================== 1. periodos de pago vs cortes internos
def test_engine_maps_cross_month_cutoffs_to_the_nearest_pay_period():
    rule = engine.CycleRule("HALF_MONTH", first_half_end_day=15, cutoff_start_day=10, cutoff_first_end_day=24)
    periods = engine.generate_periods(rule, 2026)
    assert (periods[0]["period_start"], periods[0]["period_end"], periods[0]["payment_date"]) == (date(2026, 1, 1), date(2026, 1, 15), date(2026, 1, 15))
    windows = engine.cutoff_windows(rule, periods)
    assert len(windows) == 24
    first, second = windows[0], windows[1]
    # del 25 del mes anterior al 9 → se paga en la quincena 1–15; del 10 al 24 → se paga en la 16–fin
    assert (first["cutoff_start"], first["cutoff_end"], first["period"]["label"]) == (date(2025, 12, 25), date(2026, 1, 9), "2026-01-Q1")
    assert (second["cutoff_start"], second["cutoff_end"], second["period"]["label"]) == (date(2026, 1, 10), date(2026, 1, 24), "2026-01-Q2")
    for a, b in zip(windows, windows[1:]):
        assert (b["cutoff_start"] - a["cutoff_end"]).days == 1
    assert engine.describe_cutoff_rule(rule) == "Del 10 al 24 y del 25 al 9 del mes siguiente"
    assert engine.describe_cutoff_rule(engine.CycleRule("HALF_MONTH")) == "Igual al periodo de pago"
    monthly = engine.CycleRule("MONTH", cutoff_start_day=26)
    w = engine.cutoff_windows(monthly, engine.generate_periods(monthly, 2026))
    assert (w[0]["cutoff_start"], w[0]["cutoff_end"], w[0]["period"]["label"]) == (date(2025, 12, 26), date(2026, 1, 25), "2026-01")


def test_generate_next_year_keeps_both_dimensions_contiguous(api, hr_user):
    api.force_login(hr_user)
    r = api.post(f"{S}/pay-cycles/SV_QUINCENAL_BPO/generate/", {"year": 2027}, format="json")
    assert r.status_code == 200 and (r.json()["created"], r.json()["cutoffs_created"]) == (24, 24), r.json()
    cycle = PayCycle.objects.get(code="SV_QUINCENAL_BPO")
    jan = cycle.periods.get(code="2027-01-Q1")
    assert (jan.period_start, jan.period_end, jan.payment_date) == (date(2027, 1, 1), date(2027, 1, 15), date(2027, 1, 15))
    cut = cycle.cutoffs.get(code="C-2027-01-Q1")
    assert (cut.cutoff_start, cut.cutoff_end, cut.pay_period_id) == (date(2026, 12, 25), date(2027, 1, 9), jan.pk)
    cuts = list(cycle.cutoffs.order_by("cutoff_start"))
    periods = list(cycle.periods.order_by("period_start"))
    assert all((b.cutoff_start - a.cutoff_end).days == 1 for a, b in zip(cuts, cuts[1:]))
    assert all((b.period_start - a.period_end).days == 1 for a, b in zip(periods, periods[1:]))
    again = api.post(f"{S}/pay-cycles/SV_QUINCENAL_BPO/generate/", {"year": 2027}, format="json").json()
    assert (again["created"], again["cutoffs_created"]) == (0, 0) and "ya existían" in again["feedback"]

    listing = api.get(f"{S}/pay-cycles/", {"year": 2027}).json()
    bpo = next(c for c in listing["results"] if c["code"] == "SV_QUINCENAL_BPO")
    assert bpo["rule_description"] == "Del 1 al 15 y del 16 al fin de mes"
    assert bpo["periods"][0]["cutoffs"][0]["code"] == "C-2027-01-Q1" and bpo["stats"]["periods_without_cutoff"] == 0


def _bpo():
    cycle = PayCycle.objects.get(code="SV_QUINCENAL_BPO")
    return cycle, cycle.periods.get(code="2026-03-Q1"), cycle.periods.get(code="2026-03-Q2"), cycle.cutoffs.get(code="C-2026-03-Q1")


def test_dimensions_are_independent():
    _, q1, _, cut = _bpo()
    # el corte cruza de mes aunque la quincena no; otro ciclo puede tener ventanas que se cruzan con estas
    assert cut.crosses_month and not q1.crosses_month and (cut.cutoff_start, cut.cutoff_end) == (date(2026, 2, 25), date(2026, 3, 9))
    other = PayCycle.objects.get(code="SV_QUINCENAL")
    assert other.cutoffs.filter(cutoff_start__lte=cut.cutoff_end, cutoff_end__gte=cut.cutoff_start).exists()


def test_sql_50043_pay_periods_cannot_overlap():
    _, q1, _, _ = _bpo()
    with pytest.raises(DatabaseError) as exc, transaction.atomic():
        PayPeriod.objects.filter(pk=q1.pk).update(period_end=date(2026, 3, 20))
    assert "50043" in str(exc.value)


def test_sql_50048_cutoff_maps_to_the_period_containing_its_close():
    _, _, q2, cut = _bpo()  # cierra el 09/03: no se paga en la quincena 16–31
    with pytest.raises(DatabaseError) as exc, transaction.atomic():
        AttendanceCutoff.objects.filter(pk=cut.pk).update(pay_period=q2)
    assert "50048" in str(exc.value)


def test_sql_50049_closed_cutoff_dates_are_frozen():
    _, _, _, cut = _bpo()
    AttendanceCutoff.objects.filter(pk=cut.pk).update(status="CLOSED")  # cerrar no dispara reglas de fechas
    with pytest.raises(DatabaseError) as exc, transaction.atomic():
        AttendanceCutoff.objects.filter(pk=cut.pk).update(cutoff_end=date(2026, 3, 8))
    assert "50049" in str(exc.value)


def test_model_validation_explains_mapping_and_cycle_rules(countries):
    cycle = PayCycle.objects.get(code="SV_QUINCENAL_BPO")
    cut = cycle.cutoffs.get(code="C-2026-05-Q2")  # 10/05–24/05
    cut.pay_period = cycle.periods.get(code="2026-05-Q1")
    errors = cut.mapping_errors()
    assert "24/05/2026" in errors["pay_period"] and "Corresponde a 2026-05-Q2" in errors["pay_period"]
    c = PayCycle(code="T", name="T", country=countries["SV"], pay_frequency="BIWEEKLY", period_rule="HALF_MONTH",
                 cutoff_start_day=10)
    with pytest.raises(ValidationError) as exc:
        c.clean()
    assert "cutoff_first_end_day" in exc.value.message_dict
    c.cutoff_first_end_day, c.cutoff_lag_days = 24, 3
    with pytest.raises(ValidationError) as exc:
        c.clean()
    assert "cutoff_lag_days" in exc.value.message_dict


def _bpo_default():
    PayCycle.objects.filter(code="SV_QUINCENAL").update(is_default=False)
    PayCycle.objects.filter(code="SV_QUINCENAL_BPO").update(is_default=True)


def _web_time(emp, start, end):
    check = sch.check_time_record(emp, {"start_at": start, "end_at": end, "source": "WEB_TIMER"})
    assert check.ok, check.errors
    return sch.create_time_record(emp, check)


def test_payroll_hours_come_from_the_cutoffs_mapped_to_the_pay_period(api, hr_user, make_employee):
    _bpo_default()
    emp = make_employee("SV", pay_frequency="BIWEEKLY", hire_date=date(2026, 3, 1))
    _web_time(emp, datetime(2026, 10, 8, 8), datetime(2026, 10, 8, 16))   # corte 25/09–09/10 → quincena 1–15 oct
    _web_time(emp, datetime(2026, 10, 12, 8), datetime(2026, 10, 12, 12))  # corte 10/10–24/10 → quincena 16–31 oct
    cycle = PayCycle.objects.get(code="SV_QUINCENAL_BPO")
    q1, q2 = cycle.periods.get(code="2026-10-Q1"), cycle.periods.get(code="2026-10-Q2")
    api.force_login(hr_user)
    body = api.get(f"{S}/pay-periods/{q1.pk}/hours/").json()
    row = next(r for r in body["rows"] if r["employee_code"] == emp.employee_code)
    # El 12/10 cae en la quincena de pago 1–15, pero su corte (10–24) se paga en la 16–31: no cuenta aquí
    assert row["worked_minutes"] == 480 and [c["cutoff"] for c in row["cutoffs"]] == ["C-2026-10-Q1"]
    assert body["cutoffs"][0]["cutoff_start"] == "2026-09-25" and body["period"]["payment_date"] == "2026-10-15"
    row2 = next(r for r in api.get(f"{S}/pay-periods/{q2.pk}/hours/").json()["rows"] if r["employee_code"] == emp.employee_code)
    assert row2["worked_minutes"] == 240
    text = api.get(f"{S}/pay-periods/{q1.pk}/hours/", {"export": "csv"}).content.decode("utf-8-sig")
    assert "Corte de asistencia" in text.splitlines()[0] and "C-2026-10-Q1" in text
    # El reporte por periodo usa la ventana de sus cortes; por corte, la ventana de ese corte
    rep = api.get(f"{S}/report/", {"period": q1.pk, "employee": emp.employee_code}).json()
    assert (rep["from"], rep["to"], rep["totals"]["worked_minutes"]) == ("2026-09-25", "2026-10-09", 480)
    cut2 = cycle.cutoffs.get(code="C-2026-10-Q2")
    rep2 = api.get(f"{S}/report/", {"cutoff": cut2.pk, "employee": emp.employee_code}).json()
    assert rep2["cutoff"]["code"] == "C-2026-10-Q2" and rep2["totals"]["worked_minutes"] == 240


def test_closing_a_cutoff_blocks_its_window_and_names_the_pay_period(api, hr_user, make_employee):
    _bpo_default()
    emp = make_employee("SV", pay_frequency="BIWEEKLY", hire_date=date(2026, 3, 1))
    cut = AttendanceCutoff.objects.get(cycle__code="SV_QUINCENAL_BPO", code="C-2026-10-Q1")
    api.force_login(hr_user)
    r = api.post(f"{S}/cutoffs/{cut.pk}/close/")
    assert r.status_code == 200 and r.json()["cutoff"]["status"] == "CLOSED"
    check = sch.check_time_record(emp, {"start_at": datetime(2026, 9, 28, 8), "end_at": datetime(2026, 9, 28, 16)})
    assert check.errors[0]["code"] == "closed_period" and "2026-10-Q1" in check.errors[0]["message"]
    assert sch.check_time_record(emp, {"start_at": datetime(2026, 10, 12, 8), "end_at": datetime(2026, 10, 12, 16)}).ok
    day = api.get(f"{S}/employees/{emp.employee_code}/days/2026-09-28/").json()
    assert day["cutoff"]["code"] == "C-2026-10-Q1" and day["period"]["code"] == "2026-10-Q1"


def test_phase11_reporting_views(api, hr_user):
    with connection.cursor() as cursor:
        cursor.execute("SELECT CutoffCode, PayPeriodCode FROM dbo.vw_SchAttendanceCutoff WHERE CycleCode = 'SV_QUINCENAL_BPO' AND CutoffStart = '2026-09-25'")
        assert cursor.fetchone() == ("C-2026-10-Q1", "2026-10-Q1")
        cursor.execute("SELECT CutoffCount, AttendanceStatus FROM dbo.vw_SchPayPeriod WHERE CycleCode = 'SV_QUINCENAL_BPO' AND PeriodCode = '2026-10-Q1'")
        assert cursor.fetchone() == (1, "OPEN")
        for view in ("vw_SchPayrollHours", "vw_AcdStatusSegment", "vw_AcdAgentSession"):
            cursor.execute(f"SELECT TOP 1 * FROM dbo.{view}")


# ================================================================== 2. ACD: estados y auxiliares
@pytest.fixture
def agent(api, wfm_user, employee_user):
    """Agente (rol Empleado, vinculado a su expediente) asignado por WFM al grupo GENERAL."""
    api.force_login(wfm_user)
    r = api.post(f"{A}/groups/GENERAL/members/", {"employee_code": employee_user.employee_id}, format="json")
    assert r.status_code == 201, r.json()
    api.force_login(employee_user)
    return employee_user


def test_agent_needs_a_group_and_the_flow_records_every_status(api, wfm_user, employee_user):
    api.force_login(employee_user)
    r = api.post(f"{A}/me/login/")
    assert r.status_code == 403 and r.json()["code"] == "no_group"
    api.force_login(wfm_user)
    api.post(f"{A}/groups/GENERAL/members/", {"employee_code": employee_user.employee_id}, format="json")
    api.force_login(employee_user)

    me = api.post(f"{A}/me/login/").json()
    assert me["logged_in"] and me["current"]["primary_label"] == "Available" and me["division"]["name"] == "Home"
    assert api.post(f"{A}/me/login/").json()["code"] == "already_logged_in"
    codes = {o["code"] for o in me["options"]}
    assert {"AVAILABLE", "ON_QUEUE", "BREAK", "MEAL", "MEETING"} <= codes and "OFFLINE" not in codes and "IDLE" not in codes
    meeting = next(o for o in me["options"] if o["code"] == "MEETING")
    coaching = next(a for a in meeting["aux_codes"] if a["code"] == "COACHING")
    assert [c["code"] for c in coaching["children"]] == ["COACHING_QA", "COACHING_SUP"]
    busy = next(o for o in me["options"] if o["code"] == "BUSY")
    assert [a["code"] for a in busy["aux_codes"]] == ["ACW"]  # BACK_OFFICE está restringido y GENERAL no lo tiene

    def go(primary, aux=None):
        return api.post(f"{A}/me/status/", {"primary_status": primary, "aux_code": aux}, format="json")

    assert go("ON_QUEUE").json()["current"]["is_productive"]
    assert go("ON_QUEUE").json()["code"] == "same_status"
    assert go("BREAK", "BREAK_STD").json()["current"]["secondary_status"] == "Break"
    assert go("MEETING", "COACHING").json()["code"] == "choose_sub_aux"
    assert go("MEETING", "COACHING_QA").json()["current"]["secondary_status"] == "Coaching - Calidad"
    r = go("BUSY", "BACK_OFFICE")
    assert r.status_code == 403 and r.json()["code"] == "aux_not_allowed"
    assert go("BREAK", "LUNCH").json()["code"] == "aux_status_mismatch"
    assert go("OFFLINE").json()["code"] == "use_logout"

    out = api.post(f"{A}/me/logout/").json()
    assert not out["logged_in"] and out["current"]["primary_label"] == "Offline"
    segs = list(StatusSegment.objects.filter(employee_id=employee_user.employee.pk).order_by("start_at"))
    assert [s.primary_status.code for s in segs] == ["AVAILABLE", "ON_QUEUE", "BREAK", "MEETING", "OFFLINE"]
    assert all(s.end_at and s.duration_ms == (s.end_at - s.start_at) // timedelta(milliseconds=1) for s in segs[:-1])
    assert all(a.end_at == b.start_at for a, b in zip(segs, segs[1:]))  # sin huecos ni traslapes
    assert AgentSession.objects.get(employee_id=employee_user.employee.pk).sync_status == "SKIPPED"  # menos de 1 minuto


def test_group_access_management_and_permissions(api, agent, wfm_user, hr_user, employee_user):
    assert api.get(f"{A}/agents/").status_code == 403  # el agente no supervisa
    assert api.get(f"{A}/report/", {"from": "2026-10-01"}).status_code == 403
    api.force_login(hr_user)
    assert api.get(f"{A}/agents/").status_code == 200
    assert api.patch(f"{A}/groups/GENERAL/", {"aux_codes": ["BACK_OFFICE"]}, format="json").status_code == 403
    api.force_login(wfm_user)
    r = api.patch(f"{A}/groups/GENERAL/", {"aux_codes": ["COACHING", "BACK_OFFICE"]}, format="json")
    assert r.status_code == 200 and r.json()["group"]["aux_codes"] == ["BACK_OFFICE", "COACHING"]
    assert api.patch(f"{A}/groups/GENERAL/", {"aux_codes": ["NOPE"]}, format="json").status_code == 400
    r = api.post(f"{A}/groups/", {"code": "CAMP_X", "name": "Campaña X", "division": "HOME"}, format="json")
    assert r.status_code == 201
    # Mover al agente de grupo; no se puede con sesión abierta
    api.force_login(employee_user)
    api.post(f"{A}/me/login/")
    api.force_login(wfm_user)
    r = api.post(f"{A}/groups/CAMP_X/members/", {"employee_code": employee_user.employee_id}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "session_open"
    board = api.get(f"{A}/agents/", {"group": "GENERAL"}).json()
    row = next(x for x in board["results"] if x["employee_code"] == employee_user.employee_id)
    assert row["logged_in"] and row["current"]["primary_label"] == "Available" and board["by_status"]["Available"] >= 1
    r = api.post(f"{A}/agents/{employee_user.employee_id}/logout/", {"reason": "Fin de turno"}, format="json")
    assert r.status_code == 200
    seg = StatusSegment.objects.filter(employee_id=employee_user.employee.pk, end_at__isnull=True).get()
    assert seg.primary_status.code == "OFFLINE" and seg.source == "SUPERVISOR" and "Fin de turno" in seg.notes
    assert api.post(f"{A}/groups/CAMP_X/members/", {"employee_code": employee_user.employee_id}, format="json").status_code == 201
    assert AgentGroup.objects.get(code="GENERAL").members.filter(is_active=True, employee_id=employee_user.employee.pk).count() == 0


def _past_session(employee, group, plan):
    """Sesión en el pasado con segmentos [(estado, aux, inicio, fin)] (para probar envío de tiempo y reporte)."""
    statuses = {s.code: s for s in PrimaryStatus.objects.all()}
    session = AgentSession.objects.create(employee=employee, group=group, login_at=plan[0][2], logout_at=plan[-1][3], logout_source="AGENT")
    for code, aux, start, end in plan:
        StatusSegment.objects.create(
            employee=employee, session=session, primary_status=statuses[code], group=group, division=group.division,
            aux_code=AuxCode.objects.get(code=aux) if aux else None, start_at=start, end_at=end,
            duration_ms=(end - start) // timedelta(milliseconds=1))
    return session


def test_session_paid_time_becomes_web_timer_records_and_meal_is_excluded(make_employee):
    emp = make_employee("SV", hire_date=date(2026, 3, 1))
    group = AgentGroup.objects.get(code="GENERAL")
    session = _past_session(emp, group, [
        ("AVAILABLE", None, local(2026, 10, 5, 7, 58, 30), local(2026, 10, 5, 8, 0, 10)),
        ("ON_QUEUE", None, local(2026, 10, 5, 8, 0, 10), local(2026, 10, 5, 12, 0, 40)),
        ("MEAL", "LUNCH", local(2026, 10, 5, 12, 0, 40), local(2026, 10, 5, 12, 31, 5)),
        ("ON_QUEUE", None, local(2026, 10, 5, 12, 31, 5), local(2026, 10, 5, 16, 45)),
        ("BUSY", "ACW", local(2026, 10, 5, 16, 45), local(2026, 10, 5, 17, 0, 20)),
    ])
    acd.sync_session_time(session)
    session.refresh_from_db()
    assert session.sync_status == "SYNCED", session.sync_message
    records = list(TimeRecord.objects.filter(employee=emp, source="WEB_TIMER").order_by("start_at"))
    assert [(r.start_at.strftime("%H:%M"), r.end_at.strftime("%H:%M")) for r in records] == [("07:58", "12:00"), ("12:31", "17:00")]
    assert session.paid_minutes == 242 + 269 and records[0].external_ref == f"ACD-S{session.pk}"
    assert sum(TimeRecordDay.objects.filter(employee=emp).values_list("minutes", flat=True)) == 511


def test_genesys_style_report_splits_segments_by_interval(api, hr_user, make_employee):
    emp = make_employee("SV", hire_date=date(2026, 3, 1))
    group = AgentGroup.objects.get(code="GENERAL")
    _past_session(emp, group, [
        ("ON_QUEUE", None, local(2026, 10, 6, 8, 15), local(2026, 10, 6, 9, 40, 0)),
        ("MEETING", "COACHING_QA", local(2026, 10, 6, 9, 40, 0), local(2026, 10, 6, 10)),
    ])
    api.force_login(hr_user)
    body = api.get(f"{A}/report/", {"from": "2026-10-06", "interval": "60", "employee": emp.employee_code, "page_size": 50}).json()
    assert body["columns"] == ["Interval Start", "Interval End", "Interval Complete", "Employee Id", "Employee Name",
                               "Division Id", "Division Name", "Start Time", "End Time", "Primary Status",
                               "Secondary Status", "Duration"]
    rows = body["results"]
    assert [(r["Interval Start"][11:16], r["Primary Status"], r["Duration"]) for r in rows] == [
        ("08:00", "On Queue", 45 * 60_000), ("09:00", "On Queue", 40 * 60_000), ("09:00", "Meeting", 20 * 60_000)]
    first = rows[0]
    assert first["Start Time"] == "2026-10-06T08:15:00.000-06:00" and first["End Time"] == "2026-10-06T09:00:00.000-06:00"
    assert first["Interval Complete"] == "TRUE" and first["Employee Id"] == emp.employee_code and first["Division Name"] == "Home"
    assert rows[2]["Secondary Status"] == "Coaching - Calidad"
    daily = api.get(f"{A}/report/", {"from": "2026-10-06", "employee": emp.employee_code}).json()
    assert daily["count"] == 2 and daily["summary"][0]["total_ms"] == 105 * 60_000
    resp = api.get(f"{A}/report/", {"from": "2026-10-06", "interval": "30", "employee": emp.employee_code, "export": "csv"})
    lines = list(csv.reader(io.StringIO(b"".join(resp.streaming_content).decode("utf-8-sig"))))
    assert lines[0] == body["columns"] and len(lines) == 1 + 5  # On Queue 08:15–08:30, –09:00, –09:30, –09:40 + Meeting 09:40–10:00
    assert api.get(f"{A}/report/", {"from": "2026-10-06", "interval": "15"}).json()["code"] == "invalid_interval"


def _acd_base(make_employee):
    emp = make_employee("SV", hire_date=date(2026, 3, 1))
    _past_session(emp, AgentGroup.objects.get(code="GENERAL"), [("ON_QUEUE", None, local(2026, 10, 7, 8), local(2026, 10, 7, 9))])
    return emp


def test_sql_50060_segments_cannot_overlap(make_employee):
    emp = _acd_base(make_employee)
    with pytest.raises(DatabaseError) as exc, transaction.atomic():
        StatusSegment.objects.create(employee=emp, primary_status=PrimaryStatus.objects.get(code="ON_QUEUE"),
                                     start_at=local(2026, 10, 7, 8, 30), end_at=local(2026, 10, 7, 9, 30), duration_ms=3_600_000)
    assert "50060" in str(exc.value)


def test_sql_50061_aux_must_match_primary_status(make_employee):
    emp = _acd_base(make_employee)
    with pytest.raises(DatabaseError) as exc, transaction.atomic():
        StatusSegment.objects.create(employee=emp, primary_status=PrimaryStatus.objects.get(code="BREAK"),
                                     aux_code=AuxCode.objects.get(code="LUNCH"), start_at=local(2026, 10, 7, 10),
                                     end_at=local(2026, 10, 7, 10, 30), duration_ms=1_800_000)
    assert "50061" in str(exc.value)


def test_sql_50062_sub_aux_has_one_level():
    qa = AuxCode.objects.get(code="COACHING_QA")
    with pytest.raises(DatabaseError) as exc, transaction.atomic():
        AuxCode.objects.create(code="DEEP", name="Nivel 3", primary_status=qa.primary_status, parent=qa)
    assert "50062" in str(exc.value)
