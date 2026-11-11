"""Fase 4: edición de empleados (PATCH), catálogos y filtros que consume el frontend React."""

import pytest

from apps.employees.models import EmployeeAttributeValue
from apps.hcm.models import Employee
from tests.test_employees import EMPLOYEES, gt_row, sv_row

pytestmark = pytest.mark.django_db


@pytest.fixture
def created(api, hr_user):
    """Empleado SV creado por la API (con atributos EAV) y el cliente autenticado como RRHH."""
    api.force_login(hr_user)
    r = api.post(EMPLOYEES, sv_row(), format="json")
    assert r.status_code == 201, r.json()
    return api, r.json()["employee"]


def test_patch_updates_core_fields_cost_center_and_eav(created, hr_user):
    api, emp = created
    url = f"{EMPLOYEES}{emp['employee_code']}/"
    r = api.patch(
        url,
        {
            "phone_number": "7999-0000",
            "cost_center": "SV-TI",
            "attributes": {"pension_fund": "confia", "emergency_contact_phone": ""},
            "row_version": emp["row_version"],
        },
        format="json",
    )
    body = r.json()
    assert r.status_code == 200, body
    assert body["saved"] is True
    assert set(body["changes"]) >= {"Teléfono", "Centro de costos", "AFP"}
    assert body["feedback"].startswith(f"Se actualizó el empleado {emp['employee_code']}")
    updated = body["employee"]
    assert updated["phone_number"] == "7999-0000" and updated["cost_center"] == "SV-TI"
    assert updated["attributes"]["pension_fund"] == "CONFIA"
    assert "emergency_contact_phone" not in updated["attributes"]  # opcional borrado
    assert updated["row_version"] != emp["row_version"]
    employee = Employee.objects.get(employee_code=emp["employee_code"])
    assert employee.updated_by == hr_user.username and employee.first_name == "Ana"  # lo no enviado se conserva
    assert not EmployeeAttributeValue.objects.filter(employee=employee, attribute__code="emergency_contact_phone").exists()


def test_patch_rejects_invalid_data_with_natural_language_feedback(created):
    api, emp = created
    url = f"{EMPLOYEES}{emp['employee_code']}/"
    r = api.patch(
        url,
        {"country": "GT", "national_id_number": "123", "cost_center": "GT-OPS", "attributes": {"pension_id": ""}},
        format="json",
    )
    body = r.json()
    assert r.status_code == 400
    fields = {e["field"] for e in body["errors"]}
    assert {"country", "national_id_number", "pension_id"} <= fields
    assert "El país no se puede cambiar" in body["feedback"] and "01234567-8" in body["feedback"]
    assert Employee.objects.get(employee_code=emp["employee_code"]).national_id_number == "01234567-8"


def test_patch_duplicate_document_excludes_self_but_detects_others(created):
    api, emp = created
    url = f"{EMPLOYEES}{emp['employee_code']}/"
    # Reenviar su propio documento no es duplicado.
    assert api.patch(url, {"national_id_number": "01234567-8"}, format="json").status_code == 200
    other = api.post(EMPLOYEES, sv_row(national_id_number="07654321-0", work_email="otra@metamorph.test"), format="json")
    assert other.status_code == 201
    r = api.patch(url, {"national_id_number": "07654321-0"}, format="json")
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "duplicate_employee"


