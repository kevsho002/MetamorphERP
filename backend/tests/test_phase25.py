"""Fase 25: control de sesiones y usuarios (bloqueo, panel de Django, Estado del sistema), esquemas por módulo en SQL
Server (sin el uso genérico de dbo), catálogo de vistas / SP / triggers, periódico virtual con acuse de recibo y
compliance, y la boleta desglosada por día de los cortes internos."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.communications import services as comms
from apps.communications.models import Announcement, AnnouncementAck, ComplianceSnapshot
from apps.payroll import engine, services
from apps.payroll.models import PayrollDay
from apps.scheduling.models import PayPeriod, ScheduleAssignment, TimeRecord, TimeRecordDay
from apps.system import policy
from apps.system.models import AuditEvent, PlatformSettings, UserSession

from .conftest import STRONG_PASSWORD

pytestmark = pytest.mark.django_db
N = "/api/v1/announcements"
DAY = {"days": {d: {"start": "08:00", "end": "17:00", "lunch_minutes": 60} for d in ("mon", "tue", "wed", "thu", "fri")}}


def _rows(sql, params=None):
    with connection.cursor() as c:
        c.execute(sql, params or [])
        return c.fetchall() if c.description else None


def _login(api, username, password=STRONG_PASSWORD):
    return api.post("/api/v1/auth/login/", {"username": username, "password": password}, format="json")


# ================================================================== esquemas por módulo
def test_erp_objects_left_dbo_for_module_schemas():
    dbo_tables = {n for (n,) in _rows("SELECT name FROM sys.tables WHERE schema_id = SCHEMA_ID(N'dbo')")}
    assert dbo_tables and all(n.startswith(("auth_", "django_")) or n == "sysdiagrams" for n in dbo_tables), dbo_tables
    dbo_modules = _rows("SELECT name FROM sys.objects WHERE schema_id = SCHEMA_ID(N'dbo') AND is_ms_shipped = 0 "
                        "AND type IN ('V', 'P', 'FN', 'IF', 'TF', 'TR') AND name NOT LIKE N'%diagram%'")
    assert dbo_modules == []
    where = dict(_rows("SELECT name, SCHEMA_NAME(schema_id) FROM sys.objects WHERE is_ms_shipped = 0"))
    expected = {
        "accounts_customuser": "sec", "accounts_customuser_groups": "sec", "sys_user_session": "sec", "sys_audit_event": "adm",
        "hcm_bank": "hcm", "gid_id_type": "hcm", "ops_leader": "org", "roster_assignment": "org", "sch_pay_cycle": "wfm",
        "adh_schedule_segment": "wfm", "hol_holiday": "wfm", "acd_aux_code": "acd", "pa_action": "pa", "pay_payroll_line": "fin",
        "pay_payroll_day": "fin", "com_announcement": "com", "vw_PayPayrollDetail": "fin", "vw_SchPayPeriod": "wfm",
        "fn_EmployeesUnderLeader": "org", "fn_EasterSunday": "wfm", "usp_HolidayCopyYear": "wfm", "usp_SystemTableStats": "adm",
        "vw_AnnouncementCompliance": "com", "TR_pa_action_attachment_rules": "pa", "TR_pay_payroll_day_rules": "fin",
        "vw_SystemSqlObject": "adm", "Employee": "hcm", "catCountry": "core",
    }
    assert {k: where.get(k) for k in expected} == expected
    # Un trigger vive en el esquema de su tabla y TODAS las referencias de vistas / SP / triggers resuelven.
    assert _rows("SELECT t.name FROM sys.triggers t JOIN sys.objects p ON p.object_id = t.parent_id "
                 "JOIN sys.objects o ON o.object_id = t.object_id WHERE o.schema_id <> p.schema_id") == []
    broken = _rows("SELECT SchemaName + N'.' + ObjectName FROM adm.vw_SystemSqlObject WHERE UnresolvedReferences > 0")
    assert broken == []
    # El propósito de cada objeto queda en SQL Server (MS_Description) y cada esquema nuevo tiene su descripción.
    missing = _rows("SELECT ObjectName FROM adm.vw_SystemSqlObject WHERE Purpose IS NULL")
    assert missing == []
    assert _rows("SELECT COUNT(*) FROM sys.extended_properties WHERE class = 3 AND name = N'MS_Description' "
                 "AND major_id IN (SCHEMA_ID(N'sec'), SCHEMA_ID(N'wfm'), SCHEMA_ID(N'com'))") == [(3,)]


def test_module_objects_keep_working_after_the_move(hr_user):
    # Funciones, vistas y SP recreados en su esquema con las referencias reescritas.
    assert _rows("SELECT wfm.fn_EasterSunday(2026)") == [(date(2026, 4, 5),)]
    assert _rows("SELECT COUNT(*) FROM org.fn_EmployeesUnderLeader(%s, %s)", [-1, date(2026, 1, 1)]) == [(0,)]
    assert len(_rows("EXEC adm.usp_SystemTableStats")) > 80
    _rows("SELECT TOP 1 * FROM fin.vw_PayPayrollDay")
    _rows("SELECT TOP 1 * FROM com.vw_AnnouncementCompliance")


def test_introspection_understands_schema_qualified_tables():
    intro = connection.introspection
    with connection.cursor() as c:
        names = intro.table_names(c)
        assert "[pa].[pa_action]" in names and "[fin].[pay_payroll_day]" in names and "django_session" in names
        constraints = intro.get_constraints(c, "[pa].[pa_action]")
        assert any(x["primary_key"] for x in constraints.values())
        assert any(x["foreign_key"] for x in constraints.values())
        assert intro.get_primary_key_column(c, "[com].[com_announcement]") == "id"
        assert {f.name for f in intro.get_table_description(c, "[sec].[accounts_customuser]")} >= {"id", "username", "locked_at"}
        assert intro.get_sequences(c, "[adm].[sys_audit_event]")[0]["column"] == "id"


def test_sql_objects_catalog_endpoint(api, admin_user, employee_user):
    api.force_login(employee_user)
    assert api.get("/api/v1/system/data/objects/").status_code == 403
    api.force_login(admin_user)
    body = api.get("/api/v1/system/data/objects/").json()
    by_name = {o["name"]: o for o in body["results"]}
    assert body["counts"]["VIEW"] >= 25 and body["counts"]["TRIGGER"] >= 26 and body["counts"]["PROCEDURE"] >= 4
    trig = by_name["com.TR_com_announcement_no_delete"]
    assert trig["status"] == "OK" and trig["timing"] == "INSTEAD OF" and "DELETE" in trig["events"]
    assert trig["parent"] == "com.com_announcement" and trig["purpose"]
    assert by_name["fin.vw_PayPayrollDay"]["module"] == "Planillas" and body["problems"] == 0
    assert {s["schema"] for s in body["schemas"]} >= {"sec", "adm", "hcm", "org", "wfm", "acd", "pa", "fin", "com"}
    stats = api.get("/api/v1/system/data/stats/").json()
    modules = {t["name"]: t["module"] for t in stats["tables"]}
    assert modules["wfm.sch_pay_cycle"] == "Horarios y tiempo" and modules["hcm.gid_id_type"] == "General IDs"
    assert modules["com.com_announcement"] == "Comunicados" and modules["sec.accounts_customuser"] == "Usuarios y seguridad"


# ================================================================== bloqueo de cuentas y Estado del sistema
def test_account_locks_after_failed_logins_and_admin_unlocks(api, client, make_user, employee_user):
    PlatformSettings.objects.update_or_create(pk=1, defaults={"max_failed_logins": 3})
    policy.invalidate()
    for _ in range(3):
        assert _login(api, employee_user.username, "incorrecta").status_code == 400
    employee_user.refresh_from_db()
    assert employee_user.locked_at is not None and employee_user.failed_login_count == 3
    assert "3 intentos fallidos" in employee_user.lock_reason
    assert AuditEvent.objects.filter(action="account_locked", target_id=str(employee_user.pk)).exists()
    # Bloqueada: ni con la contraseña correcta.
    assert _login(api, employee_user.username).status_code == 400

    su = make_user("root.p25", "ADMIN", is_superuser=True)
    client.force_login(su)
    page = client.get("/admin/accounts/customuser/?acceso=bloqueada")
    assert page.status_code == 200 and employee_user.username in page.content.decode()
    assert client.get(f"/admin/accounts/customuser/{employee_user.pk}/change/").status_code == 200
    r = client.post("/admin/accounts/customuser/", {"action": "unlock_accounts", "_selected_action": [employee_user.pk]})
    assert r.status_code == 302
    employee_user.refresh_from_db()
    assert employee_user.locked_at is None and employee_user.failed_login_count == 0
    assert _login(api, employee_user.username).status_code == 200
    assert client.get("/admin/accounts/customuser/add/").status_code == 403  # se crean desde la aplicación


def test_admin_form_edits_access_attributes_with_rbac_rules(client, make_user, hr_user, employee_user):
    su = make_user("root.p25b", "ADMIN", is_superuser=True)
    client.force_login(su)
    url = f"/admin/accounts/customuser/{employee_user.pk}/change/"
    data = {"first_name": "Ana", "last_name": "Pérez", "email": "", "role": "EMPLOYEE", "is_active": "on",
            "must_change_password": "on", "locked": "on", "lock_reason": ""}
    r = client.post(url, data)
    assert r.status_code == 200 and "Indique el motivo del bloqueo" in r.content.decode()
    data["lock_reason"] = "Investigación de seguridad"
    assert client.post(url, data).status_code == 302
    employee_user.refresh_from_db()
    assert employee_user.must_change_password and employee_user.locked_at and employee_user.lock_reason == "Investigación de seguridad"
    assert AuditEvent.objects.filter(action="user_updated_admin", target_id=str(employee_user.pk)).exists()
    # RRHH (staff no) no entra al panel; un Administrador no superusuario no edita a un superusuario.
    admin = make_user("admin.p25", "ADMIN")
    client.force_login(admin)
    assert client.post(f"/admin/accounts/customuser/{su.pk}/change/", {**data, "role": "ADMIN"}).status_code == 403
    # Nunca sobre la propia cuenta: no se puede desactivar.
    own = {"first_name": "", "last_name": "", "email": "", "role": "ADMIN", "must_change_password": "", "lock_reason": ""}
    r = client.post(f"/admin/accounts/customuser/{admin.pk}/change/", own)
    assert r.status_code == 200 and "No puede desactivar su propia cuenta" in r.content.decode()


def test_system_overview_counts_users_and_live_sessions(api, admin_user, employee_user, hr_user):
    from rest_framework.test import APIClient

    assert _login(APIClient(), employee_user.username).status_code == 200
    other = UserSession.objects.get(user=employee_user, ended_at__isnull=True)
    CustomUser.objects.filter(pk=hr_user.pk).update(must_change_password=True)
    api.force_login(admin_user)
    body = api.get("/api/v1/system/overview/").json()
    assert body["users"]["total"] == CustomUser.objects.count()
    assert body["users"]["must_change_password"] >= 1 and body["users"]["locked"] == 0
    assert body["sessions"]["active"] >= 1 and any(r["username"] == employee_user.username for r in body["sessions"]["rows"])
    assert body["policy"]["max_failed_logins"] == 5 and {"users", "sessions"} <= set(body["admin_urls"])
    r = api.post(f"/api/v1/system/sessions/{other.pk}/close/")
    assert r.status_code == 200
    other.refresh_from_db()
    assert other.ended_at is not None and other.end_reason == "ADMIN"
    api.force_login(employee_user)
    assert api.get("/api/v1/system/overview/").status_code == 403


# ================================================================== periódico virtual y acuse de recibo
def _publish(api, **extra):
    payload = {"title": "Nueva política de contraseñas", "body": "Desde el lunes las contraseñas se renuevan cada 90 días.\n\n- Mínimo 12 caracteres",
               "category": "SECURITY", "publish": True, **extra}
    r = api.post(f"{N}/", payload, format="json")
    assert r.status_code == 201, r.json()
    return r.json()["announcement"]


def test_critical_announcement_requires_ack_and_reports_compliance(api, hr_user, employee_user, wfm_user):
    api.force_login(employee_user)
    assert api.post(f"{N}/", {"title": "x"}, format="json").status_code == 403
    api.force_login(hr_user)
    a = _publish(api, requires_ack=False)
    assert a["requires_ack"] and a["critical"] and a["status"] == "PUBLISHED" and len(a["content_hash"]) == 64
    assert a["ack_due_date"] == (timezone.localdate() + timedelta(days=comms.DEFAULT_ACK_DAYS)).isoformat()
    news = _publish(api, title="Bienvenidos al periódico", category="NEWS", body="Comunicados de la empresa en un solo lugar.")
    assert not news["requires_ack"]

    api.force_login(employee_user)
    feed = api.get(f"{N}/").json()
    assert feed["pending_count"] == 1 and not feed["can_manage"]
    assert {x["id"] for x in api.get(f"{N}/?pending=1").json()["results"]} == {a["id"]}
    assert api.get(f"{N}/pending/").json()["count"] == 1
    notes = api.get("/api/v1/system/notifications/").json()["results"]
    assert any(n["key"] == f"com:{a['id']}" for n in notes)
    assert api.post(f"{N}/{a['id']}/ack/", {}, format="json").status_code == 400  # debe confirmar que lo leyó
    r = api.post(f"{N}/{a['id']}/ack/", {"confirm": True}, format="json")
    assert r.status_code == 200 and r.json()["announcement"]["my_ack"]["sha256"] == a["content_hash"]
    assert api.post(f"{N}/{a['id']}/ack/", {"confirm": True}, format="json").status_code == 200  # idempotente
    assert AnnouncementAck.objects.filter(announcement_id=a["id"]).count() == 1
    assert api.get(f"{N}/pending/").json()["count"] == 0
    assert api.get(f"{N}/{a['id']}/compliance/").status_code == 403

    api.force_login(hr_user)
    rep = api.get(f"{N}/{a['id']}/compliance/").json()
    audience = CustomUser.objects.filter(is_active=True).count()
    assert rep["audience"] == audience and rep["acknowledged"] == 1 and rep["pending"] == audience - 1
    statuses = {r["username"]: r["status"] for r in rep["rows"]}
    assert statuses[employee_user.username] == "ACKNOWLEDGED" and statuses[wfm_user.username] == "PENDING"
    csv = api.get(f"{N}/{a['id']}/compliance/?export=csv")
    assert csv.status_code == 200 and employee_user.username in csv.content.decode("utf-8-sig")
    # SQL Server: la vista y el SP dan el mismo cumplimiento que la aplicación.
    view = _rows("SELECT Audience, Acknowledged, Pending FROM com.vw_AnnouncementCompliance WHERE AnnouncementId = %s", [a["id"]])
    assert view == [(audience, 1, audience - 1)]
    sp = {r[0]: r[6] for r in _rows("EXEC com.usp_AnnouncementComplianceReport @AnnouncementId = %s", [a["id"]])}
    assert sp[employee_user.username] == "ACKNOWLEDGED" and sp[wfm_user.username] == "PENDING"
    summary = api.get(f"{N}/compliance/").json()["results"]
    assert [x["id"] for x in summary] == [a["id"]]
    # Reporte automático: foto diaria + foto al vencer el plazo (una sola vez).
    out = comms.run_daily(timezone.localdate())
    assert [x["trigger"] for x in out] == ["DAILY"]
    assert comms.run_daily(timezone.localdate()) == []
    out = comms.run_daily(timezone.localdate() + timedelta(days=comms.DEFAULT_ACK_DAYS + 1))
    assert sorted(x["trigger"] for x in out) == ["DAILY", "DEADLINE"]
    deadline = ComplianceSnapshot.objects.get(announcement_id=a["id"], trigger="DEADLINE")
    assert deadline.overdue == audience - 1 and wfm_user.username in deadline.pending_users


def test_announcement_content_is_frozen_and_sql_rules(api, hr_user, employee_user):
    api.force_login(hr_user)
    a = _publish(api, category="ORG_CHANGE", title="Nueva estructura de operaciones", audience_roles=["EMPLOYEE"])
    r = api.patch(f"{N}/{a['id']}/", {"body": "Otro texto distinto del publicado."}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "frozen"
    r = api.patch(f"{N}/{a['id']}/", {"pinned": True, "ack_due_date": (timezone.localdate() + timedelta(days=20)).isoformat()}, format="json")
    assert r.status_code == 200 and r.json()["announcement"]["pinned"]
    # Audiencia por rol: RRHH no está obligado (no le aparece como pendiente).
    assert api.get(f"{N}/pending/").json()["count"] == 0
    api.force_login(employee_user)
    assert api.post(f"{N}/{a['id']}/ack/", {"confirm": True}, format="json").status_code == 200
    # Archivar guarda la foto final y lo saca de la portada; un formulario exige su enlace.
    api.force_login(hr_user)
    assert api.post(f"{N}/{a['id']}/archive/").status_code == 200
    assert ComplianceSnapshot.objects.filter(announcement_id=a["id"], trigger="ARCHIVE").exists()
    api.force_login(employee_user)
    assert a["id"] not in {x["id"] for x in api.get(f"{N}/").json()["results"]}
    api.force_login(hr_user)
    r = api.post(f"{N}/", {"title": "Encuesta de clima", "body": "Responda la encuesta anual.", "category": "FORM"}, format="json")
    assert r.status_code == 400 and "link_url" in r.json()["errors"]
    r = api.post(f"{N}/", {"title": "Encuesta de clima", "body": "Responda la encuesta anual.", "category": "FORM",
                           "link_url": "javascript:alert(1)"}, format="json")
    assert r.status_code == 400
    draft = Announcement.objects.create(title="Borrador", body="Contenido del borrador.", category="NEWS", created_by=hr_user)
    assert api.delete(f"{N}/{draft.pk}/").status_code == 204


COM_RULES = {
    "50122": "UPDATE com.com_announcement SET body = N'cambio' WHERE id = %(a)s",
    "50123": "DELETE FROM com.com_announcement WHERE id = %(a)s",
    "50120": "DELETE FROM com.com_announcement_ack WHERE announcement_id = %(a)s",
    "50121": ("INSERT INTO com.com_announcement_ack (announcement_id, user_id, username, acknowledged_at, content_hash, user_agent) "
              "VALUES (%(draft)s, %(user)s, N'x', SYSDATETIME(), N'x', N'')"),
    "50124": "UPDATE com.com_compliance_snapshot SET pending = 0 WHERE announcement_id = %(a)s",
}


@pytest.mark.parametrize("code", list(COM_RULES))
def test_announcement_sql_rules(api, hr_user, employee_user, code):
    api.force_login(hr_user)
    a = _publish(api)
    comms.acknowledge(Announcement.objects.get(pk=a["id"]), user=employee_user)
    comms.take_snapshot(Announcement.objects.get(pk=a["id"]), "MANUAL")
    draft = Announcement.objects.create(title="Borrador", body="Contenido del borrador.", category="NEWS", created_by=hr_user)
    sql = COM_RULES[code] % {"a": a["id"], "draft": draft.pk, "user": employee_user.pk}
    with pytest.raises(DatabaseError) as exc, transaction.atomic(), connection.cursor() as c:
        c.execute(sql)
    assert code in str(exc.value)


# ================================================================== boleta desglosada por día
def test_allocate_is_exact_to_the_cent():
    parts = engine.allocate(Decimal("100.00"), {1: 1, 2: 1, 3: 1})
    assert sum(parts.values()) == Decimal("100.00") and sorted(parts.values()) == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]
    neg = engine.allocate(Decimal("-10.01"), {"a": 2, "b": 1, "c": 0})
    assert sum(neg.values()) == Decimal("-10.01") and neg["c"] == 0
    assert engine.allocate(Decimal("5"), {"a": 0}) == {"a": Decimal("0")}


def test_daily_payslip_translates_each_cutoff_day_to_money(make_employee):
    period = PayPeriod.objects.get(cycle__code="SV_QUINCENAL", code="2026-10-Q1")
    emp = make_employee("SV", hire_date=date(2026, 9, 1), base_salary=880, pay_frequency="BIWEEKLY")
    ScheduleAssignment.objects.create(employee=emp, definition=DAY, effective_start_date=date(2026, 9, 1))
    worked = (date(2026, 9, 25), date(2026, 9, 28), date(2026, 9, 29), date(2026, 10, 9))
    for d in worked:
        start, end = datetime(d.year, d.month, d.day, 8), datetime(d.year, d.month, d.day, 12)
        rec = TimeRecord.objects.create(employee=emp, kind="INTERVAL", start_at=start, end_at=end, occurrence_date=d, minutes=240,
                                        source="WEB_TIMER")
        TimeRecordDay.objects.create(record=rec, employee=emp, occurrence_date=d, start_at=start, end_at=end, minutes=240)
    run = services.calculate(period)
    b = services.employee_breakdown(run, emp.employee_code)
    days = list(PayrollDay.objects.filter(employee=emp).order_by("work_date"))
    # Una fila por cada fecha del corte interno 25/09–09/10 (15 días), no de la quincena 1–15.
    assert [d.work_date for d in days] == [date(2026, 9, 25) + timedelta(days=i) for i in range(15)]
    assert {d.cutoff_code for d in days} == {"C-2026-10-Q1"}
    by_date = {d.work_date: d for d in days}
    assert by_date[date(2026, 9, 26)].day_type == "REST" and by_date[date(2026, 9, 26)].total_amount == 0
    assert by_date[date(2026, 9, 25)].day_type == "PARTIAL" and by_date[date(2026, 9, 25)].paid_seconds == 4 * 3600
    assert by_date[date(2026, 9, 30)].day_type == "UNPAID" and by_date[date(2026, 9, 30)].scheduled_seconds == 8 * 3600
    lines = {ln["code"]: ln for ln in b["lines"]}
    salary = Decimal(str(lines["SALARIO"]["amount"]))
    assert sum(d.total_amount for d in days) == salary
    assert all(d.regular_amount == (salary / 4).quantize(Decimal("0.01")) or d.regular_amount for d in days if d.work_date in worked)
    daily = b["daily"]
    assert daily["reconciled"] and daily["daily_total"] == services.money(salary)
    assert daily["cutoffs"][0]["code"] == "C-2026-10-Q1" and len(daily["cutoffs"][0]["days"]) == 15
    assert daily["hourly_rate"] == str(lines["SALARIO"]["rate"])
    # Recalcular reemplaza los días; con la planilla cerrada SQL Server los bloquea (50099).
    services.calculate(period)
    assert PayrollDay.objects.filter(employee=emp).count() == 15
    view = _rows("SELECT COUNT(*), SUM(TotalAmount) FROM fin.vw_PayPayrollDay WHERE PayrollCode = %s", [run.payroll.payroll_code])
    assert view == [(15, salary)]
    _rows("UPDATE fin.Payroll SET PayrollStatus = N'APPROVED', ApprovedAt = SYSDATETIME(), ApprovedBy = N'test' WHERE PayrollId = %s",
          [run.payroll_id])
    with pytest.raises(DatabaseError) as exc, transaction.atomic(), connection.cursor() as c:
        c.execute("UPDATE fin.pay_payroll_day SET notes = N'x' WHERE payroll_id = %s", [run.payroll_id])
    assert "50099" in str(exc.value)


def test_cutoff_entirely_before_hire_shows_days_outside_the_employment(make_employee):
    """Ingreso 10/10 en la quincena 2026-10-Q1 (corte interno 25/09–09/10): ningún día del corte es laborable."""
    period = PayPeriod.objects.get(cycle__code="SV_QUINCENAL", code="2026-10-Q1")
    emp = make_employee("SV", hire_date=date(2026, 10, 10), base_salary=880, pay_frequency="BIWEEKLY")
    ScheduleAssignment.objects.create(employee=emp, definition=DAY, effective_start_date=date(2026, 10, 10))
    services.calculate(period)
    days = list(PayrollDay.objects.filter(employee=emp))
    assert len(days) == 15 and {d.day_type for d in days} == {"OUTSIDE"} and sum(d.total_amount for d in days) == 0


def test_portal_shows_daily_breakdown_to_the_employee(api, make_employee, make_user):
    period = PayPeriod.objects.get(cycle__code="SV_QUINCENAL", code="2026-10-Q1")
    emp = make_employee("SV", hire_date=date(2026, 9, 1), base_salary=880, pay_frequency="BIWEEKLY")
    ScheduleAssignment.objects.create(employee=emp, definition=DAY, effective_start_date=date(2026, 9, 1))
    user = make_user("agente.p25", "EMPLOYEE", employee=emp)
    run = services.calculate(period)
    assert run.preliminary_published_at is not None
    api.force_login(user)
    body = api.get("/api/v1/payroll/me/payslips/").json()
    slip = body["preliminary"][0]
    assert slip["daily"]["cutoffs"][0]["start"] == "2026-09-25" and slip["daily"]["cutoffs"][0]["end"] == "2026-10-09"
    assert all(d["day_type"] in ("UNPAID", "REST") for d in slip["daily"]["cutoffs"][0]["days"])
