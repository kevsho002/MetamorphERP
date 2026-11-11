"""Integridad del roster en SQL Server + vista de reportes.

* FKs reales hacia tablas SQL-first: hcm.Employee y core.catCountry.
* UIX_roster_assignment_now: un solo intervalo abierto («Now») por empleado y atributo.
* TR_roster_assignment_no_overlap: la base rechaza intervalos superpuestos (filas no reemplazadas),
  aunque una aplicación externa escriba directo en la tabla. Los reportes de WFM, RRHH y QA
  pueden asumir que en cada fecha hay a lo sumo un valor por atributo.
* dbo.vw_RosterAssignment: intervalos vigentes con el ID corporativo y las descripciones
  (para Power BI / consultas SQL sin pasar por la API).
"""

from django.db import migrations

_REQUIRE = """
IF OBJECT_ID(N'hcm.Employee', N'U') IS NULL OR OBJECT_ID(N'core.catCountry', N'U') IS NULL
    THROW 50010, N'Faltan objetos SQL-first (hcm.Employee / core.catCountry). Ejecute database/deploy.ps1 antes de migrate.', 1;
"""

FORWARD = [
    _REQUIRE,
    """
IF OBJECT_ID(N'dbo.FK_roster_assignment_Employee', N'F') IS NULL
    ALTER TABLE dbo.roster_assignment WITH CHECK
        ADD CONSTRAINT FK_roster_assignment_Employee FOREIGN KEY (employee_id) REFERENCES hcm.Employee (EmployeeId);
IF OBJECT_ID(N'dbo.FK_roster_dimension_item_Country', N'F') IS NULL
    ALTER TABLE dbo.roster_dimension_item WITH CHECK
        ADD CONSTRAINT FK_roster_dimension_item_Country FOREIGN KEY (country_id) REFERENCES core.catCountry (CountryId);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'UIX_roster_assignment_now' AND object_id = OBJECT_ID(N'dbo.roster_assignment'))
    CREATE UNIQUE NONCLUSTERED INDEX UIX_roster_assignment_now
        ON dbo.roster_assignment (employee_id, attribute_id)
        WHERE effective_end IS NULL AND superseded_at IS NULL;
""",
    """
CREATE OR ALTER TRIGGER dbo.TR_roster_assignment_no_overlap
ON dbo.roster_assignment
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.roster_assignment AS a
          ON a.employee_id = i.employee_id
         AND a.attribute_id = i.attribute_id
         AND a.id <> i.id
         AND a.superseded_at IS NULL
         AND a.effective_start <= ISNULL(i.effective_end, '9999-12-31')
         AND i.effective_start <= ISNULL(a.effective_end, '9999-12-31')
        WHERE i.superseded_at IS NULL
    )
        THROW 50020, N'Roster: el empleado ya tiene un valor de ese atributo en parte del rango de fechas (intervalos superpuestos).', 1;
END
""",
    """
CREATE OR ALTER VIEW dbo.vw_RosterAssignment
AS
SELECT
    e.EmployeeCode          AS EmployeeCode,
    c.CountryCode           AS CountryCode,
    a.code                  AS AttributeCode,
    a.name                  AS AttributeName,
    a.[group]               AS AttributeGroup,
    r.value                 AS Value,
    COALESCE(i.name, r.value) AS ValueLabel,
    p.code                  AS ParentValue,
    r.effective_start       AS EffectiveStart,
    r.effective_end         AS EffectiveEnd,
    CAST(CASE WHEN r.effective_end IS NULL THEN 1 ELSE 0 END AS BIT) AS IsNow,
    r.recorded_at           AS RecordedAt,
    r.recorded_by           AS RecordedBy
FROM dbo.roster_assignment AS r
JOIN dbo.roster_attribute AS a ON a.id = r.attribute_id
JOIN hcm.Employee AS e ON e.EmployeeId = r.employee_id
JOIN core.catCountry AS c ON c.CountryId = e.CountryId
LEFT JOIN dbo.roster_dimension_item AS i ON i.id = r.item_id
LEFT JOIN dbo.roster_dimension_item AS p ON p.id = i.parent_id
WHERE r.superseded_at IS NULL;
""",
]

REVERSE = [
    "IF OBJECT_ID(N'dbo.vw_RosterAssignment', N'V') IS NOT NULL DROP VIEW dbo.vw_RosterAssignment;",
    "IF OBJECT_ID(N'dbo.TR_roster_assignment_no_overlap', N'TR') IS NOT NULL DROP TRIGGER dbo.TR_roster_assignment_no_overlap;",
    """
IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'UIX_roster_assignment_now' AND object_id = OBJECT_ID(N'dbo.roster_assignment'))
    DROP INDEX UIX_roster_assignment_now ON dbo.roster_assignment;
IF OBJECT_ID(N'dbo.FK_roster_dimension_item_Country', N'F') IS NOT NULL
    ALTER TABLE dbo.roster_dimension_item DROP CONSTRAINT FK_roster_dimension_item_Country;
IF OBJECT_ID(N'dbo.FK_roster_assignment_Employee', N'F') IS NOT NULL
    ALTER TABLE dbo.roster_assignment DROP CONSTRAINT FK_roster_assignment_Employee;
""",
]


class Migration(migrations.Migration):
    dependencies = [("roster", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
