"""Fase 23: selector jerárquico de colaboradores en las AP (org.fn_EmployeesUnderLeader), paleta dual (global y
personal) compartida con el Django Admin, calendario de feriados (copia de año con Semana Santa en SQL Server) y logos
corporativos (favicon, barra superior, cabecera de documentos / PDF)."""

from datetime import date

import pytest
from django.db import connection
from django.utils import timezone

from apps.holidays.models import Holiday
from apps.operations.models import OperationalLeader
from apps.payroll import pdf
from apps.roster.models import RosterAssignment, RosterAttribute
from apps.system import brand
from apps.system.models import PlatformSettings

pytestmark = pytest.mark.django_db
PA = "/api/v1/personnel-actions"
L = "/api/v1/roster/hierarchy/leaders"


def _leader(api, level, emp, reports_to=None):
    r = api.post(f"{L}/", {"level": level, "employee_code": emp.employee_code, "reports_to": reports_to}, format="json")
    assert r.status_code == 201, r.json()
    return r.json()["leader"]


def _assign_tm(emp, leader_id):
    item = OperationalLeader.objects.get(pk=leader_id).roster_item
    RosterAssignment.objects.create(employee=emp, attribute=RosterAttribute.objects.get(code="team_manager"), value=item.code,
                                    item=item, effective_start=date(2026, 9, 1))


@pytest.fixture
def tree(api, wfm_user, make_employee, make_user):
    """Director → Manager → Supervisor A → Team Manager A → agente 0; Manager → Supervisor B → Team Manager B → agente 1."""
    api.force_login(wfm_user)
    p = {k: make_employee("SV", first_name=k, last_name="Jerarquía")
         for k in ("Dir", "Mgr", "SupA", "TmA", "SupB", "TmB", "Agente0", "Agente1")}
    d = _leader(api, "OPS_DIRECTOR", p["Dir"])
    m = _leader(api, "OPS_MANAGER", p["Mgr"], d["id"])
    sa = _leader(api, "ACCOUNT_SUPERVISOR", p["SupA"], m["id"])
    ta = _leader(api, "TEAM_MANAGER", p["TmA"], sa["id"])
    sb = _leader(api, "ACCOUNT_SUPERVISOR", p["SupB"], m["id"])
    tb = _leader(api, "TEAM_MANAGER", p["TmB"], sb["id"])
    _assign_tm(p["Agente0"], ta["id"])
    _assign_tm(p["Agente1"], tb["id"])
    sup = make_user("sup.a.p23", "WFM", employee=p["SupA"])
    tm = make_user("tm.a.p23", "WFM", employee=p["TmA"])
    return {"people": p, "sup": sup, "tm": tm}


