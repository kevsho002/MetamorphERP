"""Fase 18: granularidad al segundo, cadena de mando centralizada en el roster y audit trail por agente y fecha."""

from datetime import date, datetime

import pytest
from django.db import DatabaseError, connection, transaction

from apps.acd.models import AgentGroup, AgentMembership
from apps.adherence.models import ActivityType, AdherenceDay, ScheduleSegment
from apps.operations.models import OperationalLeader
from apps.personnel_actions.models import ActionType, PersonnelAction
from apps.roster.models import RosterAssignment, RosterAttribute
from apps.scheduling.models import ScheduleAssignment

pytestmark = pytest.mark.django_db
H = "/api/v1/adherence"
L = "/api/v1/roster/hierarchy/leaders"
MON = date(2026, 10, 5)  # lunes pasado
DAY = {"days": {d: {"start": "08:00", "end": "17:00", "lunch_minutes": 60} for d in ("mon", "tue", "wed", "thu", "fri")}}


@pytest.fixture
def agent(api, wfm_user, make_employee):
    api.force_login(wfm_user)
    emp = make_employee("SV", hire_date=date(2026, 9, 1))
    ScheduleAssignment.objects.create(employee=emp, definition=DAY, effective_start_date=date(2026, 9, 1))
    AgentMembership.objects.create(group=AgentGroup.objects.get(code="GENERAL"), employee=emp)
    return emp


@pytest.fixture
def chain(api, make_employee, agent):
    """Director → Manager → Supervisor → Team Manager registrados desde el ROSTER; el agente con su TM en el roster."""
    people = {k: make_employee("SV", first_name=k, last_name="Líder") for k in ("Dir", "Mgr", "Sup", "Tm")}
    ids = {}
    parent = None
    for key, level in (("Dir", "OPS_DIRECTOR"), ("Mgr", "OPS_MANAGER"), ("Sup", "ACCOUNT_SUPERVISOR"), ("Tm", "TEAM_MANAGER")):
        r = api.post(f"{L}/", {"level": level, "employee_code": people[key].employee_code, "reports_to": parent}, format="json")
        assert r.status_code == 201, r.json()
        parent = ids[key] = r.json()["leader"]["id"]
    tm = OperationalLeader.objects.get(pk=ids["Tm"])
    RosterAssignment.objects.create(employee=agent, attribute=RosterAttribute.objects.get(code="team_manager"), value=tm.roster_item.code,
                                    item=tm.roster_item, effective_start=date(2026, 9, 1), recorded_by="wfm.test", reason="Alta en equipo")
    return {"people": people, "ids": ids}


