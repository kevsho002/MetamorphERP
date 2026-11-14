from unittest import mock

import pytest
from django.db import OperationalError

from apps.health.views import expected_tables


def test_liveness(api):
    r = api.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_expected_tables_cover_sql_first_and_django():
    tables = expected_tables()
    assert "hcm.Employee" in tables
    assert "core.catCostCenter" in tables
    assert "sec.accounts_customuser" in tables
    assert "dbo.django_session" in tables
    # Fase 25: en dbo solo quedan las tablas internas del framework de Django; el ERP vive en esquemas por módulo.
    assert all(t.split(".", 1)[1].startswith(("auth_", "django_")) for t in tables if t.startswith("dbo."))
    assert {"wfm.sch_pay_cycle", "fin.pay_payroll_line", "pa.pa_action", "com.com_announcement", "adm.sys_audit_event"} <= set(tables)
    assert "wfm.Attendance" not in tables  # el mock de asistencias retirado en la Fase 22


@pytest.mark.django_db
def test_db_health_returns_503_when_database_is_unreachable(api, admin_user):
    with mock.patch("apps.health.views.connection.cursor", side_effect=OperationalError("Login timeout expired")):
        r = api.get("/api/v1/health/db")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "error"
    assert "Login timeout" not in body["error"]  # Fase 26: el público no ve el detalle del driver
    api.force_authenticate(admin_user)  # sin sesión en BD: la BD está caída
    with mock.patch("apps.health.views.connection.cursor", side_effect=OperationalError("Login timeout expired")):
        r = api.get("/api/v1/health/db")
    assert "Login timeout expired" in r.json()["error"]


@pytest.mark.django_db
def test_db_health_ok_against_test_database(api, admin_user, employee_user):
    r = api.get("/api/v1/health/db")
    body = r.json()
    assert r.status_code == 200, body
    assert body["status"] == "ok" and body["missing_count"] == 0
    assert "database" not in body and "server_version" not in body  # Fase 26: sin metadatos técnicos para el público
    api.force_login(employee_user)
    assert "database" not in api.get("/api/v1/health/db").json()
    api.force_login(admin_user)
    body = api.get("/api/v1/health/db").json()
    assert body["missing_tables"] == []
    assert body["database"].startswith("test_")


def test_unknown_api_path_is_json_404_not_spa(api):
    r = api.get("/api/v1/no-existe")
    assert r.status_code == 404
    assert r["Content-Type"].startswith("application/json")
