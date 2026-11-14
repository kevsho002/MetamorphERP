"""Fase 17: jerarquía operativa, grilla de planificación estilo IEX, vista histórica del agente y drag & drop."""

from datetime import date

import pytest
from django.db import DatabaseError, transaction

from apps.acd.models import AgentGroup, AgentMembership
from apps.adherence.models import ActivityType, AdherenceDay, GridSetting
from apps.operations.models import Brand, Client, OperationalLeader
from apps.roster.models import RosterAssignment, RosterAttribute
from apps.scheduling.models import ScheduleAssignment

pytestmark = pytest.mark.django_db
H = "/api/v1/adherence"
L = "/api/v1/roster/hierarchy/leaders"  # Fase 18: la cadena de mando vive en el roster
MON = date(2026, 10, 5)  # lunes (día pasado)
DAY = {"days": {d: {"start": "08:00", "end": "17:00", "lunch_minutes": 60} for d in ("mon", "tue", "wed", "thu", "fri")}}


def _leader(api, level, emp, reports_to=None, client=None, status=201):
    r = api.post(f"{L}/", {"level": level, "employee_code": emp.employee_code, "reports_to": reports_to, "client": client}, format="json")
    assert r.status_code == status, r.json()
    return r.json().get("leader")


def _assign(emp, attribute, item, start=date(2026, 9, 1)):
    RosterAssignment.objects.create(employee=emp, attribute=RosterAttribute.objects.get(code=attribute), value=item.code, item=item,
                                    effective_start=start)


@pytest.fixture
def org(api, wfm_user, make_employee):
    """Director → Manager → 2 Account Supervisors → 2 Team Managers; 3 agentes en GENERAL con cliente / marca en el roster."""
    api.force_login(wfm_user)
    acme = Client.objects.create(code="ACME", name="Acme Corp")
    brand = Brand.objects.create(code="ACME-MOBILE", name="Acme Mobile", client=acme)
    other = Client.objects.create(code="GLOBEX", name="Globex")
    people = {k: make_employee("SV", first_name=k, last_name="Líder") for k in ("Dir", "Mgr", "SupA", "SupB", "TmA", "TmB")}
    d = _leader(api, "OPS_DIRECTOR", people["Dir"])
    m = _leader(api, "OPS_MANAGER", people["Mgr"], d["id"])
    sa = _leader(api, "ACCOUNT_SUPERVISOR", people["SupA"], m["id"], client="ACME")
    sb = _leader(api, "ACCOUNT_SUPERVISOR", people["SupB"], m["id"])
    ta = _leader(api, "TEAM_MANAGER", people["TmA"], sa["id"])
    tb = _leader(api, "TEAM_MANAGER", people["TmB"], sb["id"])
    group = AgentGroup.objects.get(code="GENERAL")
    agents = []
    for i, (tm, client) in enumerate([(ta, acme), (ta, acme), (tb, other)]):
        e = make_employee("SV", first_name=f"Agente{i}", last_name="Prueba", hire_date=date(2026, 9, 20))
        ScheduleAssignment.objects.create(employee=e, definition=DAY, effective_start_date=date(2026, 9, 20))
        AgentMembership.objects.create(group=group, employee=e)
        _assign(e, "team_manager", OperationalLeader.objects.get(pk=tm["id"]).roster_item)
        _assign(e, "client", client.roster_item)
        agents.append(e)
    _assign(agents[0], "brand", brand.roster_item)
    return {"leaders": {"dir": d, "mgr": m, "sa": sa, "sb": sb, "ta": ta, "tb": tb}, "agents": agents, "people": people}


def test_leader_hierarchy_rules(api, employee_user, org):
    lead = org["leaders"]
    assert OperationalLeader.objects.count() == 6
    tm = OperationalLeader.objects.get(pk=lead["ta"]["id"])
    # Sincronizado con la dimensión del roster de su nivel; su padre es el elemento de su supervisor.
    assert tm.roster_item.dimension.code == "TEAM_MANAGER"
    assert tm.roster_item.parent == OperationalLeader.objects.get(pk=lead["sa"]["id"]).roster_item
    # Un Team Manager debe reportar a un Account Supervisor.
    r = api.post(f"{L}/", {"level": "TEAM_MANAGER", "employee_code": org["people"]["Mgr"].employee_code,
                           "reports_to": lead["mgr"]["id"]}, format="json")
    assert r.status_code == 400 and "Account Supervisor" in r.json()["errors"]["reports_to"]
    # Con subordinados activos no se desactiva.
    r = api.patch(f"{L}/{lead['sa']['id']}/", {"is_active": False}, format="json")
    assert r.status_code == 400 and "subordinados" in r.json()["errors"]["is_active"]
    # Reasignar: el TM A pasa al supervisor B.
    r = api.patch(f"{L}/{lead['ta']['id']}/", {"reports_to": lead["sb"]["id"]}, format="json")
    assert r.status_code == 200 and r.json()["leader"]["reports_to_id"] == lead["sb"]["id"]
    r = api.get(f"{L}/")
    assert r.status_code == 200
    by_id = {x["id"]: x for x in r.json()["results"]}
    assert by_id[lead["ta"]["id"]]["agents"] == 2 and [x["level"] for x in r.json()["results"]][0] == "OPS_DIRECTOR"
    api.force_login(employee_user)  # sin permisos de roster: ni consulta ni edita
    assert api.get(f"{L}/").status_code == 403
    assert api.patch(f"{L}/{lead['ta']['id']}/", {"is_active": False}, format="json").status_code == 403


