"""Fase 7: máscaras, catálogo de bancos, vigencia, ciclo de vida, vincular cuenta existente,
catálogos operativos (clientes / marcas / LOB / sub-LOB) y General IDs."""

import csv
import io
from datetime import date

import pytest
from django.db import DatabaseError, transaction

from apps.accounts.models import CustomUser
from apps.common.models import Country
from apps.employees.masks import apply_mask, as_masks, mask_error
from apps.employees.models import Bank, EmployeeAttributeValue, EmployeeTemplate
from apps.employees.schema import validate_template_schema
from apps.general_ids.models import EmployeeGeneralId, GeneralIdType, GeneralIdTypeBrand, GeneralIdTypeClient
from apps.hcm.models import Employee
from apps.operations.models import Brand, Client, LineOfBusiness, SubLineOfBusiness
from apps.roster.models import RosterDimensionItem
from apps.system.models import AuditEvent
from tests.test_employees import EMPLOYEES, gt_row, sv_row

pytestmark = pytest.mark.django_db
GID = "/api/v1/general-ids"


# ------------------------------------------------------------------ 1. máscaras
def test_mask_engine():
    assert apply_mask(as_masks("########-#"), "012345678") == "01234567-8"
    assert apply_mask(as_masks("########-#"), "01234567-8") == "01234567-8"
    assert apply_mask(as_masks("########-#"), "0123") == "0123"  # incompleto: lo reporta el pattern
    nit = as_masks(["####-######-###-#", "########-#"])
    assert apply_mask(nit, "06140101901011") == "0614-010190-101-1"
    assert apply_mask(nit, "012345678") == "01234567-8"
    assert apply_mask(as_masks("@@-###"), "ab123") == "ab-123" and apply_mask(as_masks("@@-###"), "12345") == "12345"
    assert mask_error("abc") and mask_error(["##", "##"]) and mask_error("####-####") is None


def test_form_accepts_values_without_dashes(api, hr_user):
    api.force_login(hr_user)
    r = api.post(
        EMPLOYEES,
        sv_row(national_id_number="012345678", phone_number="71234567", tax_id="06140101901011", emergency_contact_phone="70000000"),
        format="json",
    )
    assert r.status_code == 201, r.json()
    emp = r.json()["employee"]
    assert emp["national_id_number"] == "01234567-8" and emp["phone_number"] == "7123-4567"
    assert emp["attributes"]["tax_id"] == "0614-010190-101-1"
    # GT: DPI con máscara "#### ##### ####" + strip_spaces -> se guarda solo con dígitos.
    r = api.post(EMPLOYEES, gt_row(numero_documento="1234567890101"), format="json")
    assert r.status_code == 201, r.json()
    assert r.json()["employee"]["national_id_number"] == "1234567890101"


def test_template_exposes_masks_and_validates_them(api, hr_user):
    api.force_login(hr_user)
    form = api.get("/api/v1/hcm/employee-templates/applicable/", {"country": "SV", "date": "2026-03-01"}).json()["form"]
    fields = {f["key"]: f for f in form["fields"]}
    assert fields["phone_number"]["mask"] == ["####-####"]
    assert fields["national_id_number"]["patterns_by_type"]["DUI"]["mask"] == "########-#"
    with pytest.raises(Exception) as exc:
        validate_template_schema({"core_fields": {"phone_number": {"mask": "sin marcadores"}, "birth_date": {"mask": "##"}}})
    text = str(exc.value)
    assert "no tiene marcadores" in text and "solo aplica a campos de texto" in text


# ------------------------------------------------------------------ 1. bancos
def test_bank_is_a_catalog_dropdown(api, hr_user, countries):
    api.force_login(hr_user)
    form = api.get("/api/v1/hcm/employee-templates/applicable/", {"country": "SV", "date": "2026-03-01"}).json()["form"]
    bank = next(f for f in form["fields"] if f["key"] == "bank_name")
    assert bank["catalog"] == "BANK" and {"value": "AGRICOLA", "label": "Banco Agrícola", "is_active": True} in bank["options"]
    assert all(o["value"] in set(Bank.objects.filter(country=countries["SV"]).values_list("code", flat=True)) for o in bank["options"])

    bad = api.post(f"{EMPLOYEES}validate/", sv_row(bank_name="Banco Inventado"), format="json").json()
    assert not bad["valid"] and any(e["field"] == "bank_name" and e["code"] == "invalid_choice" for e in bad["errors"])
    # Se acepta el código o el nombre (cargas masivas); se guarda el código.
    r = api.post(EMPLOYEES, sv_row(bank_name="banco agricola", bank_account_number="0012345678"), format="json")
    assert r.status_code == 201, r.json()
    code = r.json()["employee"]["employee_code"]
    assert r.json()["employee"]["attributes"]["bank_name"] == "AGRICOLA"
    dossier = api.get(f"{EMPLOYEES}{code}/digital-file/").json()
    entry = next(f for tab in dossier["tabs"] for s in tab["sections"] for f in s["fields"] if f["key"] == "bank_name")
    assert entry["value"] == "AGRICOLA" and entry["display"] == "Banco Agrícola"

    # Banco desactivado: el expediente lo conserva con advertencia; no se ofrece para nuevas altas.
    Bank.objects.filter(country=countries["SV"], code="AGRICOLA").update(is_active=False)
    check = api.post(f"{EMPLOYEES}{code}/validate/", {"phone_number": "7999-0000"}, format="json").json()
    assert check["valid"] and any(w["code"] == "inactive_option" for w in check["warnings"])


