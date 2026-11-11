"""FKs reales desde la tabla de usuarios (Django) hacia tablas SQL-first.

Django no genera estas FK porque los modelos destino son managed=False con
nombres de esquema calificados; se crean aquí con la convención FK_ del
proyecto. Requiere haber ejecutado database/deploy.ps1 (scripts 020 y 050).
"""

from django.db import migrations

_REQUIRE = """
IF OBJECT_ID(N'hcm.Employee', N'U') IS NULL OR OBJECT_ID(N'core.catCostCenter', N'U') IS NULL
    THROW 50010, N'Faltan tablas SQL-first (hcm.Employee / core.catCostCenter). Ejecute database/deploy.ps1 antes de migrate.', 1;
"""

FORWARD = _REQUIRE + """
IF OBJECT_ID(N'dbo.FK_accounts_customuser_Employee', N'F') IS NULL
    ALTER TABLE dbo.accounts_customuser WITH CHECK
        ADD CONSTRAINT FK_accounts_customuser_Employee
        FOREIGN KEY (employee_code) REFERENCES hcm.Employee (EmployeeCode);

IF OBJECT_ID(N'dbo.FK_accounts_customuser_CostCenter', N'F') IS NULL
    ALTER TABLE dbo.accounts_customuser WITH CHECK
        ADD CONSTRAINT FK_accounts_customuser_CostCenter
        FOREIGN KEY (cost_center_id) REFERENCES core.catCostCenter (CostCenterId);
"""

REVERSE = """
IF OBJECT_ID(N'dbo.FK_accounts_customuser_CostCenter', N'F') IS NOT NULL
    ALTER TABLE dbo.accounts_customuser DROP CONSTRAINT FK_accounts_customuser_CostCenter;
IF OBJECT_ID(N'dbo.FK_accounts_customuser_Employee', N'F') IS NOT NULL
    ALTER TABLE dbo.accounts_customuser DROP CONSTRAINT FK_accounts_customuser_Employee;
"""


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
