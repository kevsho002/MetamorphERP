"""Fase 6: roster operativo temporal, independiente de la ficha del empleado."""

import csv
import io
from datetime import date

import pytest
from django.db import DatabaseError, IntegrityError, transaction

from apps.roster.models import RosterAssignment, RosterAttribute, RosterDimension, RosterDimensionItem
from apps.system.models import AuditEvent

pytestmark = pytest.mark.django_db
BASE = "/api/v1/roster"


@pytest.fixture
def catalog(countries):
    dim = {d.code: d for d in RosterDimension.objects.all()}
    acme = RosterDimensionItem.objects.create(dimension=dim["CLIENT"], code="ACME", name="Acme Corp")
    globex = RosterDimensionItem.objects.create(dimension=dim["CLIENT"], code="GLOBEX", name="Globex")
    RosterDimensionItem.objects.create(dimension=dim["BRAND"], parent=acme, code="ACME-MOB", name="Acme Mobile")
    RosterDimensionItem.objects.create(dimension=dim["BRAND"], parent=globex, code="GLX-TV", name="Globex TV")
    voice = RosterDimensionItem.objects.create(dimension=dim["LOB"], code="VOICE", name="Voz")
    RosterDimensionItem.objects.create(dimension=dim["SUB_LOB"], parent=voice, code="VOICE-TS", name="Soporte técnico")
    RosterDimensionItem.objects.create(dimension=dim["CLIENT"], code="OLD", name="Cliente inactivo", is_active=False)
    return dim


@pytest.fixture
def emp(make_employee):
    return make_employee("SV", hire_date=date(2026, 3, 1))


def change(http, code, effective_date, validate=False, **values):
    url = f"{BASE}/employees/{code}/changes/{'validate/' if validate else ''}"
    return http.post(url, {"effective_date": effective_date, "reason": "prueba", "values": values}, format="json")


def intervals(emp, attribute):
    return [
        (r.value, r.effective_start.isoformat(), r.effective_end.isoformat() if r.effective_end else None)
        for r in RosterAssignment.objects.current().filter(employee=emp, attribute__code=attribute).order_by("effective_start")
    ]


def test_seeded_configuration_is_exposed_for_the_ui(api, wfm_user, catalog):
    api.force_login(wfm_user)
    attrs = {a["code"]: a for a in api.get(f"{BASE}/attributes/").json()}
    assert list(attrs)[:4] == ["client", "brand", "line_of_business", "sub_line_of_business"]
    assert attrs["brand"]["depends_on"] == "client" and attrs["brand"]["dimension"] == "BRAND"
    assert attrs["nesting_end_date"]["rules"] == {"not_before": "nesting_start_date"}
    assert {"training_wave", "operations_start_date", "report_id_type"} <= set(attrs)
    dims = {d["code"]: d for d in api.get(f"{BASE}/dimensions/").json()}
    assert dims["BRAND"]["parent"] == "CLIENT"
    assert {i["code"] for i in dims["CLIENT"]["items"]} == {"ACME", "GLOBEX"}  # sin inactivos
    assert next(i for i in dims["REPORT_ID_TYPE"]["items"] if i["code"] == "DUI")["country"] == "SV"


def test_effective_dated_changes_keep_history_and_now(api, wfm_user, catalog, emp):
    api.force_login(wfm_user)
    r = change(api, emp.employee_code, "2026-03-01", client="acme", brand="Acme Mobile", training_wave="Wave 12")
    body = r.json()
    assert r.status_code == 200 and body["saved"], body
    assert "3 cambios del roster" in body["feedback"] and "vigentes desde 01/03/2026" in body["feedback"]
    # Cambio de cliente y marca desde junio: corta el intervalo anterior en mayo.
    r = change(api, emp.employee_code, "2026-06-01", client="GLOBEX", brand="GLX-TV")
    assert r.status_code == 200, r.json()
    assert "(antes: Acme Corp)" in r.json()["feedback"]
    assert intervals(emp, "client") == [("ACME", "2026-03-01", "2026-05-31"), ("GLOBEX", "2026-06-01", None)]

    # Corrección retroactiva en abril: parte el intervalo de marzo y respeta junio.
    r = change(api, emp.employee_code, "2026-04-15", client="GLOBEX", brand="GLX-TV")
    assert r.status_code == 200
    assert intervals(emp, "client") == [
        ("ACME", "2026-03-01", "2026-04-14"), ("GLOBEX", "2026-04-15", "2026-05-31"), ("GLOBEX", "2026-06-01", None),
    ]
    # Nada se borra: las versiones reemplazadas siguen en el historial de auditoría.
    hist = api.get(f"{BASE}/employees/{emp.employee_code}/history/?attribute=client&include_superseded=1").json()["results"]
    assert sum(1 for h in hist if h["superseded_at"]) == 2 and len(hist) == 5

    snap = api.get(f"{BASE}/employees/{emp.employee_code}/?as_of=2026-05-01").json()
    current = {a["code"]: a["current"] for a in snap["attributes"]}
    assert current["client"]["label"] == "Globex" and current["client"]["effective_end"] == "2026-05-31"
    assert current["training_wave"]["is_now"] is True and current["line_of_business"] is None
    assert AuditEvent.objects.filter(action="roster_changed", target_id=emp.employee_code).count() == 3