def test_patch_status_rules_and_stale_row_version(created):
    api, emp = created
    url = f"{EMPLOYEES}{emp['employee_code']}/"
    r = api.patch(url, {"employment_status": "RETIRADO"}, format="json")
    assert r.status_code == 400 and r.json()["errors"][0]["field"] == "termination_date"
    r = api.patch(url, {"employment_status": "ACTIVE", "termination_date": "2026-05-01"}, format="json")
    assert r.status_code == 400 and "Solo un empleado" in r.json()["feedback"]
    r = api.patch(url, {"employment_status": "TERMINATED", "termination_date": "2026-02-01"}, format="json")
    assert r.status_code == 400 and "anterior a la fecha de ingreso" in r.json()["feedback"]
    r = api.patch(url, {"employment_status": "TERMINATED", "termination_date": "2026-06-30"}, format="json")
    assert r.status_code == 200 and r.json()["employee"]["employment_status"] == "TERMINATED"
    # Versión vieja -> 409 sin tocar el registro.
    r = api.patch(url, {"phone_number": "7111-1111", "row_version": emp["row_version"]}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "stale"
    assert Employee.objects.get(employee_code=emp["employee_code"]).phone_number == "7123-4567"


def test_validate_update_does_not_persist_and_reports_no_changes(created):
    api, emp = created
    url = f"{EMPLOYEES}{emp['employee_code']}/validate/"
    r = api.post(url, {"phone_number": "7888-8888"}, format="json")
    assert r.status_code == 200 and r.json()["saved"] is False and r.json()["changes"] == ["Teléfono"]
    assert Employee.objects.get(employee_code=emp["employee_code"]).phone_number == "7123-4567"
    r = api.post(url, {"phone_number": "7123-4567"}, format="json")
    assert r.json()["changes"] == [] and "No hay cambios" in r.json()["feedback"]


def test_edit_rbac(created, wfm_user):
    api, emp = created
    api.force_login(wfm_user)
    assert api.patch(f"{EMPLOYEES}{emp['employee_code']}/", {"phone_number": "7000-1111"}, format="json").status_code == 403
    assert api.put(f"{EMPLOYEES}{emp['employee_code']}/", sv_row(), format="json").status_code == 403


def test_catalogs_filters_and_ordering(api, hr_user, wfm_user, employee_user):
    api.force_login(hr_user)
    assert api.post(EMPLOYEES, sv_row(), format="json").status_code == 201
    assert api.post(EMPLOYEES, gt_row(), format="json").status_code == 201

    catalogs = api.get("/api/v1/hcm/catalogs/").json()
    assert {c["code"] for c in catalogs["countries"]} >= {"SV", "GT", "MX", "CO"}
    assert {"code": "GT-OPS", "country": "GT"}.items() <= next(c for c in catalogs["cost_centers"] if c["code"] == "GT-OPS").items()
    assert [s["value"] for s in catalogs["employment_statuses"]] == ["ACTIVE", "INACTIVE", "TERMINATED"]

    page = api.get(EMPLOYEES, {"country": "GT"}).json()
    assert page["count"] == 1 and page["results"][0]["country"] == "GT" and "attributes" not in page["results"][0]
    assert api.get(EMPLOYEES, {"cost_center": "SV-OPS"}).json()["count"] == 1
    total = api.get(EMPLOYEES).json()["count"]
    gt = Employee.objects.get(country__country_code="GT")
    gt.employment_status, gt.termination_date = Employee.Status.INACTIVE, None
    gt.save(update_fields=["employment_status"])
    assert api.get(EMPLOYEES, {"status": "INACTIVE"}).json()["count"] == 1
    assert api.get(EMPLOYEES, {"status": "ACTIVE"}).json()["count"] == total - 1
    assert api.get(EMPLOYEES, {"status": "inactive,terminated", "country": "gt"}).json()["count"] == 1
    names = [e["full_name"] for e in api.get(EMPLOYEES, {"ordering": "-name", "page_size": 200}).json()["results"]]
    assert names.index("Carlos Pérez") < names.index("Ana López")
    assert len(api.get(EMPLOYEES, {"page_size": 1}).json()["results"]) == 1

    api.force_login(wfm_user)
    rows = api.get(EMPLOYEES).json()["results"]
    assert rows and all("base_salary" not in r for r in rows)
    assert api.get("/api/v1/hcm/catalogs/").status_code == 200
    api.force_login(employee_user)
    assert api.get("/api/v1/hcm/catalogs/").status_code == 403
