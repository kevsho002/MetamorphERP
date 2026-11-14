"""Fase 3: alta individual y masiva de empleados con plantillas por país (EAV + JSON)."""

import csv
import io
import json
from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction

from apps.common.models import CostCenter, EmployeeCodeSequence
from apps.employees.models import AttributeDefinition, EmployeeAttributeValue, EmployeeTemplate, ImportBatch, ImportBatchRow
from apps.employees.schema import resolve_template, validate_template_schema
from apps.hcm.models import DigitalFile, Employee
from apps.hcm.services.employee_code import format_employee_code, is_valid_employee_code

pytestmark = pytest.mark.django_db

EMPLOYEES = "/api/v1/hcm/employees/"
IMPORTS = "/api/v1/hcm/employee-imports/"


def sv_row(**overrides):
    row = {
        "country": "SV",
        "first_name": "Ana",
        "last_name": "López",
        "national_id_number": "01234567-8",
        "birth_date": "1990-05-10",
        "hire_date": "2026-03-01",
        "base_salary": "850.00",
        "cost_center": "SV-OPS",
        "work_email": "ana.lopez@metamorph.test",
        "phone_number": "7123-4567",
        "social_security_number": "123456789",
        "pension_id": "123456789012",
        "pension_fund": "Crécer",  # sin distinguir mayúsculas ni tildes
        "emergency_contact_name": "Luis López",
        "emergency_contact_phone": "7000-0000",
        "schedule": "L-V 08:00-17:00 60",  # Fase 9: Primera AP de asignación de horario
    }
    row.update(overrides)
    return row


def gt_row(**overrides):
    row = {
        "pais": "GT",
        "primer_nombre": "Carlos",
        "primer_apellido": "Pérez",
        "numero_documento": "1234 56789 0101",
        "fecha_nacimiento": "15/08/1992",
        "fecha_ingreso": "2026-04-01",
        "salario": "5500",
        "centro_costos": "GT-OPS",
        "NIT": "1234567-k",
        "social_security_number": "1234567890",
        "emergency_contact_name": "María Pérez",
        "emergency_contact_phone": "5555-0000",
        "horario": "L-V 07:00-16:00 60; S 07:00-11:00",
    }
    row.update(overrides)
    return row


def to_csv(rows: list[dict], delimiter=",") -> bytes:
    headers: list[str] = []
    for row in rows:
        headers += [h for h in row if h not in headers]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers, delimiter=delimiter)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def upload(client, content: bytes, name="altas.csv", **options):
    data = {"file": SimpleUploadedFile(name, content), **options}
    return client.post(IMPORTS, data, format="multipart")


# --------------------------------------------------------------------- plantillas
def test_seeded_templates_are_valid_and_linked_to_catalog_countries(countries):
    templates = EmployeeTemplate.objects.select_related("country")
    assert {t.country.country_code for t in templates} == {"SV", "GT", "MX", "CO"}
    for template in templates:
        validate_template_schema(template.schema)  # no lanza
        spec = resolve_template(template)
        assert spec.fields["first_name"].required and spec.fields["cost_center"].required
    sv = resolve_template(EmployeeTemplate.objects.get(country=countries["SV"]))
    assert sv.fields["social_security_number"].label == "Número de afiliación ISSS"
    assert sv.fields["pension_fund"].choices == ("CONFIA", "CRECER")


@pytest.mark.parametrize(
    ("schema", "fragment"),
    [
        ({"campos": {}}, "Clave desconocida «campos»"),
        ({"core_fields": {"salario": {}}}, "no es un campo de hcm.Employee"),
        ({"core_fields": {"first_name": {"required": False}}}, "no puede marcarse required=false"),
        ({"attributes": {"no_existe": {}}}, "no existe en el catálogo"),
        ({"attributes": {"tax_id": {"pattern": "([0-9"}}}, "expresión regular inválida"),
        ({"attributes": {"tax_id": {"requird": True}}}, "regla desconocida «requird»"),
        ({"attributes": {"pension_fund": {"required": True}}}, "requiere «choices»"),
        ({"rules": {"min_age": "dieciocho"}}, "debe ser numérico"),
    ],
)
def test_template_schema_validation_reports_precise_problems(schema, fragment):
    with pytest.raises(ValidationError) as exc:
        validate_template_schema(schema)
    assert any(fragment in m for m in exc.value.message_dict["schema"]), exc.value.message_dict