# ================================================================== 1. segundos
def test_segments_and_justifications_keep_seconds(api, agent):
    code = agent.employee_code
    r = api.post(f"{H}/segments/", {"employee_code": code, "shift_date": "2026-10-05", "start": "10:00:30", "end": "10:15:45",
                                    "activity": "BREAK"}, format="json")
    assert r.status_code == 201, r.json()
    seg = r.json()["segment"]
    assert (seg["start"], seg["end"], seg["seconds"]) == ("2026-10-05T10:00:30", "2026-10-05T10:15:45", 915)
    assert seg["minutes"] == 15.25
    assert ScheduleSegment.objects.get(pk=seg["id"]).seconds == 915
    # El plan resultante y el cálculo van al segundo: Producción hasta 10:00:30 y desde 10:15:45.
    day = api.get(f"{H}/planner/", {"date": "2026-10-05", "employee": code}).json()["rows"][0]
    blocks = [(b["activity"], b["start"][11:], b["end"][11:], b["seconds"]) for b in day["plan"]]
    assert ("PRODUCTION", "08:00:00", "10:00:30", 7230) in blocks and ("BREAK", "10:00:30", "10:15:45", 915) in blocks
    assert r.json()["refresh"]["metrics"]["scheduled"] == 9 * 3600  # 08:00–17:00 exactos
    # Mínimo 1 minuto (60 s), ya no 5 minutos redondeados.
    r = api.post(f"{H}/segments/", {"employee_code": code, "shift_date": "2026-10-05", "start": "11:00:00", "end": "11:00:59",
                                    "activity": "BREAK"}, format="json")
    assert r.status_code == 400 and "1 min" in r.json()["errors"]["end"]
    r = api.post(f"{H}/segments/", {"employee_code": code, "shift_date": "2026-10-05", "start": "11:00:00", "end": "11:01:00",
                                    "activity": "BREAK"}, format="json")
    assert r.status_code == 201 and r.json()["segment"]["seconds"] == 60
    # Hora inválida.
    r = api.post(f"{H}/segments/", {"employee_code": code, "shift_date": "2026-10-05", "start": "11:00:61", "end": "11:05",
                                    "activity": "BREAK"}, format="json")
    assert r.status_code == 400 and "HH:MM:SS" in r.json()["errors"]["start"]
    # Justificación con segundos (antes se truncaba al minuto).
    ap = PersonnelAction.objects.create(folio="APJ-2026-918001", action_type=ActionType.objects.get(code="AP_JUSTIFICACION_TIEMPO"),
                                        employee=agent, effective_date=MON, justification="Permiso", status="APPROVED", content_hash="0" * 64)
    r = api.post(f"{H}/exceptions/", {"employee_code": code, "folio": ap.folio, "start": "2026-10-05T07:59:30",
                                      "end": "2026-10-05T08:00:15", "reason": "Ingreso tardío", "is_paid": True}, format="json")
    assert r.status_code == 201, r.json()
    assert (r.json()["exception"]["start"], r.json()["exception"]["end"]) == ("2026-10-05T07:59:30", "2026-10-05T08:00:15")


def test_sql_whole_seconds_and_views_count_seconds(api, agent):
    r = api.post(f"{H}/segments/", {"employee_code": agent.employee_code, "shift_date": "2026-10-05", "start": "10:00:50",
                                    "end": "10:06:10", "activity": "BREAK"}, format="json")
    assert r.status_code == 201, r.json()
    seg_id = r.json()["segment"]["id"]
    with connection.cursor() as c:
        c.execute("SELECT DurationSeconds, Minutes FROM dbo.vw_AdhScheduleSegment WHERE SegmentId = %s", [seg_id])
        seconds, minutes = c.fetchone()
    assert seconds == 320 and float(minutes) == pytest.approx(5.3333, abs=1e-4)  # DATEDIFF(MINUTE) daba 6
    # SQL Server guarda segundos enteros: una fracción se rechaza.
    with pytest.raises(DatabaseError, match="whole_seconds"), transaction.atomic():
        ScheduleSegment.objects.filter(pk=seg_id).update(start_at=datetime(2026, 10, 5, 10, 0, 50, 500000))


def test_activity_duration_and_grid_snap_in_seconds(api, agent):
    r = api.patch(f"{H}/activities/BREAK/", {"default_seconds": 630}, format="json")
    assert r.status_code == 200 and r.json()["activity"]["default_seconds"] == 630
    assert api.patch(f"{H}/activities/BREAK/", {"default_seconds": 30}, format="json").status_code == 400
    r = api.patch(f"{H}/activities/BREAK/", {"default_minutes": 2}, format="json")  # compatibilidad
    assert r.status_code == 200 and r.json()["activity"]["default_seconds"] == 120
    assert ActivityType.objects.get(code="MEAL").default_seconds == 3600  # migrado de 60 min
    r = api.put(f"{H}/grid/settings/", {"interval_minutes": 15, "snap_seconds": 1}, format="json")
    assert r.status_code == 200 and r.json()["snap_seconds"] == 1
    snaps = [s["value"] for s in r.json()["snaps"]]
    assert snaps[:3] == [1, 15, 30]
    assert api.put(f"{H}/grid/settings/", {"snap_seconds": 7}, format="json").status_code == 400