# ================================================================== selector jerárquico
def test_hierarchy_picker_and_server_validation(api, tree, hr_user, admin_user):
    p = tree["people"]
    with connection.cursor() as c:
        c.execute("SELECT employee_id, depth, relation FROM org.fn_EmployeesUnderLeader(%s, %s) ORDER BY depth", [p["SupA"].pk, timezone.localdate()])
        rows = c.fetchall()
    assert [(r[0], r[1], r[2]) for r in rows] == [(p["TmA"].pk, 1, "DIRECT"), (p["Agente0"].pk, 2, "INDIRECT")]

    # El supervisor A solo ve su jerarquía (directa e indirecta), nunca a sí mismo ni a la de B.
    api.force_login(tree["sup"])
    body = api.get(f"{PA}/employees/picker/").json()
    assert body["scope"] == "hierarchy"
    got = {r["employee_code"]: r["relation"] for r in body["results"]}
    assert got == {p["TmA"].employee_code: "DIRECT", p["Agente0"].employee_code: "INDIRECT"}
    assert api.get(f"{PA}/employees/picker/", {"q": "Agente0"}).json()["total"] == 1
    assert api.get(f"{PA}/employees/picker/", {"q": "Agente1"}).json()["total"] == 0

    # El servidor rechaza una AP fuera de su jerarquía (aunque se envíe el ID a mano) y acepta las de su equipo.
    today = timezone.localdate()
    payload = {"action_type": "AP_CAMBIO_ORGANIZACIONAL", "effective_date": today.isoformat(), "justification": "Fase 23",
               "values": {"job_title": "Agente senior"}}
    r = api.post(f"{PA}/", {**payload, "employee_code": p["Agente1"].employee_code}, format="json")
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "out_of_scope"
    r = api.post(f"{PA}/", {**payload, "employee_code": p["SupA"].employee_code}, format="json")
    assert r.status_code == 400 and "a sí mismo" in r.json()["errors"][0]["message"]
    r = api.post(f"{PA}/", {**payload, "employee_code": p["Agente0"].employee_code}, format="json")
    assert r.status_code == 201, r.json()

    # El Team Manager A solo ve a su agente directo.
    api.force_login(tree["tm"])
    assert [r["employee_code"] for r in api.get(f"{PA}/employees/picker/").json()["results"]] == [p["Agente0"].employee_code]

    # RRHH sin equipo a cargo (área de soporte): toda la organización; en modo estricto, nadie.
    api.force_login(hr_user)
    assert api.get(f"{PA}/employees/picker/").json()["scope"] == "support"
    s = PlatformSettings.objects.filter(pk=1).first() or PlatformSettings(pk=1)
    s.ap_full_scope_roles = []
    s.save()
    body = api.get(f"{PA}/employees/picker/").json()
    assert body["scope"] == "hierarchy" and body["total"] == 0
    r = api.post(f"{PA}/", {**payload, "employee_code": p["Agente1"].employee_code}, format="json")
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "out_of_scope"
    # El Administrador: toda la organización.
    api.force_login(admin_user)
    body = api.get(f"{PA}/employees/picker/", {"q": "Jerarquía"}).json()
    assert body["scope"] == "all" and body["total"] == 8
    # El Director ve toda su cadena (6 personas).
    with connection.cursor() as c:
        c.execute("SELECT COUNT(*) FROM org.fn_EmployeesUnderLeader(%s, %s)", [p["Dir"].pk, timezone.localdate()])
        assert c.fetchone()[0] == 7


# ================================================================== paleta dual y Django Admin
def test_dual_palette_and_admin_theme(api, admin_user, employee_user):
    from django.test import Client

    api.force_login(employee_user)
    me = api.get("/api/v1/system/appearance/me/").json()
    assert me["personal"]["saved"] is False and me["effective"]["source"] == "global" and me["effective"]["palette"] == "NAVY"
    r = api.put("/api/v1/system/appearance/me/", {"palette": "TEAL", "theme": "dark", "time_mode": "decimal"}, format="json")
    assert r.status_code == 200
    eff = r.json()["effective"]
    assert (eff["source"], eff["primary"], eff["theme"]) == ("personal", "#0f4c5c", "dark")
    assert api.put("/api/v1/system/appearance/me/", {"palette": "CUSTOM"}, format="json").status_code == 400
    assert api.put("/api/v1/system/appearance/me/", {"theme": "neon"}, format="json").status_code == 400
    # El Administrador cambia la global: quien no tiene paleta personal la hereda (respaldo de fábrica).
    api.force_login(admin_user)
    assert api.patch("/api/v1/system/appearance/", {"brand_palette": "WINE"}, format="json").status_code == 200
    api.force_login(employee_user)
    r = api.delete("/api/v1/system/appearance/me/")
    assert r.json()["effective"]["source"] == "global" and r.json()["effective"]["palette"] == "WINE"
    assert r.json()["personal"]["theme"] == "dark"  # el resto de preferencias se conserva

    # Django Admin: logotipo, favicon y la paleta efectiva del usuario (personal sobre la global).
    api.force_login(admin_user)
    api.put("/api/v1/system/appearance/me/", {"palette": "CUSTOM", "accent": "#aa3355"}, format="json")
    web = Client()
    web.force_login(admin_user)
    html = web.get("/admin/").content.decode()
    assert "brand/app_header_logo.png" in html and "brand/favicon.ico" in html
    assert "--header-bg: #4c1726" in html and "--primary: #aa3355" in html  # primario derivado del acento personal
    web.force_login(admin_user)
    api.delete("/api/v1/system/appearance/me/")
    html = web.get("/admin/").content.decode()
    assert "--header-bg: #5b1a32" in html  # global (Vino)


