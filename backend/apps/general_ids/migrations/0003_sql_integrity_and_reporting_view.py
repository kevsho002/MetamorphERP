"""General IDs: integridad en SQL Server + vista para cruces (JOINs) en reportes.

* FK_gid_employee_general_id_Employee hacia hcm.Employee (SQL-first).
* TR_gid_employee_general_id_rules (la base de datos lo garantiza aunque se escriba directo en la tabla):
    50030 — con «valor único», un valor de un tipo no puede identificar a dos registros en fechas que se cruzan;
    50031 — sin «varios activos por empleado», un empleado no tiene dos IDs del mismo tipo vigentes a la vez.
* dbo.vw_EmployeeGeneralId: cada ID con su empleado, herramienta, cliente/marca y vigencia. Ejemplo:

      SELECT e.EmployeeCode, a.*
      FROM acd_interval_data a
      JOIN dbo.vw_EmployeeGeneralId g
        ON g.IdTypeCode = 'ACD_ID' AND g.IdValue = a.agent_id
       AND a.call_date BETWEEN g.EffectiveStart AND ISNULL(g.EffectiveEnd, '9999-12-31');
"""

from django.db import migrations

_REQUIRE = """
IF OBJECT_ID(N'hcm.Employee', N'U') IS NULL OR OBJECT_ID(N'core.catCountry', N'U') IS NULL
    THROW 50010, N'Faltan objetos SQL-first (hcm.Employee / core.catCountry). Ejecute database/deploy.ps1 antes de migrate.', 1;
"""

FORWARD = [
    _REQUIRE,
    """
IF OBJECT_ID(N'dbo.FK_gid_employee_general_id_Employee', N'F') IS NULL
    ALTER TABLE dbo.gid_employee_general_id WITH CHECK
        ADD CONSTRAINT FK_gid_employee_general_id_Employee FOREIGN KEY (employee_id) REFERENCES hcm.Employee (EmployeeId);
IF OBJECT_ID(N'dbo.ck_gid_code_format', N'C') IS NULL
    ALTER TABLE dbo.gid_id_type WITH CHECK ADD CONSTRAINT ck_gid_code_format
        CHECK (code COLLATE Latin1_General_BIN LIKE N'[A-Z]%' AND code COLLATE Latin1_General_BIN NOT LIKE N'%[^A-Z0-9_]%');
IF OBJECT_ID(N'dbo.ck_gid_value_not_blank', N'C') IS NULL
    ALTER TABLE dbo.gid_employee_general_id WITH CHECK ADD CONSTRAINT ck_gid_value_not_blank CHECK (LEN(LTRIM(RTRIM(value))) > 0);
""",
    """
CREATE OR ALTER TRIGGER dbo.TR_gid_employee_general_id_rules
ON dbo.gid_employee_general_id
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.gid_id_type AS t ON t.id = i.id_type_id AND t.unique_value = 1
        JOIN dbo.gid_employee_general_id AS g
          ON g.id_type_id = i.id_type_id
         AND g.value = i.value
         AND g.id <> i.id
         AND g.effective_start <= ISNULL(i.effective_end, '9999-12-31')
         AND i.effective_start <= ISNULL(g.effective_end, '9999-12-31')
    )
        THROW 50030, N'General ID: ese valor ya identifica a otro registro del mismo tipo en fechas que se cruzan.', 1;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.gid_id_type AS t ON t.id = i.id_type_id AND t.allow_multiple_active = 0
        JOIN dbo.gid_employee_general_id AS g
          ON g.employee_id = i.employee_id
         AND g.id_type_id = i.id_type_id
         AND g.id <> i.id
         AND g.effective_start <= ISNULL(i.effective_end, '9999-12-31')
         AND i.effective_start <= ISNULL(g.effective_end, '9999-12-31')
    )
        THROW 50031, N'General ID: el empleado ya tiene un ID de ese tipo vigente en esas fechas y el tipo no admite varios.', 1;
END
""",
    """
CREATE OR ALTER VIEW dbo.vw_EmployeeGeneralId
AS
SELECT
    g.id                    AS GeneralIdId,
    e.EmployeeId            AS EmployeeId,
    e.EmployeeCode          AS EmployeeCode,
    CONCAT_WS(N' ', e.FirstName, e.MiddleName, e.LastName, e.SecondLastName) AS FullName,
    c.CountryCode           AS CountryCode,
    e.EmploymentStatus      AS EmploymentStatus,
    t.code                  AS IdTypeCode,
    t.name                  AS IdTypeName,
    s.code                  AS ToolCode,
    s.name                  AS ToolName,
    s.category              AS ToolCategory,
    g.value                 AS IdValue,
    cl.code                 AS ClientCode,
    cl.name                 AS ClientName,
    b.code                  AS BrandCode,
    b.name                  AS BrandName,
    g.effective_start       AS EffectiveStart,
    g.effective_end         AS EffectiveEnd,
    CAST(CASE WHEN g.effective_end IS NULL THEN 1 ELSE 0 END AS BIT) AS IsNow
FROM dbo.gid_employee_general_id AS g
JOIN dbo.gid_id_type AS t ON t.id = g.id_type_id
JOIN dbo.gid_source_tool AS s ON s.id = t.tool_id
JOIN hcm.Employee AS e ON e.EmployeeId = g.employee_id
JOIN core.catCountry AS c ON c.CountryId = e.CountryId
LEFT JOIN dbo.ops_client AS cl ON cl.id = g.client_id
LEFT JOIN dbo.ops_brand AS b ON b.id = g.brand_id;
""",
]

REVERSE = [
    "IF OBJECT_ID(N'dbo.vw_EmployeeGeneralId', N'V') IS NOT NULL DROP VIEW dbo.vw_EmployeeGeneralId;",
    "IF OBJECT_ID(N'dbo.TR_gid_employee_general_id_rules', N'TR') IS NOT NULL DROP TRIGGER dbo.TR_gid_employee_general_id_rules;",
    """
IF OBJECT_ID(N'dbo.ck_gid_value_not_blank', N'C') IS NOT NULL
    ALTER TABLE dbo.gid_employee_general_id DROP CONSTRAINT ck_gid_value_not_blank;
IF OBJECT_ID(N'dbo.ck_gid_code_format', N'C') IS NOT NULL ALTER TABLE dbo.gid_id_type DROP CONSTRAINT ck_gid_code_format;
IF OBJECT_ID(N'dbo.FK_gid_employee_general_id_Employee', N'F') IS NOT NULL
    ALTER TABLE dbo.gid_employee_general_id DROP CONSTRAINT FK_gid_employee_general_id_Employee;
""",
]


class Migration(migrations.Migration):
    dependencies = [("general_ids", "0002_initial"), ("operations", "0002_sql_integrity_and_roster_sync")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