def test_future_change_and_clearing_a_value(api, hr_user, catalog, emp):
    api.force_login(hr_user)
    change(api, emp.employee_code, "2026-12-01", line_of_business="VOICE")  # programado a futuro
    change(api, emp.employee_code, "2026-03-01", line_of_business="VOICE", sub_line_of_business="VOICE-TS")
    # El cambio de marzo dura hasta el día anterior al programado (no lo pisa).
    assert intervals(emp, "line_of_business") == [("VOICE", "2026-03-01", "2026-11-30"), ("VOICE", "2026-12-01", None)]
    snap = api.get(f"{BASE}/employees/{emp.employee_code}/?as_of=2026-07-01").json()
    lob = next(a for a in snap["attributes"] if a["code"] == "line_of_business")
    assert lob["next"]["effective_start"] == "2026-12-01"

    r = change(api, emp.employee_code, "2026-08-01", sub_line_of_business=None)
    assert r.status_code == 200 and "Sub-línea de negocio: sin valor" in r.json()["feedback"]
    assert intervals(emp, "sub_line_of_business") == [("VOICE-TS", "2026-03-01", "2026-07-31")]

    r = change(api, emp.employee_code, "2026-08-05", line_of_business="VOICE")
    assert r.json()["saved"] is False and "ya estaban vigentes" in r.json()["feedback"]


def test_validation_rules(api, wfm_user, catalog, emp):
    api.force_login(wfm_user)
    code = emp.employee_code
    errors = lambda r: {(e["field"], e["code"]) for e in r.json()["errors"]}  # noqa: E731

    r = change(api, code, "2026-03-01", brand="ACME-MOB")
    assert r.status_code == 400 and ("brand", "missing_parent") in errors(r)
    r = change(api, code, "2026-03-01", client="GLOBEX", brand="ACME-MOB")
    assert ("brand", "parent_mismatch") in errors(r) and "no pertenece a cliente «Globex»" in r.json()["feedback"]
    change(api, code, "2026-03-01", client="ACME", brand="ACME-MOB")
    r = change(api, code, "2026-05-01", client="GLOBEX")  # deja una marca huérfana
    assert ("brand", "parent_mismatch") in errors(r)

    r = change(api, code, "2026-03-01", training_start_date="2026-03-10", nesting_start_date="2026-03-05")
    assert ("nesting_start_date", "date_order") in errors(r)
    assert change(api, code, "2026-03-01", training_start_date="10/03/2026", nesting_start_date="2026-04-01").status_code == 200

    assert ("client", "inactive_item") in errors(change(api, code, "2026-03-01", client="OLD"))
    assert ("client", "unknown_item") in errors(change(api, code, "2026-03-01", client="NOPE"))
    assert ("report_id_type", "wrong_country") in errors(change(api, code, "2026-03-01", report_id_type="CURP"))
    assert ("effective_date", "before_hire") in errors(change(api, code, "2026-02-01", client="ACME"))
    assert ("nope", "unknown_attribute") in errors(change(api, code, "2026-03-01", nope="x"))
    assert ("effective_date", "required") in errors(change(api, code, "", client="ACME"))

    before = RosterAssignment.objects.count()
    r = change(api, code, "2026-07-01", validate=True, report_id_type="dui")
    assert r.status_code == 200 and r.json()["valid"] and "validación previa" in r.json()["feedback"]
    assert RosterAssignment.objects.count() == before


