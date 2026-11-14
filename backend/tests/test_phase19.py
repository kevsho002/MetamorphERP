"""Fase 19: Lateness bloqueado, Unjustified Absence con Legal Benefit Lunch, categorías del Time Utilization,
segmentos que exigen AP y ventana flotante de detalle con la cola de aprobación de WFM."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.db import DatabaseError, connection

from apps.acd import services as acd
from apps.acd.models import AgentGroup, AgentMembership, AgentSession, PrimaryStatus, StatusSegment
from apps.adherence.models import ActivityType, AdherenceException, ChangeRequest, ScheduleSegment, UtilizationCategory
from apps.adherence.services import now_local
from apps.operations.models import OperationalLeader
from apps.personnel_actions.models import ActionType, PersonnelAction
from apps.roster.models import RosterAssignment, RosterAttribute
from apps.scheduling.models import ScheduleAssignment
from apps.system.models import AuditEvent

pytestmark = pytest.mark.django_db
H = "/api/v1/adherence"
SV = ZoneInfo("America/El_Salvador")
MON = date(2026, 10, 5)  # lunes pasado
DAY = {"days": {d: {"start": "08:00", "end": "17:00", "lunch_minutes": 60} for d in ("mon", "tue", "wed", "thu", "fri")}}
_FOLIO = iter(range(919001, 919999))


def _agent(make_employee, definition=DAY, **kw):
    emp = make_employee("SV", hire_date=date(2026, 9, 1), **kw)
    ScheduleAssignment.objects.create(employee=emp, definition=definition, effective_start_date=date(2026, 9, 1))
    AgentMembership.objects.create(group=AgentGroup.objects.get(code="GENERAL"), employee=emp)
    return emp


def _ap(emp, status="APPROVED") -> PersonnelAction:
    return PersonnelAction.objects.create(folio=f"APJ-2026-{next(_FOLIO)}", action_type=ActionType.objects.get(code="AP_JUSTIFICACION_TIEMPO"),
                                          employee=emp, effective_date=MON, justification="Respaldo", status=status, content_hash="0" * 64)


def _session(emp, d, h0, m0, h1, m1):
    st = PrimaryStatus.objects.get(code="ON_QUEUE")
    group = AgentGroup.objects.get(code="GENERAL")
    s, e = datetime(d.year, d.month, d.day, h0, m0, tzinfo=SV), datetime(d.year, d.month, d.day, h1, m1, tzinfo=SV)
    session = AgentSession.objects.create(employee=emp, group=group, login_at=s, logout_at=e, logout_source="AGENT")
    StatusSegment.objects.create(employee=emp, session=session, primary_status=st, group=group, division=group.division, start_at=s,
                                 end_at=e, duration_ms=(e - s) // timedelta(milliseconds=1))


def _seg(api, emp, start, end, activity, **extra):
    return api.post(f"{H}/segments/", {"employee_code": emp.employee_code, "shift_date": "2026-10-05", "start": start, "end": end,
                                       "activity": activity, **extra}, format="json")


@pytest.fixture
def agent(api, wfm_user, make_employee):
    api.force_login(wfm_user)
    return _agent(make_employee)


# ================================================================== 3. categorías del Time Utilization
def test_time_utilization_categories_and_dropdown_payload(api, agent):
    cats = {c.code: c for c in UtilizationCategory.objects.all()}
    assert {"WFM_REGULAR", "WFM_OUT_OF_PHONE", "WFM_UNLOGGED", "TD_TRAINING", "IT_SYSTEM_ISSUES", "HR_PAID", "HR_UNPAID", "ATTENDANCE"} <= set(cats)
    assert ActivityType.objects.filter(utilization_category=cats["HR_PAID"]).count() == 22
    assert ActivityType.objects.filter(utilization_category=cats["HR_UNPAID"]).count() == 24
    assert ActivityType.objects.filter(utilization_category=cats["IT_SYSTEM_ISSUES"]).count() == 22
    sick = ActivityType.objects.get(code="HRP_PAID_SICK_TIME")
    assert (sick.requires_ap, sick.requires_acd_login, sick.allows_full_day, sick.is_paid) == (True, False, True, True)
    chat = ActivityType.objects.get(code="OPW_CHAT")  # trabajo fuera del teléfono: con sesión (reglas de Back Office)
    assert chat.requires_acd_login and chat.status_rules.exists() and chat.is_billable
    assert ActivityType.objects.get(code="BREAK").utilization_category.code == "WFM_REGULAR"
    grid = api.get(f"{H}/grid/", {"date": "2026-10-05", "group": "GENERAL"}).json()
    codes = {a["code"] for a in grid["toolbox"]}
    assert "LATENESS" not in codes and "UNJUSTIFIED_ABSENCE" not in codes and "HRP_PAID_SICK_TIME" in codes
    assert grid["categories"][0]["code"] == "WFM_REGULAR"
    tool = next(a for a in grid["toolbox"] if a["code"] == "HRP_PAID_SICK_TIME")
    assert tool["utilization_category"]["code"] == "HR_PAID" and tool["requires_ap"] is True
    cat = api.get(f"{H}/catalogs/").json()
    assert {c["code"] for c in cat["utilization_categories"]} == {c.code for c in cats.values()}
    # Editar la matriz desde el catálogo.
    r = api.patch(f"{H}/activities/OPW_EMAIL/", {"requires_ap": True, "review_areas": ["wfm", "it"], "client_paid": "OPTIONAL"}, format="json")
    assert r.status_code == 200, r.json()
    assert (r.json()["activity"]["requires_ap"], r.json()["activity"]["review_areas"], r.json()["activity"]["client_paid"]) == (True, ["WFM", "IT"], "OPTIONAL")
    r = api.post(f"{H}/activities/", {"code": "OFFSITE", "name": "Evento externo", "requires_acd_login": False,
                                      "utilization_category": "WFM_UNLOGGED"}, format="json")
    assert r.status_code == 201, r.json()  # sin sesión ACD: no exige estados
    assert api.patch(f"{H}/activities/OFFSITE/", {"allows_partial": False, "allows_full_day": False}, format="json").status_code == 400


# ================================================================== 4. AP obligatoria
def test_segments_that_require_an_approved_ap(api, agent, make_employee):
    r = _seg(api, agent, "10:00", "11:00", "HRP_MEDICAL_APPOINTMENT")
    assert r.status_code == 409 and r.json()["code"] == "ap_required"
    assert _seg(api, agent, "10:00", "11:00", "HRP_MEDICAL_APPOINTMENT", folio=_ap(agent, "PENDING").folio).status_code == 400
    assert _seg(api, agent, "10:00", "11:00", "HRP_MEDICAL_APPOINTMENT", folio=_ap(make_employee()).folio).status_code == 400
    ap = _ap(agent)
    r = _seg(api, agent, "10:00", "11:00", "HRP_MEDICAL_APPOINTMENT", folio=ap.folio)
    assert r.status_code == 201, r.json()
    assert r.json()["segment"]["folio"] == ap.folio and r.json()["segment"]["requires_ap"] is True
    # Operativos: WFM los coloca libremente.
    assert _seg(api, agent, "15:00", "15:15", "BREAK").status_code == 201
    # Día completo y cambio mayor (≥ 4 h por defecto) exigen AP; un permiso de día completo con AP sí.
    r = _seg(api, agent, "11:00", "15:00", "TRAINING")
    assert r.status_code == 409 and "Cambio mayor" in r.json()["detail"]
    assert _seg(api, agent, "11:00", "15:00", "TRAINING", folio=ap.folio).status_code == 201
    other = _agent(make_employee)
    r = _seg(api, other, "08:00", "17:00", "HRP_PAID_SICK_TIME")
    assert r.status_code == 409 and r.json()["code"] == "ap_required"
    assert _seg(api, other, "08:00", "17:00", "BREAK", folio=_ap(other).folio).json()["code"] == "full_day_not_allowed"
    assert _seg(api, other, "08:00", "17:00", "HRP_PAID_SICK_TIME", folio=_ap(other).folio).status_code == 201
    assert _seg(api, other, "08:00", "17:00", "HRU_ATTRITION", folio=_ap(other).folio).status_code == 409  # traslape
    # La programación masiva no acepta actividades con AP; las del sistema no se colocan a mano.
    r = api.post(f"{H}/segments/bulk/", {"employee_codes": [agent.employee_code], "date_from": "2026-10-06", "start": "10:00",
                                         "end": "11:00", "activity": "HRP_JURY_DUTY"}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "ap_required"
    assert _seg(api, agent, "16:00", "16:30", "LATENESS").status_code == 400


# SQL Server protege las reglas aunque se salte el servicio. Un error de trigger aborta la transacción: uno por prueba.
def _raw_segment(emp, code, **extra):
    return ScheduleSegment.objects.create(employee=emp, shift_date=MON, start_at=datetime(2026, 10, 5, 16),
                                          end_at=datetime(2026, 10, 5, 16, 30), activity=ActivityType.objects.get(code=code), **extra)


def test_sql_50072_activity_requires_an_approved_ap(agent):
    with pytest.raises(DatabaseError, match="50072"):
        _raw_segment(agent, "HRU_WEDDING")


def test_sql_50074_attendance_activities_only_by_the_system(agent):
    with pytest.raises(DatabaseError, match="50074"):
        _raw_segment(agent, "LATENESS")


def test_sql_50073_locked_segment_cannot_be_deleted(agent):
    seg = _raw_segment(agent, "LATENESS", origin="SYSTEM", is_locked=True)
    with pytest.raises(DatabaseError, match="50073"), connection.cursor() as c:
        c.execute("DELETE FROM wfm.adh_schedule_segment WHERE id = %s", [seg.pk])


def test_sql_50073_locked_segment_cannot_be_moved(agent):
    seg = _raw_segment(agent, "UNJUSTIFIED_ABSENCE", origin="SYSTEM", is_locked=True)
    ScheduleSegment.objects.filter(pk=seg.pk).update(notes="Observación")  # sin mover: permitido
    with pytest.raises(DatabaseError, match="50073"):
        ScheduleSegment.objects.filter(pk=seg.pk).update(end_at=datetime(2026, 10, 5, 16, 20))


# ================================================================== 1. lateness bloqueado
def test_late_acd_login_inserts_a_locked_lateness_that_can_only_be_replaced(api, wfm_user, make_employee):
    now = now_local()
    start = (now - timedelta(minutes=50)).replace(second=0)
    end = start + timedelta(hours=4)
    every = {d: {"start": f"{start:%H:%M}", "end": f"{end:%H:%M}", "lunch_minutes": 0}
             for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
    emp = _agent(make_employee, {"days": every})
    acd.login(emp)
    late = ScheduleSegment.objects.get(employee=emp, activity__system_role="LATENESS")
    assert late.is_locked and late.origin == "SYSTEM" and late.start_at == start
    assert 49 * 60 <= late.seconds <= 51 * 60
    assert AuditEvent.objects.filter(action="adh_lateness_detected", target_id=emp.employee_code).exists()
    # Un segundo inicio de sesión en el mismo turno no duplica el lateness.
    acd.logout(emp)
    acd.login(emp)
    assert ScheduleSegment.objects.filter(employee=emp, activity__system_role="LATENESS").count() == 1
    api.force_login(wfm_user)
    r = api.delete(f"{H}/segments/{late.pk}/")
    assert r.status_code == 409 and r.json()["code"] == "locked"
    assert api.patch(f"{H}/segments/{late.pk}/", {"start": f"{start:%H:%M:%S}"}, format="json").json()["code"] == "locked"
    # Reemplazo: exige AP aprobada; un tramo parcial deja el resto bloqueado.
    r = api.post(f"{H}/segments/{late.pk}/replace/", {"activity": "ITP_SKYCOM_HARDWARE"}, format="json")
    assert r.status_code == 400 and "folio" in r.json()["errors"]
    ap = _ap(emp)
    mid = start + timedelta(minutes=20)
    r = api.post(f"{H}/segments/{late.pk}/replace/", {"activity": "ITP_SKYCOM_HARDWARE", "folio": ap.folio, "end": f"{mid:%H:%M:%S}",
                                                      "notes": "Falla de equipo al iniciar"}, format="json")
    assert r.status_code == 200, r.json()
    new = r.json()["segment"]
    assert (new["activity"], new["folio"], new["start"][11:], new["end"][11:]) == ("ITP_SKYCOM_HARDWARE", ap.folio, f"{start:%H:%M:%S}", f"{mid:%H:%M:%S}")
    rest = ScheduleSegment.objects.get(employee=emp, activity__system_role="LATENESS")
    assert rest.is_locked and rest.start_at == mid
    trail = api.get(f"{H}/grid/audit/", {"employee": emp.employee_code, "date": late.shift_date.isoformat()}).json()
    actions = {e["action"] for e in trail["entries"]}
    assert {"adh_lateness_detected", "adh_segment_replaced"} <= actions


# ================================================================== 2. ausencia + Legal Benefit Lunch
def test_no_show_becomes_unjustified_absence_with_legal_lunch(api, agent, make_employee):
    _seg(api, agent, "10:00", "10:15", "BREAK")
    _seg(api, agent, "12:30", "13:30", "MEAL")
    late = _agent(make_employee)
    _session(late, MON, 8, 20, 17, 0)
    on_time = _agent(make_employee)
    _session(on_time, MON, 7, 55, 17, 0)
    leave = _agent(make_employee)
    AdherenceException.objects.create(employee=leave, personnel_action=_ap(leave), start_at=datetime(2026, 10, 5, 8),
                                      end_at=datetime(2026, 10, 5, 17), reason="Incapacidad")
    gone = _agent(make_employee, employment_status="TERMINATED", termination_date=date(2026, 10, 1))
    r = api.post(f"{H}/attendance/reconcile/", {"date": "2026-10-05", "group": "GENERAL"}, format="json")
    assert r.status_code == 200, r.json()
    out = r.json()
    assert (out["absences"], out["lateness"], out["on_leave"], out["inactive"]) == (1, 1, 1, 1)
    status = {x["employee_code"]: x["status"] for x in out["rows"]}
    assert status[agent.employee_code] == "ABSENT" and status[gone.employee_code] == "INACTIVE" and status[on_time.employee_code] == "PRESENT"
    plan = [(s.activity.code, f"{s.start_at:%H:%M}", f"{s.end_at:%H:%M}", s.is_locked)
            for s in ScheduleSegment.objects.filter(employee=agent).order_by("start_at")]
    # El almuerzo legal queda donde estaba el almuerzo; el break del plan ya no aplica.
    assert plan == [("UNJUSTIFIED_ABSENCE", "08:00", "12:30", True), ("LEGAL_BENEFIT_LUNCH", "12:30", "13:30", True),
                    ("UNJUSTIFIED_ABSENCE", "13:30", "17:00", True)]
    assert [(s.activity.code, f"{s.start_at:%H:%M}", f"{s.end_at:%H:%M}") for s in ScheduleSegment.objects.filter(employee=late)] == \
        [("LATENESS", "08:00", "08:20")]
    assert not ScheduleSegment.objects.filter(employee__in=[leave, gone, on_time]).exists()
    # Idempotente.
    again = api.post(f"{H}/attendance/reconcile/", {"date": "2026-10-05", "group": "GENERAL"}, format="json").json()
    assert (again["absences"], again["lateness"]) == (0, 0)
    # La grilla separa ausentes, permisos e inactivos de la dotación neta.
    grid = api.get(f"{H}/grid/", {"date": "2026-10-05", "group": "GENERAL"}).json()
    s = grid["summary"]
    assert (s["absent"], s["late"], s["on_leave"], s["inactive"]) == (1, 1, 1, 1)
    assert s["net_staff"] == s["with_shift"] - 3
    row = next(x for x in grid["rows"] if x["employee_code"] == agent.employee_code)
    assert row["attendance"] == "ABSENT" and row["metrics"]["in_adherence"] == 3600  # solo el almuerzo legal
    assert row["metrics"]["out_of_adherence"] == 8 * 3600 and row["metrics"]["scheduled_paid"] == 0  # ausencia y almuerzo: no pagados
    # Reemplazar el día de ausencia con un permiso respaldado por AP (todo el turno).
    absence = ScheduleSegment.objects.filter(employee=agent, activity__code="UNJUSTIFIED_ABSENCE").first()
    r = api.post(f"{H}/segments/{absence.pk}/replace/", {"activity": "HRP_PAID_SICK_TIME", "folio": _ap(agent).folio, "scope": "day"},
                 format="json")
    assert r.status_code == 200, r.json()
    assert [(s.activity.code, f"{s.start_at:%H:%M}", f"{s.end_at:%H:%M}") for s in ScheduleSegment.objects.filter(employee=agent)] == \
        [("HRP_PAID_SICK_TIME", "08:00", "17:00")]
    m = r.json()["refresh"]["metrics"]
    assert m["in_adherence"] == 9 * 3600 and m["paid_valid"] == 9 * 3600


# ================================================================== 5. ventana flotante y cola de WFM
@pytest.fixture
def team(api, wfm_user, make_employee, make_user, agent):
    people = {k: make_employee("SV", first_name=k, last_name="Líder") for k in ("Dir", "Mgr", "Sup", "Tm")}
    parent = None
    for key, level in (("Dir", "OPS_DIRECTOR"), ("Mgr", "OPS_MANAGER"), ("Sup", "ACCOUNT_SUPERVISOR"), ("Tm", "TEAM_MANAGER")):
        r = api.post("/api/v1/roster/hierarchy/leaders/", {"level": level, "employee_code": people[key].employee_code, "reports_to": parent},
                     format="json")
        assert r.status_code == 201, r.json()
        parent = r.json()["leader"]["id"]
    tm = OperationalLeader.objects.get(pk=parent)
    RosterAssignment.objects.create(employee=agent, attribute=RosterAttribute.objects.get(code="team_manager"), value=tm.roster_item.code,
                                    item=tm.roster_item, effective_start=date(2026, 9, 1), recorded_by="wfm.test", reason="Equipo")
    return {"agent_user": make_user("agente.p19", "EMPLOYEE", employee=agent),
            "sup_user": make_user("sup.p19", "EMPLOYEE", employee=people["Sup"]),
            "other_user": make_user("otro.p19", "EMPLOYEE")}


def test_floating_window_read_mode_and_wfm_approval_queue(api, wfm_user, make_user, agent, team):
    brk = _seg(api, agent, "10:00", "10:15", "BREAK", notes="Break AM").json()["segment"]
    code = agent.employee_code
    # WFM: edición.
    day = api.get(f"{H}/day/", {"employee": code, "date": "2026-10-05"}).json()
    assert day["mode"] == "edit" and day["role"] == "WFM"
    row = next(x for x in day["table"] if x["segment_id"] == brk["id"])
    assert (row["activity_name"], row["start"][11:], row["end"][11:], row["notes"]) == ("Break programado", "10:00:00", "10:15:00", "Break AM")
    assert any(x["kind"] == "container" for x in day["table"])
    # Agente: lectura + solicitud; otro empleado: sin acceso; supervisor de la cadena: lectura + solicitud.
    api.force_login(team["agent_user"])
    day = api.get(f"{H}/day/", {"employee": code, "date": "2026-10-05"}).json()
    assert (day["mode"], day["role"]) == ("request", "AGENT")
    assert api.patch(f"{H}/segments/{brk['id']}/", {"start": "10:30"}, format="json").status_code == 403
    r = api.post(f"{H}/requests/", {"employee_code": code, "shift_date": "2026-10-05", "kind": "CHANGE", "segment_id": brk["id"],
                                    "start": "10:30:00", "end": "10:45:00", "reason": "Me tocó una llamada larga"}, format="json")
    assert r.status_code == 201, r.json()
    req = r.json()["request"]
    assert req["status"] == "PENDING" and req["requester_role"] == "AGENT" and req["before"]["start"].endswith("10:00:00")
    dup = api.post(f"{H}/requests/", {"employee_code": code, "shift_date": "2026-10-05", "kind": "DELETE", "segment_id": brk["id"],
                                      "reason": "Duplicada"}, format="json")
    assert dup.status_code == 409
    r = api.post(f"{H}/requests/", {"employee_code": code, "shift_date": "2026-10-05", "kind": "ADD", "activity": "HRP_PAID_SICK_TIME",
                                    "start": "08:00", "end": "17:00", "reason": "Estuve incapacitado"}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "ap_flow_required"  # el día completo va por AP
    assert [x["id"] for x in api.get(f"{H}/requests/").json()["results"]] == [req["id"]]
    api.force_login(team["other_user"])
    assert api.get(f"{H}/day/", {"employee": code, "date": "2026-10-05"}).status_code == 403
    assert api.post(f"{H}/requests/{req['id']}/cancel/").status_code == 403
    api.force_login(team["sup_user"])
    day = api.get(f"{H}/day/", {"employee": code, "date": "2026-10-05"}).json()
    assert (day["mode"], day["role"]) == ("request", "SUPERVISOR")
    mine = api.get(f"{H}/my-plan/", {"date": "2026-10-05"}).json()
    assert mine["is_leader"] and code in [x["employee_code"] for x in mine["rows"]]
    r = api.post(f"{H}/requests/", {"employee_code": code, "shift_date": "2026-10-05", "kind": "ADD", "activity": "COACHING",
                                    "start": "15:00", "end": "15:30", "reason": "Coaching de calidad"}, format="json")
    assert r.status_code == 201
    sup_req = r.json()["request"]
    assert api.post(f"{H}/requests/{sup_req['id']}/decide/", {"decision": "APPROVE"}, format="json").status_code == 403
    # WFM resuelve la cola: aprueba (se aplica al plan) y rechaza con comentario.
    api.force_login(wfm_user)
    queue = api.get(f"{H}/requests/", {"status": "PENDING"}).json()
    assert queue["pending"] == 2 and queue["can_decide"]
    r = api.post(f"{H}/requests/{req['id']}/decide/", {"decision": "APPROVE", "comment": "Ok"}, format="json")
    assert r.status_code == 200, r.json()
    seg = ScheduleSegment.objects.get(pk=brk["id"])
    assert (f"{seg.start_at:%H:%M}", f"{seg.end_at:%H:%M}", seg.origin) == ("10:30", "10:45", "REQUEST")
    assert api.post(f"{H}/requests/{sup_req['id']}/decide/", {"decision": "REJECT"}, format="json").status_code == 400
    r = api.post(f"{H}/requests/{sup_req['id']}/decide/", {"decision": "REJECT", "comment": "Ya tiene coaching mañana"}, format="json")
    assert r.json()["request"]["status"] == "REJECTED"
    # WFM no aprueba su propia solicitud.
    other_wfm = make_user("wfm2.p19", "WFM")
    api.force_login(other_wfm)
    own = api.post(f"{H}/requests/", {"employee_code": code, "shift_date": "2026-10-05", "kind": "DELETE", "segment_id": brk["id"],
                                      "reason": "Ya no aplica"}, format="json").json()["request"]
    assert api.post(f"{H}/requests/{own['id']}/decide/", {"decision": "APPROVE"}, format="json").status_code == 403
    api.force_login(wfm_user)
    assert api.post(f"{H}/requests/{own['id']}/decide/", {"decision": "APPROVE"}, format="json").status_code == 200
    assert not ScheduleSegment.objects.filter(pk=brk["id"]).exists()
    assert ChangeRequest.objects.filter(status="APPROVED").count() == 2
    trail = api.get(f"{H}/grid/audit/", {"employee": code, "date": "2026-10-05"}).json()
    kinds = {e["action"]: e["kind"] for e in trail["entries"]}
    assert kinds["adh_request_created"] == "action" and kinds["adh_request_approved"] == "approval"
    assert kinds["adh_request_rejected"] == "approval"


def test_daily_reconcile_command(agent, capsys):
    from django.core.management import call_command

    call_command("adh_reconcile_attendance", date="2026-10-05", group="general")
    assert "1 ausencias nuevas" in capsys.readouterr().out
    assert ScheduleSegment.objects.filter(employee=agent, activity__system_role="ABSENCE").count() == 2
    assert ScheduleSegment.objects.filter(employee=agent, activity__system_role="LEGAL_LUNCH").count() == 1