def test_legacy_free_text_bank_is_kept_until_changed(api, hr_user):
    api.force_login(hr_user)
    r = api.post(EMPLOYEES, sv_row(bank_name="AGRICOLA"), format="json")
    code = r.json()["employee"]["employee_code"]
    EmployeeAttributeValue.objects.filter(attribute__code="bank_name").update(value="Banco viejo S.A.")
    ok = api.post(f"{EMPLOYEES}{code}/validate/", {"bank_name": "Banco viejo S.A."}, format="json").json()
    assert ok["valid"] and any(w["code"] == "legacy_catalog_value" for w in ok["warnings"])
    bad = api.post(f"{EMPLOYEES}{code}/validate/", {"bank_name": "Otro texto"}, format="json").json()
    assert not bad["valid"]


# ------------------------------------------------------------------ 1. vigencia de la plantilla
def test_hire_before_country_catalog_date_uses_template_vigency(api, hr_user, countries):
    """Corrección: el país se registró en el catálogo el 2026-01-01, pero la plantilla base rige desde 2000-01-01."""
    api.force_login(hr_user)
    assert countries["SV"].effective_start_date > date(2025, 6, 1)
    r = api.post(EMPLOYEES, sv_row(hire_date="2025-06-01"), format="json")
    assert r.status_code == 201, r.json()
    # Solo un país dado de baja bloquea ingresos posteriores a su fecha de baja.
    Country.objects.filter(country_code="SV").update(effective_end_date=date(2026, 1, 31))
    bad = api.post(f"{EMPLOYEES}validate/", sv_row(hire_date="2026-03-01", national_id_number="07654321-0"), format="json").json()
    assert any(e["code"] == "country_not_effective" for e in bad["errors"])
    # Sin plantilla vigente a la fecha: mensaje específico de plantilla.
    EmployeeTemplate.objects.filter(country__country_code="GT").update(effective_date=date(2026, 5, 1))
    bad = api.post(f"{EMPLOYEES}validate/", gt_row(fecha_ingreso="2026-04-30"), format="json").json()
    assert bad["errors"][0]["code"] == "no_template" and "plantilla activa de Guatemala" in bad["errors"][0]["message"]
    assert api.post(f"{EMPLOYEES}validate/", gt_row(fecha_ingreso="2026-05-01"), format="json").json()["valid"]


# ------------------------------------------------------------------ 1. ciclo de vida
def test_lifecycle_statuses(api, hr_user):
    api.force_login(hr_user)
    statuses = api.get("/api/v1/hcm/catalogs/").json()["employment_statuses"]
    assert statuses == [
        {"value": "ACTIVE", "label": "Activo"}, {"value": "INACTIVE", "label": "Inactivo"}, {"value": "TERMINATED", "label": "Terminado"}
    ]
    code = api.post(EMPLOYEES, sv_row(), format="json").json()["employee"]["employee_code"]
    url = f"{EMPLOYEES}{code}/"
    assert api.patch(url, {"employment_status": "Inactivo"}, format="json").json()["employee"]["employment_status"] == "INACTIVE"
    r = api.patch(url, {"employment_status": "TERMINADO"}, format="json")
    assert r.status_code == 400 and "Fecha de terminación" in r.json()["feedback"]
    r = api.patch(url, {"employment_status": "Terminado", "termination_date": "2026-06-30"}, format="json")
    assert r.json()["employee"]["employment_status"] == "TERMINATED" and r.json()["employee"]["employment_status_label"] == "Terminado"
    assert api.get(EMPLOYEES, {"status": "NOT_ACTIVE"}).json()["count"] == 1
    # La BD solo admite los tres estados oficiales.
    with pytest.raises(DatabaseError), transaction.atomic():
        Employee.objects.filter(employee_code=code).update(employment_status="SUSPENDED")


