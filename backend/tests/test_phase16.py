"""Fase 16: segmentos de actividad, validación de pago y motor de adherencia (WFM)."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.db import DatabaseError, connection, transaction

from apps.acd.models import AgentGroup, AgentMembership, AgentSession, AuxCode, PrimaryStatus, StatusSegment
from apps.adherence import engine
from apps.adherence.models import ActivityType, AdherenceDay, AdherenceException, Deviation, ScheduleSegment
from apps.personnel_actions.models import ActionType, PersonnelAction
from apps.scheduling.models import AttendanceCutoff, PayCycle, ScheduleAssignment

pytestmark = pytest.mark.django_db
H = "/api/v1/adherence"
SV = ZoneInfo("America/El_Salvador")
MON = date(2026, 10, 5)  # lunes
DAY = {"days": {d: {"start": "08:00", "end": "17:00", "lunch_minutes": 60} for d in ("mon", "tue", "wed", "thu", "fri")}}
NIGHT = {"days": {d: {"start": "22:00", "end": "06:00", "lunch_minutes": 30} for d in ("mon", "tue", "wed", "thu", "fri")}}


def wall(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hh, mm)


# ================================================================== 1. motor (sin base de datos)
ACTS = {
    "PRODUCTION": engine.Activity("PRODUCTION", is_paid=True, is_billable=True, rules=(
        engine.StatusRule("ON_QUEUE", None, "PRIMARY"), engine.StatusRule("BUSY", "ACW", "SECONDARY"))),
    "BREAK": engine.Activity("BREAK", rules=(engine.StatusRule("BREAK", None, "PRIMARY"),)),
    "MEAL": engine.Activity("MEAL", is_paid=False, rules=(engine.StatusRule("MEAL", None, "PRIMARY"),)),
    "COACHING": engine.Activity("COACHING", rules=(engine.StatusRule("MEETING", "COACHING", "PRIMARY"),)),
}


def _day_plan():
    container = engine.Container(MON, wall(MON, 8), wall(MON, 17), "AP-1")
    segs = [engine.PlannedSegment(MON, wall(MON, 10), wall(MON, 10, 15), "BREAK"),
            engine.PlannedSegment(MON, wall(MON, 12), wall(MON, 13), "MEAL"),
            engine.PlannedSegment(MON, wall(MON, 15), wall(MON, 15, 30), "COACHING")]
    return engine.build_plan([container], segs, "PRODUCTION")


def _a(h0, m0, h1, m1, primary, aux=None, parent=None, paid=True):
    return engine.Actual(wall(MON, h0, m0), wall(MON, h1, m1), primary, aux, parent, paid, primary)


ACTUAL = [
    _a(7, 50, 8, 0, "ON_QUEUE"),
    _a(8, 0, 10, 0, "ON_QUEUE"),
    _a(10, 0, 10, 20, "BREAK", "BREAK_STD"),
    _a(10, 20, 12, 0, "ON_QUEUE"),
    _a(12, 0, 13, 0, "MEAL", "LUNCH", paid=False),
    _a(13, 0, 15, 0, "BUSY", "ACW"),
    _a(15, 0, 15, 30, "MEETING", "COACHING_QA", "COACHING"),  # sub-auxiliar: cumple la regla de su padre
    _a(15, 30, 16, 30, "ON_QUEUE"),
    # 16:30–17:00 sin sesión
    _a(17, 0, 17, 20, "ON_QUEUE"),
]


def test_plan_fills_the_container_with_the_default_activity_and_rejects_segments_outside():
    plan = _day_plan()
    assert [(b.start.strftime("%H:%M"), b.end.strftime("%H:%M"), b.activity, b.source) for b in plan] == [
        ("08:00", "10:00", "PRODUCTION", "CONTAINER"), ("10:00", "10:15", "BREAK", "SEGMENT"),
        ("10:15", "12:00", "PRODUCTION", "CONTAINER"), ("12:00", "13:00", "MEAL", "SEGMENT"),
        ("13:00", "15:00", "PRODUCTION", "CONTAINER"), ("15:00", "15:30", "COACHING", "SEGMENT"),
        ("15:30", "17:00", "PRODUCTION", "CONTAINER"),
    ]
    container = engine.Container(MON, wall(MON, 8), wall(MON, 17))
    with pytest.raises(engine.PlanError, match="sale del contenedor"):
        engine.build_plan([container], [engine.PlannedSegment(MON, wall(MON, 16, 45), wall(MON, 17, 15), "BREAK")], "PRODUCTION")
    with pytest.raises(engine.PlanError, match="traslapados"):
        engine.build_plan([container], [engine.PlannedSegment(MON, wall(MON, 9), wall(MON, 10), "BREAK"),
                                        engine.PlannedSegment(MON, wall(MON, 9, 30), wall(MON, 9, 45), "BREAK")], "PRODUCTION")


def test_engine_adherence_pay_billing_and_deviations():
    justif = [engine.Justification(wall(MON, 17), wall(MON, 17, 10), True, 1, "APJ-1")]
    res = engine.evaluate(_day_plan(), ACTUAL, justif, ACTS, window_start=wall(MON, 0), window_end=wall(MON + timedelta(days=1), 0))
    t = res.days[MON]
    m = lambda s: s // 60  # noqa: E731
    assert m(t.scheduled) == 540 and m(t.scheduled_paid) == 480  # el almuerzo no es pagado
    assert m(t.in_adherence) == 505 and m(t.out_of_adherence) == 35
    assert t.adherence_pct == 93.52 and t.conformance_pct == 94.44
    assert m(t.paid_valid) == 460  # dentro del contenedor en estado pagado + exceso justificado pagado
    assert m(t.billable) == 400  # solo producción en adherencia
    assert m(t.primary_work) == 325 and m(t.secondary_paid) == 120  # ACW en producción = auxiliar secundario pagado
    assert m(t.unpaid_excess) == 20 and m(t.justified) == 10
    got = [(x.kind, x.start.strftime("%H:%M"), x.end.strftime("%H:%M"), x.expected, x.actual.primary if x.actual else None)
           for x in res.deviations]
    assert got == [
        ("UNPAID_EXCESS_LOGIN", "07:50", "08:00", None, "ON_QUEUE"),
        ("OUT_OF_ADHERENCE", "10:15", "10:20", "PRODUCTION", "BREAK"),
        ("OUT_OF_ADHERENCE", "16:30", "17:00", "PRODUCTION", None),
        ("UNPAID_EXCESS_LOGIN", "17:10", "17:20", None, "ON_QUEUE"),
    ]


def test_justified_scheduled_time_leaves_the_adherence_base():
    plan = engine.build_plan([engine.Container(MON, wall(MON, 8), wall(MON, 12))], [], "PRODUCTION")
    actual = [_a(8, 0, 10, 0, "ON_QUEUE")]
    res = engine.evaluate(plan, actual, [engine.Justification(wall(MON, 10), wall(MON, 12), False)], ACTS,
                          window_start=wall(MON, 0), window_end=wall(MON, 23))
    t = res.days[MON]
    assert t.adherence_pct == 100.0 and t.justified == 7200 and t.paid_valid == 7200 and not res.deviations


def test_evaluation_stops_at_now():
    plan = engine.build_plan([engine.Container(MON, wall(MON, 8), wall(MON, 17))], [], "PRODUCTION")
    res = engine.evaluate(plan, [_a(8, 0, 9, 0, "ON_QUEUE")], [], ACTS, window_start=wall(MON, 0), window_end=wall(MON, 9))
    assert res.days[MON].scheduled == 3600 and res.days[MON].adherence_pct == 100.0


# ================================================================== 2. planificador y API
@pytest.fixture
def agent_emp(make_employee):
    emp = make_employee("SV", hire_date=date(2026, 3, 1))
    ScheduleAssignment.objects.create(employee=emp, definition=DAY, effective_start_date=date(2026, 9, 1))
    AgentMembership.objects.create(group=AgentGroup.objects.get(code="GENERAL"), employee=emp)
    return emp


def _approved_ap(emp, folio="APJ-2026-900001"):
    return PersonnelAction.objects.create(folio=folio, action_type=ActionType.objects.get(code="AP_JUSTIFICACION_TIEMPO"),
                                          employee=emp, effective_date=MON, justification="Permiso", status="APPROVED",
                                          content_hash="0" * 64)


def test_planner_segments_inside_the_container(api, wfm_user, agent_emp):
    api.force_login(wfm_user)
    code = agent_emp.employee_code
    r = api.post(f"{H}/segments/", {"employee_code": code, "shift_date": "2026-10-05", "start": "10:00", "end": "10:15", "activity": "BREAK"}, format="json")
    assert r.status_code == 201, r.json()
    seg = ScheduleSegment.objects.get(pk=r.json()["segment"]["id"])
    assert seg.assignment.employee_id == agent_emp.pk and seg.minutes == 15
    r = api.post(f"{H}/segments/", {"employee_code": code, "shift_date": "2026-10-05", "start": "16:45", "end": "17:30", "activity": "BREAK"}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "outside_container"
    r = api.post(f"{H}/segments/", {"employee_code": code, "shift_date": "2026-10-05", "start": "10:10", "end": "10:40", "activity": "COACHING"}, format="json")
    assert r.status_code == 409 and "Break programado" in r.json()["detail"]
    r = api.post(f"{H}/segments/", {"employee_code": code, "shift_date": "2026-10-04", "start": "10:00", "end": "10:15", "activity": "BREAK"}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "no_container"  # domingo: descanso
    r = api.patch(f"{H}/segments/{seg.pk}/", {"start": "10:30", "end": "10:45"}, format="json")
    assert r.status_code == 200 and r.json()["segment"]["start"].endswith("10:30:00")
    plan = api.get(f"{H}/planner/?date=2026-10-05&employee={code}").json()
    row = plan["rows"][0]
    assert [b["activity"] for b in row["plan"]] == ["PRODUCTION", "BREAK", "PRODUCTION"]
    assert any("60 min de almuerzo" in w for w in row["warnings"])
    bulk = api.post(f"{H}/segments/bulk/", {"employee_codes": [code], "date_from": "2026-10-05", "date_to": "2026-10-11",
                                            "start": "12:00", "end": "13:00", "activity": "MEAL"}, format="json")
    assert bulk.status_code == 201 and bulk.json()["created"] == 5 and bulk.json()["rest_days"] == 2
    assert api.delete(f"{H}/segments/{seg.pk}/").status_code == 200


def test_overnight_container_places_segments_on_the_next_calendar_day(api, wfm_user, make_employee):
    emp = make_employee("SV", hire_date=date(2026, 3, 1))
    ScheduleAssignment.objects.create(employee=emp, definition=NIGHT, effective_start_date=date(2026, 9, 1))
    api.force_login(wfm_user)
    r = api.post(f"{H}/segments/", {"employee_code": emp.employee_code, "shift_date": "2026-10-05", "start": "02:00", "end": "02:30",
                                    "activity": "BREAK"}, format="json")
    assert r.status_code == 201, r.json()
    assert r.json()["segment"]["start"] == "2026-10-06T02:00:00" and r.json()["segment"]["shift_date"] == "2026-10-05"


def _acd(emp, plan):
    statuses = {s.code: s for s in PrimaryStatus.objects.all()}
    group = AgentGroup.objects.get(code="GENERAL")
    start = datetime(MON.year, MON.month, MON.day, plan[0][2], plan[0][3], tzinfo=SV)
    end = datetime(MON.year, MON.month, MON.day, plan[-1][4], plan[-1][5], tzinfo=SV)
    session = AgentSession.objects.create(employee=emp, group=group, login_at=start, logout_at=end, logout_source="AGENT")
    for code, aux, h0, m0, h1, m1 in plan:
        s = datetime(MON.year, MON.month, MON.day, h0, m0, tzinfo=SV)
        e = datetime(MON.year, MON.month, MON.day, h1, m1, tzinfo=SV)
        StatusSegment.objects.create(employee=emp, session=session, primary_status=statuses[code], group=group, division=group.division,
                                     aux_code=AuxCode.objects.get(code=aux) if aux else None, start_at=s, end_at=e,
                                     duration_ms=(e - s) // timedelta(milliseconds=1))


def test_report_detail_and_stored_results(api, wfm_user, employee_user, agent_emp):
    for start, end, act in (("10:00", "10:15", "BREAK"), ("12:00", "13:00", "MEAL")):
        ScheduleSegment.objects.create(employee=agent_emp, shift_date=MON, start_at=wall(MON, *map(int, start.split(":"))),
                                       end_at=wall(MON, *map(int, end.split(":"))), activity=ActivityType.objects.get(code=act))
    _acd(agent_emp, [
        ("ON_QUEUE", None, 7, 50, 10, 0),
        ("BREAK", "BREAK_STD", 10, 0, 10, 20),
        ("ON_QUEUE", None, 10, 20, 12, 0),
        ("MEAL", "LUNCH", 12, 0, 13, 0),
        ("BUSY", "ACW", 13, 0, 14, 0),
        ("ON_QUEUE", None, 14, 0, 16, 30),
    ])
    api.force_login(wfm_user)
    code = agent_emp.employee_code
    rep = api.get(f"{H}/report/?from=2026-10-05&to=2026-10-05&employee={code}").json()
    t = rep["rows"][0]["totals"]
    assert t["scheduled"] == 540 * 60 and t["in_adherence"] == 505 * 60 and t["out_of_adherence"] == 35 * 60
    assert t["unpaid_excess"] == 10 * 60 and t["secondary_paid"] == 60 * 60 and t["billable"] == (120 + 100 + 60 + 150) * 60
    assert rep["rows"][0]["deviation_counts"] == {"UNPAID_EXCESS_LOGIN": 1, "OUT_OF_ADHERENCE": 2}
    det = api.get(f"{H}/detail/?employee={code}&date=2026-10-05").json()
    assert [d["kind"] for d in det["deviations"]] == ["UNPAID_EXCESS_LOGIN", "OUT_OF_ADHERENCE", "OUT_OF_ADHERENCE"]
    assert det["deviations"][2]["actual"].startswith("Sin sesión") and len(det["plan"]) == 5

    # Justificación con AP aprobada: el exceso de 07:50 deja de ser Unpaid Excess Login.
    pending = PersonnelAction.objects.create(folio="APJ-2026-900000", action_type=ActionType.objects.get(code="AP_JUSTIFICACION_TIEMPO"),
                                             employee=agent_emp, effective_date=MON, justification="x", status="PENDING",
                                             content_hash="0" * 64)
    r = api.post(f"{H}/exceptions/", {"employee_code": code, "folio": pending.folio, "start": "2026-10-05T07:45", "end": "2026-10-05T08:00",
                                      "reason": "Ingreso anticipado autorizado"}, format="json")
    assert r.status_code == 400 and "aprobada" in r.json()["errors"]["folio"]
    ap = _approved_ap(agent_emp)
    r = api.post(f"{H}/exceptions/", {"employee_code": code, "folio": ap.folio, "start": "2026-10-05T07:45", "end": "2026-10-05T08:00",
                                      "reason": "Ingreso anticipado autorizado", "is_paid": True}, format="json")
    assert r.status_code == 201, r.json()
    t = api.get(f"{H}/report/?from=2026-10-05&employee={code}").json()["rows"][0]["totals"]
    assert t["unpaid_excess"] == 0 and t["justified"] == 10 * 60

    r = api.post(f"{H}/compute/", {"from": "2026-10-05", "to": "2026-10-05", "employee": code}, format="json")
    assert r.status_code == 200 and r.json()["stored"] == 1, r.json()
    day = AdherenceDay.objects.get(employee=agent_emp, shift_date=MON)
    assert float(day.adherence_pct) == 93.52 and Deviation.objects.filter(day=day).count() == 2
    with connection.cursor() as cursor:
        cursor.execute("SELECT AdherencePct, UnpaidExcessLoginMinutes, PayPeriod FROM dbo.vw_AdhAdherenceDay WHERE EmployeeId = %s", [code])
        pct, excess, period = cursor.fetchone()
        assert float(pct) == 93.52 and float(excess) == 0 and period
        cursor.execute("SELECT DeviationLabel, ScheduledActivity, ActualPrimaryStatus FROM dbo.vw_AdhDeviation WHERE EmployeeId = %s ORDER BY StartLocal", [code])
        assert cursor.fetchall() == [("Out of Adherence", "PRODUCTION", "Break"), ("Out of Adherence", "PRODUCTION", None)]
        cursor.execute("SELECT COUNT(*) FROM dbo.vw_AdhScheduleSegment WHERE EmployeeId = %s", [code])
        assert cursor.fetchone()[0] == 2

    api.force_login(employee_user)
    assert api.get(f"{H}/report/?from=2026-10-05&employee={code}").status_code == 403


def test_closed_cutoff_freezes_planning(api, wfm_user, hr_user, agent_emp):
    PayCycle.objects.filter(code="SV_QUINCENAL").update(is_default=False)
    PayCycle.objects.filter(code="SV_QUINCENAL_BPO").update(is_default=True)
    agent_emp.pay_frequency = "BIWEEKLY"
    agent_emp.save()
    cut = AttendanceCutoff.objects.get(cycle__code="SV_QUINCENAL_BPO", code="C-2026-10-Q1")  # 25/09 – 09/10
    api.force_login(hr_user)
    assert api.post(f"/api/v1/scheduling/cutoffs/{cut.pk}/close/").status_code == 200
    api.force_login(wfm_user)
    r = api.post(f"{H}/segments/", {"employee_code": agent_emp.employee_code, "shift_date": "2026-10-05", "start": "10:00", "end": "10:15",
                                    "activity": "BREAK"}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "cutoff_closed"


def test_activity_catalog_management(api, wfm_user, hr_user):
    api.force_login(wfm_user)
    cat = api.get(f"{H}/catalogs/").json()
    assert {a["code"] for a in cat["activities"]} >= {"PRODUCTION", "BREAK", "MEAL", "TRAINING", "COACHING", "BACK_OFFICE"}
    assert next(a for a in cat["activities"] if a["code"] == "PRODUCTION")["is_default"] and cat["can_manage"]
    r = api.post(f"{H}/activities/", {"code": "CHAT", "name": "Chats", "category": "PRODUCTION", "color": "#0ea5e9", "is_billable": True,
                                      "rules": [{"primary_status": "ON_QUEUE", "role": "PRIMARY"}, {"primary_status": "BUSY", "aux_code": "LUNCH"}]},
                 format="json")
    assert r.status_code == 400 and "es de Meal" in r.json()["errors"]["rules.1"]
    r = api.post(f"{H}/activities/", {"code": "CHAT", "name": "Chats", "category": "PRODUCTION", "color": "#0ea5e9", "is_billable": True,
                                      "rules": [{"primary_status": "ON_QUEUE", "role": "PRIMARY"}, {"primary_status": "BUSY", "aux_code": "ACW", "role": "SECONDARY"}]},
                 format="json")
    assert r.status_code == 201, r.json()
    r = api.patch(f"{H}/activities/CHAT/", {"is_default": True}, format="json")
    assert r.status_code == 200 and ActivityType.objects.get(is_default=True).code == "CHAT"
    r = api.patch(f"{H}/activities/CHAT/", {"is_default": False}, format="json")
    assert r.status_code == 400
    api.patch(f"{H}/activities/PRODUCTION/", {"is_default": True}, format="json")
    api.force_login(hr_user)  # RRHH ve WFM pero no administra
    assert api.get(f"{H}/catalogs/").status_code == 200
    assert api.post(f"{H}/activities/", {"code": "X"}, format="json").status_code == 403


def test_sql_50070_segments_cannot_overlap(agent_emp):
    act = ActivityType.objects.get(code="BREAK")
    ScheduleSegment.objects.create(employee=agent_emp, shift_date=MON, start_at=wall(MON, 10), end_at=wall(MON, 10, 15), activity=act)
    with pytest.raises(DatabaseError, match="50070"), transaction.atomic():
        ScheduleSegment.objects.create(employee=agent_emp, shift_date=MON, start_at=wall(MON, 10, 10), end_at=wall(MON, 10, 30), activity=act)


def test_sql_50071_justification_needs_an_approved_ap_of_the_same_employee(make_employee, agent_emp):
    other = make_employee("SV", hire_date=date(2026, 3, 1))
    ap = _approved_ap(other, "APJ-2026-900002")
    with pytest.raises(DatabaseError, match="50071"), transaction.atomic():
        AdherenceException.objects.create(employee=agent_emp, personnel_action=ap, start_at=wall(MON, 8), end_at=wall(MON, 9), reason="x")