def test_database_rejects_overlapping_intervals(catalog, emp):
    attr = RosterAttribute.objects.get(code="training_wave")
    RosterAssignment.objects.create(employee=emp, attribute=attr, value="W1", effective_start=date(2026, 3, 1), effective_end=date(2026, 3, 31))
    RosterAssignment.objects.create(employee=emp, attribute=attr, value="W0", effective_start=date(2026, 4, 1))  # contiguo: válido
    # El trigger aborta la transacción completa (comportamiento de SQL Server): debe ser lo último del test.
    with pytest.raises(DatabaseError, match="intervalos superpuestos"), transaction.atomic():
        RosterAssignment.objects.create(employee=emp, attribute=attr, value="W2", effective_start=date(2026, 3, 15), effective_end=date(2026, 3, 20))


def test_database_rejects_inverted_dates(catalog, emp):
    attr = RosterAttribute.objects.get(code="training_wave")
    with pytest.raises(IntegrityError), transaction.atomic():
        RosterAssignment.objects.create(employee=emp, attribute=attr, value="W2", effective_start=date(2026, 3, 1), effective_end=date(2026, 2, 1))


def test_rbac(api, employee_user, wfm_user, catalog, emp):
    api.force_login(employee_user)
    assert api.get(f"{BASE}/attributes/").status_code == 403
    assert api.get(f"{BASE}/employees/{emp.employee_code}/").status_code == 403
    assert change(api, emp.employee_code, "2026-03-01", client="ACME").status_code == 403
    api.force_login(wfm_user)
    snap = api.get(f"{BASE}/employees/{emp.employee_code}/?include=employee").json()
    assert snap["can_manage"] is True
    assert "base_salary" not in snap["employee"]  # la ficha cruzada respeta el RBAC de la ficha


def test_cross_report_by_date_range(api, hr_user, catalog, make_employee, emp):
    other = make_employee("GT", hire_date=date(2026, 3, 1))
    make_employee("SV", hire_date=date(2027, 1, 1))  # ingresa después del rango: no aparece
    api.force_login(hr_user)
    change(api, emp.employee_code, "2026-03-01", client="ACME", brand="ACME-MOB")
    change(api, emp.employee_code, "2026-06-01", client="GLOBEX", brand="GLX-TV")
    change(api, other.employee_code, "2026-03-01", client="GLOBEX")

    body = api.get(f"{BASE}/report/?from=2026-05-01&to=2026-06-30&attribute=client&value=ACME").json()
    assert [r["employee"]["employee_code"] for r in body["results"]] == [emp.employee_code]
    clients = body["results"][0]["assignments"]["client"]
    assert [(c["value"], c["effective_end"]) for c in clients] == [("ACME", "2026-05-31"), ("GLOBEX", None)]
    assert body["range"] == {"from": "2026-05-01", "to": "2026-06-30"} and body["attributes"][0]["code"] == "client"

    body = api.get(f"{BASE}/report/?from=2026-07-01&attribute=client&value=GLOBEX").json()
    assert {r["employee"]["employee_code"] for r in body["results"]} == {emp.employee_code, other.employee_code}
    assert api.get(f"{BASE}/report/?from=2026-07-01&country=GT").json()["count"] == 1
    assert api.get(f"{BASE}/report/?from=2026-07-01&to=2026-06-01").status_code == 400

    r = api.get(f"{BASE}/report/?from=2026-01-01&to=2026-12-31&export=csv")
    rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert r["Content-Type"].startswith("text/csv") and len(rows) == 5
    now_rows = [x for x in rows if x["vigente_hasta"] == "Now"]
    assert {(x["id_corporativo"], x["atributo"], x["valor_descripcion"]) for x in now_rows} >= {(emp.employee_code, "client", "Globex")}


def test_reporting_view_in_sql_server(catalog, emp, api, hr_user):
    from django.db import connection

    api.force_login(hr_user)
    change(api, emp.employee_code, "2026-03-01", client="ACME", brand="ACME-MOB")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT AttributeCode, ValueLabel, ParentValue, IsNow FROM org.vw_RosterAssignment WHERE EmployeeCode = %s ORDER BY AttributeCode",
            [emp.employee_code],
        )
        assert cursor.fetchall() == [("brand", "Acme Mobile", "ACME", True), ("client", "Acme Corp", None, True)]