# ------------------------------------------------------------------ 2. vincular cuenta existente
def test_link_existing_account_from_the_dossier(api, admin_user, hr_user, make_user, make_employee):
    emp = make_employee("SV")
    loose = make_user("cuenta.suelta", "ADMIN", with_employee=False)
    api.force_login(admin_user)
    candidates = api.get(f"{EMPLOYEES}{emp.employee_code}/user-account/candidates/", {"search": "suelta"}).json()["results"]
    assert [c["username"] for c in candidates] == ["cuenta.suelta"]
    # RRHH no administra cuentas de Administrador: ni las ve como candidatas ni puede vincularlas.
    api.force_login(hr_user)
    assert api.get("/api/v1/hcm/user-account-candidates/", {"search": "suelta"}).json()["results"] == []
    r = api.post(f"{EMPLOYEES}{emp.employee_code}/user-account/link/", {"user_id": loose.pk}, format="json")
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "role_not_allowed"

    api.force_login(admin_user)
    r = api.post(f"{EMPLOYEES}{emp.employee_code}/user-account/link/", {"user_id": loose.pk}, format="json")
    assert r.status_code == 200, r.json()
    loose.refresh_from_db()
    assert loose.employee_id == emp.employee_code and loose.cost_center_id == emp.cost_center_id
    assert AuditEvent.objects.filter(action="user_linked").exists()
    # Ya vinculado: ni el empleado ni la cuenta admiten otro vínculo.
    other = make_user("otra.suelta", "ADMIN", with_employee=False)
    r = api.post(f"{EMPLOYEES}{emp.employee_code}/user-account/link/", {"user_id": other.pk}, format="json")
    assert r.json()["errors"][0]["code"] == "already_linked"
    r = api.post(f"{EMPLOYEES}{make_employee('SV').employee_code}/user-account/link/", {"user_id": loose.pk}, format="json")
    assert r.json()["errors"][0]["code"] == "user_linked"


def test_link_existing_account_during_hire(api, admin_user, make_user):
    loose = make_user("cuenta.alta", "ADMIN", with_employee=False)
    api.force_login(admin_user)
    preview = api.post(f"{EMPLOYEES}validate/", sv_row(user_account={"mode": "link", "user_id": loose.pk}), format="json").json()
    assert preview["valid"] and preview["user_account_preview"]["username"] == "cuenta.alta"
    assert not CustomUser.objects.get(pk=loose.pk).employee_id
    r = api.post(EMPLOYEES, sv_row(user_account={"mode": "link", "user_id": loose.pk}), format="json")
    assert r.status_code == 201, r.json()
    assert "quedó vinculada" in r.json()["feedback"] and "temporary_password" not in r.json()["user_account"]
    assert CustomUser.objects.get(pk=loose.pk).employee_id == r.json()["employee"]["employee_code"]
    # Cuenta inexistente: no se crea el empleado.
    before = Employee.objects.count()
    bad = api.post(EMPLOYEES, sv_row(national_id_number="07654321-0", user_account={"mode": "link", "user_id": 999999}), format="json")
    assert bad.status_code == 400 and Employee.objects.count() == before


# ------------------------------------------------------------------ 3. catálogos operativos
@pytest.fixture
def ops(countries):
    acme = Client.objects.create(code="ACME", name="Acme Corp", legal_name="Acme Corporation S.A.")
    globex = Client.objects.create(code="GLOBEX", name="Globex", country=countries["SV"])
    mobile = Brand.objects.create(code="ACME-MOB", name="Acme Mobile", client=acme)
    tv = Brand.objects.create(code="ACME-TV", name="Acme TV", client=acme)
    glx = Brand.objects.create(code="GLX-TV", name="Globex TV", client=globex)
    voice = LineOfBusiness.objects.create(code="VOICE", name="Voz")
    SubLineOfBusiness.objects.create(code="VOICE-TS", name="Soporte técnico", line=voice)
    return {"acme": acme, "globex": globex, "mobile": mobile, "tv": tv, "glx": glx, "voice": voice}