def test_template_is_chosen_by_effective_date(api, hr_user, countries):
    base = EmployeeTemplate.objects.get(country=countries["SV"])
    schema = json.loads(json.dumps(base.schema))
    schema["attributes"]["tax_id"]["required"] = True  # desde jul-2026 el NIT pasa a obligatorio
    EmployeeTemplate.objects.create(country=countries["SV"], name="SV 2026-07", effective_date=date(2026, 7, 1), schema=schema)
    api.force_login(hr_user)

    before = api.post(f"{EMPLOYEES}validate/", sv_row(hire_date="2026-06-30"), format="json").json()
    after = api.post(f"{EMPLOYEES}validate/", sv_row(hire_date="2026-07-01", national_id_number="01234567-9"), format="json").json()
    assert before["valid"] and before["template"]["name"] == "El Salvador — plantilla base"
    assert not after["valid"] and after["template"]["name"] == "SV 2026-07"
    assert "Falta el campo obligatorio «NIT» exigido por la plantilla «SV 2026-07» (vigente desde 01/07/2026)" in after["feedback"]

    r = api.get("/api/v1/hcm/employee-templates/applicable/", {"country": "sv", "date": "2026-08-15"})
    assert r.status_code == 200 and r.json()["name"] == "SV 2026-07"
    assert any(f["key"] == "pension_fund" and f["choices"] == ["CONFIA", "CRECER"] for f in r.json()["form"]["fields"])


# --------------------------------------------------------------------- alta individual
def test_individual_create_generates_code_file_and_eav(api, hr_user, wfm_user, countries):
    api.force_login(hr_user)
    r = api.post(EMPLOYEES, sv_row(), format="json")
    assert r.status_code == 201, r.json()
    body = r.json()
    code = body["employee"]["employee_code"]
    assert code.startswith("SV-2026-") and is_valid_employee_code(code)
    assert body["feedback"].startswith(f"Se creó el empleado {code} — Ana López")
    assert body["employee"]["cost_center"] == "SV-OPS"
    assert body["employee"]["attributes"]["pension_fund"] == "CRECER"  # forma canónica de la opción
    assert body["employee"]["national_id_type"] == "DUI"  # default de la plantilla

    employee = Employee.objects.get(employee_code=code)
    assert employee.created_by == hr_user.username
    assert DigitalFile.objects.filter(employee=employee).exists()
    values = dict(EmployeeAttributeValue.objects.filter(employee=employee).values_list("attribute__code", "value"))
    assert values["social_security_number"] == "123456789"
    assert EmployeeAttributeValue.objects.filter(employee=employee).first().template.country == countries["SV"]

    api.force_login(wfm_user)  # WFM ve empleados pero no salarios ni atributos sensibles
    detail = api.get(f"{EMPLOYEES}{code}/").json()
    assert "base_salary" not in detail and "pension_id" not in detail["attributes"]
    assert detail["attributes"]["pension_fund"] == "CRECER"  # no sensible: visible
    assert {"base_salary", "pension_id", "social_security_number"} <= set(detail["restricted_fields"])


def test_individual_create_explains_country_specific_errors(api, hr_user):
    api.force_login(hr_user)
    before = Employee.objects.count()
    r = api.post(
        EMPLOYEES,
        sv_row(national_id_number="1234", social_security_number="", cost_center="GT-OPS", pension_fund="FUTURO"),
        format="json",
    )
    assert r.status_code == 400
    body = r.json()
    codes = {(e["field"], e["code"]) for e in body["errors"]}
    assert ("national_id_number", "invalid_format") in codes
    assert ("social_security_number", "required") in codes
    assert ("cost_center", "cost_center_country") in codes
    assert ("pension_fund", "invalid_choice") in codes
    assert "«Número de documento de identidad (DUI)» con valor «1234» no tiene el formato esperado; ejemplo válido: 01234567-8." in body["detail"]
    assert "pertenece a Guatemala, no a El Salvador" in body["detail"]
    assert Employee.objects.count() == before


def _sequences():
    return dict(EmployeeCodeSequence.objects.values_list("country_id", "last_value"))


