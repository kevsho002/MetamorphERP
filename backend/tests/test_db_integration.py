"""Integración contra SQL Server (BD test_MetamorphERP creada desde database/scripts).

Garantiza que los modelos Django y el DDL SQL-first no diverjan.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.apps import apps
from django.db import IntegrityError, connection, transaction

from apps.common.fields import split_sql_table
from apps.hcm.models import DigitalFile, Employee
from apps.hcm.services.employee_code import compute_check_digit, generate_employee_code, is_valid_employee_code

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

MODELS = sorted(
    (m for m in apps.get_models() if m._meta.app_label in {"common", "hcm", "payroll", "accounts"}),
    key=lambda m: m._meta.db_table,
)


@pytest.mark.parametrize("model", MODELS, ids=lambda m: "%s.%s" % split_sql_table(m._meta.db_table))
def test_model_matches_database(model):
    schema, table = split_sql_table(model._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT COLUMN_NAME, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
            [schema, table],
        )
        db_columns = {name: nullable == "YES" for name, nullable in cursor.fetchall()}

    model_columns = {}
    for field in model._meta.concrete_fields:
        nullable = field.null or (field.generated and field.output_field.null)
        model_columns[field.column] = nullable

    assert db_columns, f"La tabla {schema}.{table} no existe"
    assert set(model_columns) == set(db_columns), f"Columnas distintas en {schema}.{table}"
    for column, nullable in model_columns.items():
        assert nullable == db_columns[column], f"{schema}.{table}.{column}: nulabilidad distinta"


def test_sql_and_python_check_digit_agree():
    with connection.cursor() as cursor:
        for payload in ["SV2026000001", "GT2026123456", "MX1999999999", "CO2030000042", "ABC0", "7992739871"]:
            cursor.execute("SELECT core.fn_ComputeCheckDigit(%s)", [payload])
            assert cursor.fetchone()[0] == compute_check_digit(payload), payload


def test_generate_code_requires_transaction(countries):
    # Fuera de atomic() el correlativo podría confirmarse sin el empleado: se rechaza.
    with mock_no_atomic():
        with pytest.raises(RuntimeError):
            generate_employee_code(countries["SV"].country_id)


class mock_no_atomic:
    def __enter__(self):
        self._prev = connection.in_atomic_block
        connection.in_atomic_block = False

    def __exit__(self, *exc):
        connection.in_atomic_block = self._prev


def test_create_employee_with_generated_code_and_digital_file(countries):
    """Flujo ACID: código + empleado + expediente en una transacción (pytest la revierte)."""
    sv = countries["SV"]
    generated = generate_employee_code(sv.country_id, date(2026, 2, 1))
    assert is_valid_employee_code(generated.code)
    assert generated.code.startswith("SV-2026-")

    employee = Employee.objects.create(
        employee_code=generated.code,
        country=sv,
        first_name="Ana",
        last_name="Pérez",
        national_id_type="DUI",
        national_id_number="TEST-00000000-0",
        birth_date=date(1995, 4, 12),
        hire_date=date(2026, 2, 1),
        base_salary=Decimal("950.00"),
    )
    assert employee.employee_id is not None
    assert employee.created_by  # DEFAULT SUSER_SNAME() aplicado por SQL Server y leído vía OUTPUT
    employee.refresh_from_db(fields=["row_ver"])
    assert employee.row_ver  # ROWVERSION asignado por SQL Server
    assert employee.employment_status == "ACTIVE"

    digital_file = DigitalFile.objects.create(employee=employee)
    assert digital_file.file_status == "OPEN"

    # ROWVERSION cambia en cada UPDATE y Django nunca intenta escribirla
    old_version = employee.row_ver
    employee.phone_number = "+503 2222-0000"
    employee.save()
    employee.refresh_from_db(fields=["row_ver"])
    assert employee.row_ver != old_version


def test_user_employee_fk_is_enforced_by_database(admin_user):
    with pytest.raises(IntegrityError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE sec.accounts_customuser SET employee_code = %s WHERE id = %s",
                ["SV-2099-999999-0", admin_user.pk],
            )


def test_user_cost_center_fk_is_enforced_by_database(admin_user):
    with pytest.raises(IntegrityError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("UPDATE sec.accounts_customuser SET cost_center_id = -1 WHERE id = %s", [admin_user.pk])


def test_cost_centers_seeded_per_country(cost_center, countries):
    for code in countries:
        assert cost_center(f"{code}-RRHH").country_id == countries[code].country_id