def test_catalogs_feed_the_roster_dimensions(api, wfm_user, ops):
    item = RosterDimensionItem.objects.get(dimension__code="BRAND", code="ACME-MOB")
    assert item.parent.code == "ACME" and item.name == "Acme Mobile"
    assert RosterDimensionItem.objects.get(dimension__code="SUB_LOB", code="VOICE-TS").parent.code == "VOICE"
    # Renombrar en el catálogo se refleja en el roster; desactivar un cliente desactiva sus marcas.
    ops["acme"].name = "ACME Global"
    ops["acme"].is_active = False
    ops["acme"].save()
    assert RosterDimensionItem.objects.get(dimension__code="CLIENT", code="ACME").name == "ACME Global"
    assert not Brand.objects.get(code="ACME-TV").is_active
    assert not RosterDimensionItem.objects.get(dimension__code="BRAND", code="ACME-TV").is_active

    api.force_login(wfm_user)
    body = api.get("/api/v1/operations/catalogs/").json()
    assert [c["code"] for c in body["clients"]] == ["GLOBEX"]
    assert body["lines_of_business"][0]["sub_lines"][0]["code"] == "VOICE-TS"
    roster_clients = next(d for d in api.get("/api/v1/roster/dimensions/").json() if d["code"] == "CLIENT")
    assert {i["code"] for i in roster_clients["items"]} == {"GLOBEX"}


def test_catalog_admin_pages(client, admin_user, ops):
    client.force_login(admin_user)
    for path in ["operations/client/", f"operations/client/{ops['acme'].pk}/change/", "operations/brand/",
                 "operations/lineofbusiness/", "operations/sublineofbusiness/", "general_ids/sourcetool/",
                 "general_ids/generalidtype/", "employees/bank/"]:
        assert client.get(f"/admin/{path}").status_code == 200, path
    assert client.get("/admin/general_ids/employeegeneralid/").status_code == 404  # los IDs se gestionan en la app


# ------------------------------------------------------------------ 4. General IDs
@pytest.fixture
def emp(make_employee):
    return make_employee("SV", hire_date=date(2026, 3, 1))


def add(http, emp, validate=False, **data):
    return http.post(f"{GID}/employees/{emp.employee_code}/{'validate/' if validate else ''}", data, format="json")


def test_general_ids_multiple_active_and_unique_values(api, wfm_user, ops, emp, make_employee):
    api.force_login(wfm_user)
    cats = api.get(f"{GID}/catalogs/").json()
    assert {"ACD_ID", "PAYROLL_TOOL_ID"} <= {t["code"] for t in cats["types"]}
    r = add(api, emp, id_type="PAYROLL_TOOL_ID", value="P-100", effective_start="2026-03-01")
    assert r.status_code == 201, r.json()
    # Varios IDs activos a la vez: ACD por cliente (el tipo lo permite) + Payroll.
    assert add(api, emp, id_type="ACD_ID", value="5001", client="ACME", brand="ACME-MOB", effective_start="2026-03-01").status_code == 201
    assert add(api, emp, id_type="ACD_ID", value="7001", client="GLOBEX", effective_start="2026-03-15").status_code == 201
    current = api.get(f"{GID}/employees/{emp.employee_code}/", {"as_of": "2026-04-01"}).json()["results"]
    assert sorted(g["value"] for g in current) == ["5001", "7001", "P-100"]

    # Payroll no admite dos vigentes a la vez.
    r = add(api, emp, id_type="PAYROLL_TOOL_ID", value="P-200", effective_start="2026-05-01")
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "overlap"
    payroll = EmployeeGeneralId.objects.get(value="P-100")
    r = api.post(f"{GID}/employees/{emp.employee_code}/{payroll.pk}/close/", {"effective_end": "2026-04-30"}, format="json")
    assert r.status_code == 200 and r.json()["general_id"]["effective_end"] == "2026-04-30"
    assert add(api, emp, id_type="PAYROLL_TOOL_ID", value="P-200", effective_start="2026-05-01").status_code == 201

    # Un valor solo identifica a un empleado a la vez (llave de JOIN).
    other = make_employee("SV", hire_date=date(2026, 3, 1))
    r = add(api, other, id_type="ACD_ID", value="5001", client="ACME", effective_start="2026-04-01")
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "duplicate_value"
    lookup = api.get(f"{GID}/lookup/", {"type": "ACD_ID", "value": "5001", "date": "2026-04-01"}).json()
    assert [m["employee_code"] for m in lookup["matches"]] == [emp.employee_code]
    assert api.get(f"{GID}/lookup/", {"type": "PAYROLL_TOOL_ID", "value": "P-100", "date": "2026-05-15"}).json()["matches"] == []

    # Reporte + CSV.
    report = api.get(f"{GID}/report/", {"from": "2026-04-01", "to": "2026-04-30", "type": "ACD_ID"}).json()
    assert report["count"] == 2
    rows = list(csv.reader(io.StringIO(api.get(f"{GID}/report/", {"from": "2026-05-01", "export": "csv"}).content.decode("utf-8-sig"))))
    assert rows[0][:7] == ["EmployeeCode", "FullName", "Country", "EmploymentStatus", "IdType", "Tool", "Value"]
    assert {r[6] for r in rows[1:]} == {"5001", "7001", "P-200"}
    assert AuditEvent.objects.filter(category="GIDS", action="general_id_created").count() == 4

    # El trigger de SQL Server es la última barrera (escritura directa fuera de la API).
    with pytest.raises(DatabaseError), transaction.atomic():
        EmployeeGeneralId.objects.create(
            employee=other, id_type=GeneralIdType.objects.get(code="ACD_ID"), value="5001",
            client=ops["acme"], effective_start=date(2026, 4, 1),
        )