def test_validate_endpoint_does_not_persist_anything(api, hr_user, countries):
    api.force_login(hr_user)
    employees, sequences = Employee.objects.count(), _sequences()
    r = api.post(f"{EMPLOYEES}validate/", sv_row(), format="json")
    assert r.status_code == 200 and r.json()["valid"]
    assert Employee.objects.count() == employees and _sequences() == sequences


def test_employee_endpoints_rbac(api, wfm_user, employee_user):
    api.force_login(wfm_user)
    assert api.get(EMPLOYEES).status_code == 200
    assert api.post(EMPLOYEES, sv_row(), format="json").status_code == 403
    assert api.get(IMPORTS).status_code == 403
    api.force_login(employee_user)
    assert api.get(EMPLOYEES).status_code == 403
    assert api.get("/api/v1/hcm/employee-templates/").status_code == 403


# --------------------------------------------------------------------- carga masiva
def test_batch_is_atomic_per_country(api, hr_user):
    api.force_login(hr_user)
    rows = [
        sv_row(),
        sv_row(first_name="Beto", national_id_number="11111111-1", work_email="beto@metamorph.test", pension_id=""),
        gt_row(),
    ]
    r = upload(api, to_csv(rows))
    assert r.status_code == 201, r.json()
    report = r.json()
    assert report["status"] == "PARTIAL"
    assert (report["created_rows"], report["error_rows"], report["skipped_rows"]) == (1, 1, 1)
    by_row = {row["row_number"]: row for row in report["rows"]}
    assert by_row[2]["status"] == "NOT_APPLIED"
    assert "no se aplicó porque la carga es «todo o nada por país» y la fila 3 de El Salvador tiene errores" in by_row[2]["feedback"]
    assert by_row[3]["status"] == "ERROR"
    assert by_row[3]["feedback"].startswith("Fila 3 (El Salvador): no se creó el empleado por 1 error: Falta el campo obligatorio «NUP (AFP)»")
    assert by_row[4]["status"] == "CREATED" and by_row[4]["employee_code"].startswith("GT-2026-")
    assert "Se crearon 1 empleado (Guatemala: 1)" in report["summary"]
    assert "1 fila con errores (El Salvador: 1)" in report["summary"]
    assert "campo obligatorio faltante (1)" in report["summary"]
    assert not Employee.objects.filter(national_id_number__in=["01234567-8", "11111111-1"]).exists()
    gt = Employee.objects.get(country__country_code="GT")
    assert gt.national_id_number == "1234567890101" and gt.national_id_type == "DPI"
    assert gt.attribute_values.get(attribute__code="tax_id").value == "1234567-K"  # columna «NIT» = etiqueta del país


def test_batch_row_atomicity_creates_valid_rows(api, hr_user):
    api.force_login(hr_user)
    rows = [sv_row(), sv_row(national_id_number="22222222-2", birth_date="2015-01-01", work_email="nino@metamorph.test")]
    report = upload(api, to_csv(rows, delimiter=";"), atomicity="ROW").json()
    assert report["status"] == "PARTIAL" and report["created_rows"] == 1
    assert "exige al menos 18" in report["rows"][1]["feedback"]
    assert "Se detectó «;» como separador de columnas." in report["notes"]


def test_batch_dry_run_validates_everything_and_rolls_back(api, hr_user, countries):
    api.force_login(hr_user)
    employees, sequences = Employee.objects.count(), _sequences()
    next_sv = sequences.get(countries["SV"].pk, 0) + 1
    r = upload(api, to_csv([sv_row(), gt_row()]), dry_run="true")
    assert r.status_code == 200
    report = r.json()
    assert report["status"] == "DRY_RUN" and report["created_rows"] == 0
    assert all(row["status"] == "VALID" for row in report["rows"])
    assert f"recibiría un ID como SV-2026-{next_sv:06d}-" in report["rows"][0]["feedback"]
    assert "No se guardó ningún empleado." in report["summary"]
    assert Employee.objects.count() == employees
    assert _sequences() == sequences  # correlativos devueltos


