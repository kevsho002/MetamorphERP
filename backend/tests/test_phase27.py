"""Fase 27: historial de boletas por corte (paginación y filtro por año), búsqueda de colaboradores para los campos
con autocompletado y carga diferida de la grilla IEX (filtros obligatorios y agentes por páginas)."""

from datetime import date

import pytest

from apps.acd.models import AgentGroup, AgentMembership
from apps.adherence import grid
from apps.payroll import services
from apps.scheduling.models import AttendanceCutoff, PayPeriod, ScheduleAssignment

from .test_phase17 import org  # noqa: F401  (fixture: jerarquía con 3 agentes en GENERAL)

pytestmark = pytest.mark.django_db
DAY = {"days": {d: {"start": "08:00", "end": "17:00", "lunch_minutes": 60} for d in ("mon", "tue", "wed", "thu", "fri")}}
H = "/api/v1/adherence"


# ================================================================== boletas por corte
def test_cutoff_history_is_paginated_and_filtered_by_year(api, make_employee, make_user):
    emp = make_employee("SV", hire_date=date(2026, 9, 1), base_salary=880, pay_frequency="BIWEEKLY")
    ScheduleAssignment.objects.create(employee=emp, definition=DAY, effective_start_date=date(2026, 9, 1))
    user = make_user("agente.p27", "EMPLOYEE", employee=emp)
    services.calculate(PayPeriod.objects.get(cycle__code="SV_QUINCENAL", code="2026-10-Q1"))
    api.force_login(user)

    body = api.get("/api/v1/payroll/me/cutoffs/", {"page_size": 3}).json()
    expected = AttendanceCutoff.objects.filter(cycle__code="SV_QUINCENAL", cutoff_end__gte=date(2026, 9, 1),
                                               cutoff_start__lte=date.today()).count()
    assert body["count"] == expected >= 4 and body["page_size"] == 3 and body["pages"] == -(-expected // 3)
    starts = [r["start"] for r in body["results"]]
    assert starts == sorted(starts, reverse=True)  # del más reciente al más antiguo
    assert body["years"] == [2026]

    pages = [api.get("/api/v1/payroll/me/cutoffs/", {"page_size": 3, "page": n}).json() for n in range(1, body["pages"] + 1)]
    seen = [r for p in pages for r in p["results"]]
    assert len(seen) == expected and len({r["id"] for r in seen}) == expected
    paid = next(r for r in seen if r["start"] == "2026-09-25")  # corte interno de la quincena 2026-10-Q1
    assert paid["state"] == "PRELIMINARY" and len(paid["days"]) == 15 and paid["pay_period"]["code"] == "2026-10-Q1"
    assert all(r["state"] == "PENDING" and r["days"] == [] for r in seen if r["start"] > "2026-09-25")
    # El primer corte empieza antes del ingreso pero lo incluye: el colaborador estuvo activo en él.
    assert min(r["start"] for r in seen) < "2026-09-01" <= min(r["end"] for r in seen)

    assert api.get("/api/v1/payroll/me/cutoffs/", {"year": 2025}).json()["count"] == 0
    assert api.get("/api/v1/payroll/me/cutoffs/", {"page": 999, "page_size": 3}).json()["page"] == body["pages"]
    assert api.get("/api/v1/payroll/me/cutoffs/", {"year": "x"}).status_code == 400
    slips = api.get("/api/v1/payroll/me/payslips/", {"year": 2026}).json()
    assert slips["final_page"] == {"year": 2026, "years": [], "count": 0, "page": 1, "pages": 1, "page_size": 6}


def test_cutoff_history_requires_a_linked_employee(api, make_user):
    api.force_login(make_user("sin.empleado.p27", "ADMIN", with_employee=False))
    assert api.get("/api/v1/payroll/me/cutoffs/").status_code in (403, 404)


# ================================================================== autocompletado
def test_employee_lookup_searches_by_name_or_code(api, make_employee, wfm_user, employee_user):
    a = make_employee("SV", first_name="Rigoberto", last_name="Quintanilla")
    b = make_employee("SV", first_name="Rigoberta", last_name="Menjívar")
    AgentMembership.objects.create(group=AgentGroup.objects.get(code="GENERAL"), employee=b)
    api.force_login(employee_user)
    assert api.get("/api/v1/hcm/employee-lookup/", {"q": "rigob"}).status_code == 403
    api.force_login(wfm_user)
    codes = lambda **p: {r["employee_code"] for r in api.get("/api/v1/hcm/employee-lookup/", p).json()["results"]}  # noqa: E731
    assert codes(q="rigob") == {a.employee_code, b.employee_code}
    assert codes(q="rigob quinta") == {a.employee_code}  # varias palabras se combinan (AND)
    assert codes(q=a.employee_code) == {a.employee_code}
    assert codes(q="menjivar") == {b.employee_code}  # sin distinguir acentos
    assert codes(q="rigob", scope="acd") == {b.employee_code}  # solo agentes con membresía ACD activa
    row = api.get("/api/v1/hcm/employee-lookup/", {"q": a.employee_code}).json()["results"][0]
    assert set(row) == {"employee_code", "full_name", "country", "status", "status_label", "cost_center"}


# ================================================================== grilla IEX
def test_grid_requires_a_filter_and_loads_agents_by_page(api, org, monkeypatch):  # noqa: F811
    r = api.get(f"{H}/grid/", {"date": "2026-10-05"})
    assert r.status_code == 400 and r.json()["code"] == "filters_required"
    body = api.get(f"{H}/grid/", {"date": "2026-10-05", "group": "GENERAL"}).json()
    assert body["paging"] == {"count": 3, "page": 1, "pages": 1, "page_size": 50, "page_sizes": [25, 50, 100, 200]}

    monkeypatch.setattr(grid, "GRID_PAGE_SIZES", (2, 50))
    p1 = api.get(f"{H}/grid/", {"date": "2026-10-05", "group": "GENERAL", "page_size": 2}).json()
    p2 = api.get(f"{H}/grid/", {"date": "2026-10-05", "group": "GENERAL", "page_size": 2, "page": 2}).json()
    assert (p1["paging"]["pages"], len(p1["rows"]), len(p2["rows"])) == (2, 2, 1)
    assert {r["employee_code"] for r in p1["rows"] + p2["rows"]} == {e.employee_code for e in org["agents"]}
    assert p1["summary"]["agents"] == 2  # solo la página pedida se evalúa
    # Los filtros por cuenta y jerarquía se resuelven como subconsultas (sin listas de ids).
    tm = org["people"]["TmA"].employee_code
    sql = str(grid.grid_queryset({"group": "GENERAL", "client": "ACME", "team_manager": tm}, date(2026, 10, 5)).query)
    assert sql.count("SELECT") >= 4
    only = api.get(f"{H}/grid/", {"date": "2026-10-05", "team_manager": tm}).json()
    assert {r["employee_code"] for r in only["rows"]} == {org["agents"][0].employee_code, org["agents"][1].employee_code}