# ================================================================== 2. cadena de mando en el roster
def test_chain_of_command_lives_in_the_roster(api, hr_user, chain, agent):
    people, ids = chain["people"], chain["ids"]
    # Ya no hay API de líderes en operaciones (WFM): todo pasa por el roster.
    assert api.get("/api/v1/operations/leaders/").status_code == 404
    r = api.get(f"/api/v1/roster/employees/{agent.employee_code}/", {"as_of": "2026-10-05"})
    assert r.status_code == 200
    as_agent = r.json()["chain_of_command"]["as_agent"]
    assert as_agent["TEAM_MANAGER"]["employee_code"] == people["Tm"].employee_code
    assert as_agent["OPS_DIRECTOR"]["employee_code"] == people["Dir"].employee_code
    r = api.get(f"/api/v1/roster/employees/{people['Sup'].employee_code}/", {"as_of": "2026-10-05"})
    roles = r.json()["chain_of_command"]["roles"]
    assert roles[0]["level"] == "ACCOUNT_SUPERVISOR" and roles[0]["subordinates"] == 1
    assert [c["level"] for c in roles[0]["chain"]] == ["OPS_MANAGER", "OPS_DIRECTOR"]
    # El reporte del roster trae la cadena y filtra por ella.
    r = api.get("/api/v1/roster/report/", {"from": "2026-10-05", "supervisor": people["Sup"].employee_code})
    assert r.status_code == 200, r.json()
    rows = r.json()["results"]
    assert [x["employee"]["employee_code"] for x in rows] == [agent.employee_code]
    assert rows[0]["chain_of_command"]["ACCOUNT_SUPERVISOR"]["employee_code"] == people["Sup"].employee_code
    # RRHH (roster.manage) también administra la cadena desde el roster.
    api.force_login(hr_user)
    r = api.patch(f"{L}/{ids['Tm']}/", {"client": ""}, format="json")
    assert r.status_code == 200, r.json()
    from apps.system.models import AuditEvent

    assert AuditEvent.objects.filter(action="ops_leader_updated", category="ROSTER").exists()


# ================================================================== 3. audit trail
def test_audit_trail_of_an_agent_on_a_date(api, employee_user, chain, agent):
    code = agent.employee_code
    payload = {"from": "2026-10-05", "to": "2026-10-05", "employee": code, "reconcile": False}  # sin conciliar asistencia (Fase 19)
    assert api.post(f"{H}/compute/", payload, format="json").status_code == 200
    r = api.post(f"{H}/segments/", {"employee_code": code, "shift_date": "2026-10-05", "start": "12:00", "end": "13:00",
                                    "activity": "MEAL"}, format="json")
    seg_id = r.json()["segment"]["id"]
    assert api.patch(f"{H}/segments/{seg_id}/", {"start": "12:30:15", "end": "13:30:15"}, format="json").status_code == 200
    other = api.post(f"{H}/segments/", {"employee_code": code, "shift_date": "2026-10-06", "start": "10:00", "end": "10:15",
                                        "activity": "BREAK"}, format="json")
    assert other.status_code == 201
    assert api.delete(f"{H}/segments/{seg_id}/").status_code == 200

    r = api.get(f"{H}/grid/audit/", {"employee": code, "date": "2026-10-05"})
    assert r.status_code == 200, r.json()
    body = r.json()
    actions = [e["action"] for e in body["entries"]]
    for expected in ("adh_segment_created", "adh_segment_updated", "adh_segment_deleted", "adh_day_recomputed", "adh_computed",
                     "roster_change"):
        assert expected in actions, (expected, actions)
    # Más reciente primero; el movimiento guarda el antes y el después al segundo.
    assert body["entries"][0]["at"] >= body["entries"][-1]["at"]
    moved = next(e for e in body["entries"] if e["action"] == "adh_segment_updated")
    assert moved["before"]["start"] == "2026-10-05T12:00:00" and moved["after"]["start"] == "2026-10-05T12:30:15"
    assert moved["actor"] == "wfm.test" and moved["kind"] == "change"
    # Lo del 06/10 no aparece en la línea del 05/10.
    assert not any("06/10/2026" in e["summary"] for e in body["entries"])
    assert body["hierarchy"]["TEAM_MANAGER"]["employee_code"] == chain["people"]["Tm"].employee_code
    assert AdherenceDay.objects.filter(employee=agent, shift_date=MON).exists()
    api.force_login(employee_user)
    assert api.get(f"{H}/grid/audit/", {"employee": code, "date": "2026-10-05"}).status_code == 403