def test_sql_50080_leader_must_report_to_the_level_above(org):
    tm = OperationalLeader.objects.get(pk=org["leaders"]["ta"]["id"])
    with pytest.raises(DatabaseError, match="50080"), transaction.atomic():
        OperationalLeader.objects.filter(pk=tm.pk).update(reports_to_id=org["leaders"]["mgr"]["id"])


def test_grid_filters_by_management_unit_client_and_hierarchy(api, org):
    a = org["agents"]
    r = api.get(f"{H}/grid/filters/")
    assert r.status_code == 200
    body = r.json()
    assert {"GENERAL"} <= {g["code"] for g in body["management_units"]}
    assert [lvl["param"] for lvl in body["levels"]] == ["director", "manager", "supervisor", "team_manager"]
    assert next(c for c in body["clients"] if c["code"] == "ACME")["brands"] == [{"code": "ACME-MOBILE", "name": "Acme Mobile"}]

    def codes(**params):
        r = api.get(f"{H}/grid/", {"date": "2026-10-05", "group": "GENERAL", **params})
        assert r.status_code == 200, r.json()
        return r.json(), {row["employee_code"] for row in r.json()["rows"]}

    data, all_codes = codes(director=org["people"]["Dir"].employee_code)
    assert all_codes == {e.employee_code for e in a}
    assert codes(supervisor=org["people"]["SupA"].employee_code)[1] == {a[0].employee_code, a[1].employee_code}
    assert codes(team_manager=org["people"]["TmB"].employee_code)[1] == {a[2].employee_code}
    assert codes(client="GLOBEX")[1] == {a[2].employee_code}
    assert codes(client="ACME", brand="ACME-MOBILE")[1] == {a[0].employee_code}
    # El nivel más bajo elegido manda.
    assert codes(director=org["people"]["Dir"].employee_code, team_manager=org["people"]["TmA"].employee_code)[1] == {
        a[0].employee_code, a[1].employee_code}

    row = next(r for r in data["rows"] if r["employee_code"] == a[0].employee_code)
    assert row["hierarchy"]["TEAM_MANAGER"]["employee_code"] == org["people"]["TmA"].employee_code
    assert row["hierarchy"]["OPS_DIRECTOR"]["employee_code"] == org["people"]["Dir"].employee_code
    assert row["client"]["code"] == "ACME" and row["brand"]["code"] == "ACME-MOBILE"
    assert row["containers"][0]["start"] == "2026-10-05T08:00:00"
    # Metadatos: turno 08–17 con 1 h de margen → ventana 07:00–18:00 en minutos desde las 00:00.
    assert data["grid"]["interval_minutes"] == 15 and data["grid"]["snap_seconds"] == 300
    assert (data["grid"]["window_start"], data["grid"]["window_end"]) == (7 * 60, 18 * 60)
    assert row["metrics"]["scheduled"] == 9 * 3600 and row["metrics"]["adherence_pct"] == 0.0
    tools = {t["code"]: t for t in data["toolbox"]}
    assert tools["BREAK"]["icon"] == "coffee" and tools["MEAL"]["icon"] == "utensils"


def test_toolbox_is_scoped_by_account(api, org):
    r = api.patch(f"{H}/activities/COACHING/", {"clients": ["GLOBEX"], "icon": "star"}, format="json")
    assert r.status_code == 200, r.json()
    assert r.json()["activity"]["clients"] == ["GLOBEX"] and r.json()["activity"]["icon"] == "star"
    assert api.patch(f"{H}/activities/COACHING/", {"icon": "rocket"}, format="json").status_code == 400
    acme = {t["code"] for t in api.get(f"{H}/grid/", {"date": "2026-10-05", "client": "ACME"}).json()["toolbox"]}
    globex = {t["code"] for t in api.get(f"{H}/grid/", {"date": "2026-10-05", "client": "GLOBEX"}).json()["toolbox"]}
    assert "COACHING" not in acme and "COACHING" in globex and "BREAK" in acme