def test_general_ids_scope_and_cascading_restrictions(api, hr_user, ops, emp):
    api.force_login(hr_user)
    acd = GeneralIdType.objects.get(code="ACD_ID")
    # GLOBAL no acepta cliente; CLIENT exige cliente; la marca debe ser del cliente.
    r = add(api, emp, validate=True, id_type="PAYROLL_TOOL_ID", value="X1", client="ACME", effective_start="2026-03-01")
    assert r.json()["errors"][0]["code"] == "scope"
    r = add(api, emp, validate=True, id_type="ACD_ID", value="1", effective_start="2026-03-01")
    assert r.json()["errors"][0]["code"] == "required"
    r = add(api, emp, validate=True, id_type="ACD_ID", value="1", client="GLOBEX", brand="ACME-MOB", effective_start="2026-03-01")
    assert r.json()["errors"][0]["code"] == "hierarchy"

    # Restricción en cascada: habilitado para ACME (todas sus marcas) y solo la marca GLX-TV de Globex.
    GeneralIdTypeClient.objects.create(id_type=acd, client=ops["acme"])
    GeneralIdTypeBrand.objects.create(id_type=acd, brand=ops["glx"])
    assert add(api, emp, validate=True, id_type="ACD_ID", value="1", client="ACME", effective_start="2026-03-01").json()["valid"]
    assert add(api, emp, validate=True, id_type="ACD_ID", value="1", brand="ACME-TV", effective_start="2026-03-01").json()["valid"]
    r = add(api, emp, validate=True, id_type="ACD_ID", value="1", client="GLOBEX", effective_start="2026-03-01").json()
    assert r["errors"][0]["code"] == "not_applicable" and "indique la marca" in r["errors"][0]["message"]
    assert add(api, emp, validate=True, id_type="ACD_ID", value="1", brand="GLX-TV", effective_start="2026-03-01").json()["valid"]
    other = Client.objects.create(code="INITECH", name="Initech")
    r = add(api, emp, validate=True, id_type="ACD_ID", value="1", client=other.code, effective_start="2026-03-01").json()
    assert r["errors"][0]["code"] == "not_applicable"
    types = {t["code"]: t for t in api.get(f"{GID}/catalogs/").json()["types"]}
    assert types["ACD_ID"]["applies_to"] == {"all": False, "clients": ["ACME"], "brands": ["GLX-TV"]}

    # Formato del valor (patrón configurable) y vigencia.
    GeneralIdType.objects.filter(pk=acd.pk).update(pattern=r"^\d{4}$", example="1234")
    r = add(api, emp, validate=True, id_type="ACD_ID", value="12", client="ACME", effective_start="2026-03-01").json()
    assert r["errors"][0]["code"] == "invalid_format" and "1234" in r["errors"][0]["message"]
    r = add(api, emp, validate=True, id_type="ACD_ID", value="1234", client="ACME", effective_start="2026-03-10",
            effective_end="2026-03-01").json()
    assert r["errors"][0]["code"] == "invalid_range"
    r = add(api, emp, validate=True, id_type="ACD_ID", value="1234", client="ACME", effective_start="2026-01-10").json()
    assert r["valid"] and r["warnings"][0]["code"] == "before_hire"


def test_general_ids_rbac(api, employee_user, wfm_user, emp):
    api.force_login(employee_user)
    assert api.get(f"{GID}/employees/{emp.employee_code}/").status_code == 403
    assert api.get(f"{GID}/catalogs/").status_code == 403
    api.force_login(wfm_user)
    body = api.get(f"{GID}/employees/{emp.employee_code}/").json()
    assert body["can_manage"] is True and body["results"] == []