def test_batch_reports_id_format_duplicates_and_unknown_columns(api, hr_user, make_employee):
    existing = make_employee("SV")
    good = format_employee_code("SV", 2026, 999)
    bad_check = good[:-1] + str((int(good[-1]) + 1) % 10)
    api.force_login(hr_user)
    rows = [
        sv_row(employee_code="SV-26-1"),
        sv_row(national_id_number="33333333-3", work_email="x1@metamorph.test", employee_code=bad_check),
        sv_row(national_id_number="33333333-3", work_email="x2@metamorph.test"),
        sv_row(national_id_number="44444444-4", work_email="x3@metamorph.test", employee_code=existing.employee_code),
        {**sv_row(national_id_number="55555555-5", work_email="x4@metamorph.test"), "color_favorito": "azul"},
    ]
    report = upload(api, to_csv(rows), atomicity="ROW").json()
    rows_by = {r["row_number"]: r for r in report["rows"]}
    assert "no tiene el formato {PAÍS}-AAAA-NNNNNN-D" in rows_by[2]["feedback"]
    assert f"El ID corporativo «{bad_check}» tiene un dígito verificador incorrecto" in rows_by[3]["feedback"]
    assert "ya aparece en la fila 3 del archivo" in rows_by[4]["feedback"]
    assert f"El empleado {existing.employee_code}" in rows_by[5]["feedback"]
    assert rows_by[6]["status"] == "CREATED"
    assert all(w["code"] != "unknown_field" for row in report["rows"] for w in row["warnings"])  # va al lote, no a la fila
    assert any("«color_favorito»" in note for note in report["notes"])


def test_batch_accepts_excel_with_dates_and_numeric_cells(api, hr_user):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    row = sv_row(social_security_number=12345678, birth_date=date(1991, 2, 3), hire_date=date(2026, 5, 4), base_salary=900.5)
    sheet.append(list(row))
    sheet.append(list(row.values()))
    buffer = io.BytesIO()
    workbook.save(buffer)
    api.force_login(hr_user)
    report = upload(api, buffer.getvalue(), name="altas.xlsx").json()
    assert report["source_format"] == "XLSX" and report["status"] == "FAILED"
    feedback = report["rows"][0]["feedback"]
    assert "«Número de afiliación ISSS» con valor «12345678» no tiene el formato esperado" in feedback
    assert "Excel pudo eliminar ceros a la izquierda" in feedback

    sheet.delete_rows(2)
    sheet.append(list(sv_row(social_security_number="012345678", birth_date=date(1991, 2, 3), hire_date=date(2026, 5, 4), base_salary=900.5).values()))
    buffer = io.BytesIO()
    workbook.save(buffer)
    report = upload(api, buffer.getvalue(), name="altas.xlsx").json()
    assert report["status"] == "COMPLETED", report["rows"]
    employee = Employee.objects.get(national_id_number="01234567-8")
    assert employee.hire_date == date(2026, 5, 4) and str(employee.base_salary) == "900.50"


def test_batch_accepts_json_rows_in_body(api, hr_user):
    api.force_login(hr_user)
    r = api.post(IMPORTS, {"rows": [sv_row(), {"attributes": {"x": 1}}, "texto"], "atomicity": "ROW"}, format="json")
    assert r.status_code == 201
    rows = r.json()["rows"]
    assert rows[0]["status"] == "CREATED"
    assert rows[1]["feedback"].startswith("Registro 2 (país no identificado): no se creó el empleado")
    assert "no es un objeto con campos" in rows[2]["feedback"]


@pytest.mark.parametrize(
    ("name", "content", "fragment"),
    [
        ("altas.xls", b"x", "no está soportado"),
        ("altas.csv", b"", "está vacío"),
        ("altas.csv", "country,country\nSV,SV\n".encode(), "está repetido"),
        ("altas.csv", b"country,first_name\n", "no contiene filas de datos"),
        ("altas.json", b"{no json", "El JSON no es válido"),
        ("altas.pdf", b"%PDF", "No se reconoce el tipo de archivo"),
    ],
)
def test_batch_rejects_unreadable_files_with_clear_message(api, hr_user, name, content, fragment):
    api.force_login(hr_user)
    r = upload(api, content, name=name)
    assert r.status_code == 400 and fragment in r.json()["detail"]
    assert not ImportBatch.objects.exists()


