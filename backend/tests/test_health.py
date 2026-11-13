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
    assert "dbo.accounts_customuser" in tables
    assert "dbo.django_session" in tables
    # 19 de la Fase 1 + catCostCenter − las 8 tablas wfm.* del mock de asistencias (retiradas en la Fase 22)
    assert len([t for t in tables if not t.startswith("dbo.")]) == 12
    assert not any(t.startswith("wfm.") for t in tables)


def test_db_health_returns_503_when_database_is_unreachable(api):
    with mock.patch("apps.health.views.connection.cursor", side_effect=OperationalError("Login timeout expired")):
        r = api.get("/api/v1/health/db")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "error"
    assert "Login timeout expired" in body["error"]


@pytest.mark.django_db
def test_db_health_ok_against_test_database(api):
    r = api.get("/api/v1/health/db")
    body = r.json()
    assert r.status_code == 200, body
    assert body["status"] == "ok"
    assert body["missing_tables"] == []
    assert body["database"].startswith("test_")


def test_unknown_api_path_is_json_404_not_spa(api):
    r = api.get("/api/v1/no-existe")
    assert r.status_code == 404
    assert r["Content-Type"].startswith("application/json")
