"""FKs reales hacia tablas SQL-first (core.catCountry, hcm.Employee) + CHECK del código de atributo.

Requiere haber ejecutado database/deploy.ps1 (scripts 001, 020 y 060).
"""

from django.db import migrations

_REQUIRE = """
IF OBJECT_ID(N'hcm.Employee', N'U') IS NULL OR OBJECT_ID(N'core.catCountry', N'U') IS NULL
   OR COL_LENGTH(N'hcm.Employee', N'CostCenterId') IS NULL
    THROW 50010, N'Faltan objetos SQL-first (hcm.Employee / core.catCountry / script 060). Ejecute database/deploy.ps1 antes de migrate.', 1;
"""

_FKS = [
    ("hcm_employee_template", "FK_hcm_employee_template_Country", "country_id", "core.catCountry (CountryId)"),
    ("hcm_employee_attribute_value", "FK_hcm_employee_attribute_value_Employee", "employee_id", "hcm.Employee (EmployeeId)"),
    ("hcm_import_batch_row", "FK_hcm_import_batch_row_Country", "country_id", "core.catCountry (CountryId)"),
    ("hcm_import_batch_row", "FK_hcm_import_batch_row_Employee", "employee_id", "hcm.Employee (EmployeeId)"),
]

FORWARD = _REQUIRE + "".join(
    f"""
IF OBJECT_ID(N'dbo.{name}', N'F') IS NULL
    ALTER TABLE dbo.{table} WITH CHECK ADD CONSTRAINT {name} FOREIGN KEY ({column}) REFERENCES {target};
"""
    for table, name, column, target in _FKS
) + """
IF OBJECT_ID(N'dbo.ck_attribute_definition_code', N'C') IS NULL
    ALTER TABLE dbo.hcm_attribute_definition WITH CHECK ADD CONSTRAINT ck_attribute_definition_code
        CHECK (code COLLATE Latin1_General_BIN LIKE N'[a-z]%'
               AND code COLLATE Latin1_General_BIN NOT LIKE N'%[^a-z0-9_]%');
"""

REVERSE = """
IF OBJECT_ID(N'dbo.ck_attribute_definition_code', N'C') IS NOT NULL
    ALTER TABLE dbo.hcm_attribute_definition DROP CONSTRAINT ck_attribute_definition_code;
""" + "".join(
    f"""
IF OBJECT_ID(N'dbo.{name}', N'F') IS NOT NULL
    ALTER TABLE dbo.{table} DROP CONSTRAINT {name};
"""
    for table, name, _, _ in reversed(_FKS)
)


class Migration(migrations.Migration):
    dependencies = [("employees", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