def test_drop_creates_moves_and_recomputes_stored_adherence(api, org):
    emp = org["agents"][0]
    code = emp.employee_code
    r = api.post(f"{H}/compute/", {"from": "2026-10-05", "to": "2026-10-05", "employee": code, "reconcile": False}, format="json")
    assert r.status_code == 200, r.json()
    stored = AdherenceDay.objects.get(employee=emp, shift_date=MON)
    assert stored.scheduled_paid_seconds == 9 * 3600
    # Soltar «Almuerzo» desde la barra de segmentos a las 12:00 (duración sugerida 60 min).
    r = api.post(f"{H}/segments/", {"employee_code": code, "shift_date": "2026-10-05", "start": "12:00", "end": "13:00", "activity": "MEAL"},
                 format="json")
    assert r.status_code == 201, r.json()
    refresh = r.json()["refresh"]
    assert refresh["stored_recomputed"] is True and refresh["metrics"]["scheduled_paid"] == 8 * 3600
    assert AdherenceDay.objects.get(employee=emp, shift_date=MON).scheduled_paid_seconds == 8 * 3600
    # Arrastrar el segmento a otra hora.
    seg_id = r.json()["segment"]["id"]
    r = api.patch(f"{H}/segments/{seg_id}/", {"start": "12:30", "end": "13:30"}, format="json")
    assert r.status_code == 200 and r.json()["segment"]["start"] == "2026-10-05T12:30:00"
    # Fuera del pre-contenedor se rechaza.
    r = api.patch(f"{H}/segments/{seg_id}/", {"start": "16:30", "end": "17:30"}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "outside_container"
    r = api.delete(f"{H}/segments/{seg_id}/")
    assert r.status_code == 200 and r.json()["refresh"]["metrics"]["scheduled_paid"] == 9 * 3600
    # Un día sin resultado guardado no se guarda solo.
    r = api.post(f"{H}/segments/", {"employee_code": code, "shift_date": "2026-10-06", "start": "10:00", "end": "10:15", "activity": "BREAK"},
                 format="json")
    assert r.status_code == 201 and r.json()["refresh"]["stored_recomputed"] is False
    assert not AdherenceDay.objects.filter(employee=emp, shift_date=date(2026, 10, 6)).exists()


def test_agent_history_starts_at_hire_date(api, org):
    emp = org["agents"][0]  # contratado el 20/09/2026, horario lun–vie desde esa fecha
    r = api.get(f"{H}/grid/agent/", {"employee": emp.employee_code, "from": "2026-08-01", "to": "2026-10-10"})
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["hire_date"] == "2026-09-20" and body["from"] == "2026-09-20"
    assert len(body["rows"]) == 21 and body["to"] == "2026-10-10" and body["prev_from"] is None
    assert body["management_unit"]["code"] == "GENERAL"
    assert body["hierarchy_history"][0]["TEAM_MANAGER"]["employee_code"] == org["people"]["TmA"].employee_code
    rows = {x["date"]: x for x in body["rows"]}
    assert rows["2026-09-20"]["containers"] == []  # domingo: descanso
    assert rows["2026-09-21"]["containers"][0]["start"] == "2026-09-21T08:00:00"
    assert rows["2026-09-21"]["metrics"]["scheduled"] == 9 * 3600
    assert (body["grid"]["window_start"], body["grid"]["window_end"]) == (7 * 60, 18 * 60)
    # Página siguiente.
    r = api.get(f"{H}/grid/agent/", {"employee": emp.employee_code, "from": body["next_from"]})
    assert r.status_code == 200 and r.json()["from"] == "2026-10-11" and r.json()["prev_from"] == "2026-09-27"  # páginas de 14 días


def test_grid_settings(api, hr_user, org):
    r = api.put(f"{H}/grid/settings/", {"group": "GENERAL", "interval_minutes": 30, "snap_seconds": 900, "margin_hours": 2}, format="json")
    assert r.status_code == 200, r.json()
    assert GridSetting.objects.get(group__code="GENERAL").interval_minutes == 30
    grid = api.get(f"{H}/grid/", {"date": "2026-10-05", "group": "GENERAL"}).json()["grid"]
    assert (grid["interval_minutes"], grid["snap_seconds"], grid["window_start"]) == (30, 900, 6 * 60)
    assert api.get(f"{H}/grid/", {"date": "2026-10-05", "client": "ACME"}).json()["grid"]["interval_minutes"] == 15  # global
    r = api.put(f"{H}/grid/settings/", {"interval_minutes": 15, "snap_seconds": 1800}, format="json")
    assert r.status_code == 400 and "snap_seconds" in r.json()["errors"]
    api.force_login(hr_user)
    assert api.put(f"{H}/grid/settings/", {"interval_minutes": 60}, format="json").status_code == 403
    assert ActivityType.objects.get(code="PRODUCTION").icon == "headset"