# ================================================================== calendario de feriados
def test_holiday_calendar_copy_year_and_sql(api, hr_user, wfm_user, countries):
    with connection.cursor() as c:
        c.execute("SELECT wfm.fn_EasterSunday(2026), wfm.fn_EasterSunday(2028)")
        assert c.fetchone() == (date(2026, 4, 5), date(2028, 4, 16))
        c.execute("SELECT IsoWeekday, HolidayName FROM wfm.vw_HolidayCalendar WHERE CountryCode = 'SV' AND HolidayDate = '2026-01-01'")
        assert c.fetchone() == (4, "Año Nuevo")  # jueves
    api.force_login(wfm_user)
    assert api.post("/api/v1/holidays/copy-year/", {"country": "SV", "from_year": 2026, "to_year": 2028}, format="json").status_code == 403
    api.force_login(hr_user)
    r = api.post("/api/v1/holidays/copy-year/", {"country": "SV", "from_year": 2026, "to_year": 2028}, format="json")
    assert r.status_code == 201, r.json()
    sv = countries["SV"]
    got = {h.name: h.date for h in Holiday.objects.filter(country=sv, date__year=2028)}
    assert len(got) == 11 and got["Navidad"] == date(2028, 12, 25)
    assert (got["Jueves Santo"], got["Viernes Santo"], got["Sábado Santo"]) == (date(2028, 4, 13), date(2028, 4, 14), date(2028, 4, 15))
    r = api.post("/api/v1/holidays/copy-year/", {"country": "SV", "from_year": 2026, "to_year": 2028}, format="json")
    assert r.status_code == 200 and r.json()["created"] == []  # idempotente
    # Edición completa desde el calendario: nombre, recargo, desactivar y eliminar.
    h = Holiday.objects.get(country=sv, date=date(2028, 5, 10))
    r = api.patch(f"/api/v1/holidays/{h.pk}/", {"name": "Día de la Madre (asueto)", "premium_percent": "150", "is_active": False}, format="json")
    assert r.status_code == 200 and r.json()["is_active"] is False and float(r.json()["premium_percent"]) == 150
    assert api.delete(f"/api/v1/holidays/{h.pk}/").status_code == 204


# ================================================================== logos corporativos
def test_brand_assets_in_documents():
    brand.build()
    for name in ("app_header_logo.png", "doc_header_logo.png", "doc_header_logo_pdf.png", "favicon.ico", "favicon-32.png"):
        assert (brand.STATIC_BRAND / name).exists(), name
    from PIL import Image

    app = Image.open(brand.STATIC_BRAND / "app_header_logo.png")
    assert app.height == 96 and app.mode == "RGBA"
    # El logotipo de la barra queda sin «polvo» semitransparente: casi todo es transparente u opaco.
    hist = app.getchannel("A").histogram()
    assert sum(hist[1:12]) == 0 and sum(hist[12:60]) < 0.05 * app.width * app.height
    content = {"folio": "BOL-X", "payroll_code": "P", "currency": "USD", "employee": {"code": "SV-1", "name": "Prueba"}, "period": {},
               "lines": [], "totals": {"gross": "1", "deductions": "0", "net": "1"}}
    body = pdf.payslip_pdf(content)
    assert body.startswith(b"%PDF") and b"/Subtype /Image" in body and b"/XObject << /ImLogo" in body
