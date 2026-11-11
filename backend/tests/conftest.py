"""Fixtures comunes.

La BD de pruebas (test_MetamorphERP) la crea pytest-django. Antes de aplicar las
migraciones de Django se ejecutan los scripts SQL-first de database/scripts, de
modo que el esquema de dominio de los tests es EXACTAMENTE el de producción.
"""

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.cache import cache
from django.db import connections
from django.db.models.signals import pre_migrate
from django.dispatch import receiver
from rest_framework.test import APIClient

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "database" / "scripts"
_GO = re.compile(r"^\s*GO\s*$", re.IGNORECASE | re.MULTILINE)
_deployed: set[str] = set()


def deploy_sql_first_schema(alias: str = "default") -> None:
    connection = connections[alias]
    with connection.cursor() as cursor:
        for script in sorted(SCRIPTS_DIR.glob("*.sql")):
            for batch in _GO.split(script.read_text(encoding="utf-8-sig")):
                if batch.strip():
                    cursor.execute(batch)
        # Los scripts fijan opciones de SESIÓN (XACT_ABORT, NOCOUNT) pensadas para sqlcmd;
        # se restauran para que no alteren el comportamiento de Django en esta conexión.
        cursor.execute("SET XACT_ABORT OFF; SET NOCOUNT OFF;")


@receiver(pre_migrate)
def _deploy_before_migrations(sender, using, **kwargs):
    name = connections[using].settings_dict["NAME"]
    if not name.startswith("test_") or name in _deployed:
        return  # nunca toca la BD real
    deploy_sql_first_schema(using)
    _deployed.add(name)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()  # reinicia los contadores de throttling entre tests


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.fixture
def csrf_api() -> APIClient:
    """Cliente que, como un navegador, está sujeto a la verificación CSRF."""
    return APIClient(enforce_csrf_checks=True)


# ------------------------------------------------------------------ datos
@pytest.fixture
def countries(db):
    from apps.common.models import Country

    return {c.country_code: c for c in Country.objects.all()}


@pytest.fixture
def make_employee(db, countries):
    """Crea un empleado con ID corporativo generado por el SP del país."""
    from apps.hcm.models import Employee
    from apps.hcm.services.employee_code import generate_employee_code

    counter = iter(range(1, 10_000))

    def _make(country_code: str = "SV", **overrides) -> Employee:
        country = countries[country_code]
        n = next(counter)
        hire = overrides.pop("hire_date", date(2026, 3, 1))
        code = generate_employee_code(country.country_id, hire).code
        fields = {
            "employee_code": code,
            "country": country,
            "first_name": "Empleado",
            "last_name": f"Prueba{n}",
            "national_id_type": "DOC",
            "national_id_number": f"TEST-{country_code}-{n:06d}",
            "birth_date": date(1990, 1, 1),
            "hire_date": hire,
            "base_salary": Decimal("1000.00"),
            "work_email": f"empleado{n}@metamorph.test",
        }
        fields.update(overrides)
        return Employee.objects.create(**fields)

    return _make


@pytest.fixture
def cost_center(db):
    from apps.common.models import CostCenter

    return lambda code: CostCenter.objects.get(code=code)


STRONG_PASSWORD = "Metamorph!2026-Segura"


@pytest.fixture
def make_user(db, make_employee):
    from apps.accounts.models import CustomUser
    from apps.accounts.roles import ROLES_REQUIRING_EMPLOYEE, Role

    def _make(username: str, role: str = Role.EMPLOYEE, *, with_employee: bool | None = None, **fields):
        if with_employee is None:
            with_employee = role in ROLES_REQUIRING_EMPLOYEE
        if with_employee and "employee" not in fields:
            fields["employee"] = make_employee()
        user = CustomUser(username=username, role=role, **fields)
        user.set_password(STRONG_PASSWORD)
        user.save()
        return user

    return _make


@pytest.fixture
def admin_user(make_user):
    return make_user("admin.test", "ADMIN")


@pytest.fixture
def hr_user(make_user):
    return make_user("rrhh.test", "HR")


@pytest.fixture
def wfm_user(make_user):
    return make_user("wfm.test", "WFM")


@pytest.fixture
def employee_user(make_user):
    return make_user("empleado.test", "EMPLOYEE")


@pytest.fixture
def as_user(api):
    def _login(user) -> APIClient:
        api.force_login(user)
        return api

    return _login