def test_import_history_and_row_filter(api, hr_user):
    api.force_login(hr_user)
    batch_id = upload(api, to_csv([sv_row(), sv_row(national_id_number="")]), atomicity="ROW").json()["id"]
    assert api.get(IMPORTS).json()["count"] == 1
    errors = api.get(f"{IMPORTS}{batch_id}/", {"row_status": "error"}).json()["rows"]
    assert [r["row_number"] for r in errors] == [3]
    assert ImportBatchRow.objects.get(batch_id=batch_id, row_number=2).employee is not None


def test_template_csv_download(api, hr_user, countries):
    api.force_login(hr_user)
    template = EmployeeTemplate.objects.get(country=countries["MX"])
    r = api.get(f"/api/v1/hcm/employee-templates/{template.pk}/csv/")
    assert r.status_code == 200 and r["Content-Type"].startswith("text/csv")
    header = r.content.decode("utf-8-sig").splitlines()[0].split(",")
    assert header[0] == "country" and "tax_id" in header and "social_security_number" in header


# --------------------------------------------------------------------- integridad en BD
def test_db_rejects_cost_center_from_another_country(make_employee):
    employee = make_employee("SV")
    employee.cost_center = CostCenter.objects.get(code="GT-OPS")
    with pytest.raises(IntegrityError), transaction.atomic():
        employee.save(update_fields=["cost_center"])


def test_attribute_code_check_constraint():
    with pytest.raises(IntegrityError), transaction.atomic():
        AttributeDefinition.objects.create(code="Bad-Code", name="x")


# --------------------------------------------------------------------- /admin/
@pytest.fixture
def admin_client_su(client, make_user):
    su = make_user("root.test", "ADMIN", is_superuser=True)
    client.force_login(su)
    return client


def test_admin_pages_render(admin_client_su, make_employee, countries):
    employee = make_employee("SV")
    template = EmployeeTemplate.objects.get(country=countries["SV"])
    for url in [
        "/admin/",
        "/admin/employees/employeetemplate/",
        f"/admin/employees/employeetemplate/{template.pk}/change/",
        "/admin/employees/employeetemplate/add/",
        "/admin/employees/attributedefinition/",
        "/admin/common/country/",
        "/admin/common/costcenter/",
        "/admin/system/usersession/",
        "/admin/system/auditevent/",
    ]:
        r = admin_client_su.get(url)
        assert r.status_code == 200, url
    page = admin_client_su.get(f"/admin/employees/employeetemplate/{template.pk}/change/").content.decode()
    assert "Número de afiliación ISSS" in page and "&quot;core_fields&quot;" in page
    # Fase 5: personas, cuentas y datos operativos ya no se gestionan en /admin/.
    for url in [
        "/admin/employees/employeeattributevalue/",
        "/admin/employees/importbatch/",
        "/admin/employees/importbatch/add/",
        "/admin/employees/importbatchrow/",
        "/admin/hcm/employee/",
        f"/admin/hcm/employee/{employee.pk}/change/",
        "/admin/accounts/customuser/add/",  # Fase 25: las cuentas se gestionan en /admin/, pero no se crean ahí
        "/admin/auth/group/",
    ]:
        assert admin_client_su.get(url).status_code in (403, 404), url


def test_admin_rejects_invalid_template_json(admin_client_su, countries):
    r = admin_client_su.post(
        "/admin/employees/employeetemplate/add/",
        {
            "country": countries["SV"].pk,
            "name": "Rota",
            "effective_date": "2027-01-01",
            "is_active": "on",
            "schema": json.dumps({"attributes": {"no_existe": {}}}),
            "notes": "",
        },
    )
    assert r.status_code == 200
    assert "no existe en el catálogo de atributos dinámicos" in r.content.decode()
    assert not EmployeeTemplate.objects.filter(name="Rota").exists()


def test_admin_role_can_use_admin_and_hr_cannot(client, make_user):
    admin_role = make_user("admin.rol", "ADMIN")
    client.force_login(admin_role)
    assert client.get("/admin/employees/employeetemplate/").status_code == 200
    assert client.get("/admin/system/auditevent/").status_code == 200
    client.force_login(make_user("rrhh.rol", "HR"))
    assert client.get("/admin/").status_code == 302  # sin is_staff
