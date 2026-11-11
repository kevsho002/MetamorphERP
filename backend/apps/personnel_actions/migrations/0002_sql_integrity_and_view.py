"""Acciones de Personal: integridad en SQL Server + vista para reportería.

* FK_pa_action_Employee hacia hcm.Employee (SQL-first) y CHECK del formato del folio.
* TR_pa_action_signature_immutable (50050): una firma no se modifica ni se borra.
* TR_pa_action_value_frozen (50051): los valores EAV solo cambian mientras la AP es borrador.
* TR_pa_action_content_frozen (50052): enviada la AP, su folio, tipo, empleado, fecha efectiva, justificación y
  sello de contenido no cambian (solo avanzan el estado y las fechas del flujo).
* dbo.vw_PersonnelAction: cada AP con empleado, tipo, estado y avance de firmas.
"""

from django.db import migrations

_REQUIRE = """
IF OBJECT_ID(N'hcm.Employee', N'U') IS NULL
    THROW 50010, N'Falta hcm.Employee. Ejecute database/deploy.ps1 antes de migrate.', 1;
"""

FORWARD = [
    _REQUIRE,
    """
IF OBJECT_ID(N'dbo.FK_pa_action_Employee', N'F') IS NULL
    ALTER TABLE dbo.pa_action WITH CHECK ADD CONSTRAINT FK_pa_action_Employee FOREIGN KEY (employee_id) REFERENCES hcm.Employee (EmployeeId);
IF OBJECT_ID(N'dbo.ck_pa_action_folio', N'C') IS NULL
    ALTER TABLE dbo.pa_action WITH CHECK ADD CONSTRAINT ck_pa_action_folio
        CHECK (folio COLLATE Latin1_General_BIN LIKE N'[A-Z][A-Z]%-[0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]');
IF OBJECT_ID(N'dbo.ck_pa_action_sealed', N'C') IS NULL
    ALTER TABLE dbo.pa_action WITH CHECK ADD CONSTRAINT ck_pa_action_sealed
        CHECK (status = N'DRAFT' OR status = N'CANCELLED' OR LEN(content_hash) = 64);
""",
    """
CREATE OR ALTER TRIGGER dbo.TR_pa_action_signature_immutable
ON dbo.pa_action_signature
AFTER UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (SELECT 1 FROM deleted)
        THROW 50050, N'Acciones de personal: las firmas son inmutables (no se modifican ni se eliminan).', 1;
END
""",
    """
CREATE OR ALTER TRIGGER dbo.TR_pa_action_value_frozen
ON dbo.pa_action_value
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1
        FROM (SELECT action_id FROM inserted UNION SELECT action_id FROM deleted) AS x
        JOIN dbo.pa_action AS a ON a.id = x.action_id
        WHERE a.status <> N'DRAFT'
    )
        THROW 50051, N'Acciones de personal: los datos de una AP enviada a aprobación no se modifican.', 1;
END
""",
    """
CREATE OR ALTER TRIGGER dbo.TR_pa_action_content_frozen
ON dbo.pa_action
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN deleted AS d ON d.id = i.id
        WHERE d.status <> N'DRAFT'
          AND (i.folio <> d.folio OR i.action_type_id <> d.action_type_id OR i.employee_id <> d.employee_id
               OR i.effective_date <> d.effective_date OR i.justification <> d.justification
               OR i.content_hash <> d.content_hash OR i.is_initial <> d.is_initial)
    )
        THROW 50052, N'Acciones de personal: el contenido de una AP enviada a aprobación no se modifica.', 1;
    IF EXISTS (
        SELECT 1 FROM inserted AS i JOIN deleted AS d ON d.id = i.id
        WHERE d.status IN (N'APPROVED', N'REJECTED', N'CANCELLED') AND i.status <> d.status
    )
        THROW 50052, N'Acciones de personal: una AP resuelta (aprobada, rechazada o anulada) no cambia de estado.', 1;
END
""",
    """
CREATE OR ALTER VIEW dbo.vw_PersonnelAction
AS
SELECT
    a.id                    AS ActionId,
    a.folio                 AS Folio,
    t.code                  AS ActionTypeCode,
    t.name                  AS ActionTypeName,
    t.category              AS Category,
    t.effect                AS Effect,
    a.is_initial            AS IsInitial,
    e.EmployeeId            AS EmployeeId,
    e.EmployeeCode          AS EmployeeCode,
    CONCAT_WS(N' ', e.FirstName, e.MiddleName, e.LastName, e.SecondLastName) AS FullName,
    c.CountryCode           AS CountryCode,
    a.effective_date        AS EffectiveDate,
    a.status                AS Status,
    a.created_at            AS CreatedAt,
    a.submitted_at          AS SubmittedAt,
    a.decided_at            AS DecidedAt,
    a.applied_at            AS AppliedAt,
    (SELECT COUNT(*) FROM dbo.pa_approval_step AS s WHERE s.action_type_id = t.id)                 AS StepsTotal,
    (SELECT COUNT(*) FROM dbo.pa_action_signature AS g WHERE g.action_id = a.id AND g.decision = N'APPROVED') AS StepsApproved
FROM dbo.pa_action AS a
JOIN dbo.pa_action_type AS t ON t.id = a.action_type_id
JOIN hcm.Employee AS e ON e.EmployeeId = a.employee_id
JOIN core.catCountry AS c ON c.CountryId = e.CountryId;
""",
]

REVERSE = [
    "IF OBJECT_ID(N'dbo.vw_PersonnelAction', N'V') IS NOT NULL DROP VIEW dbo.vw_PersonnelAction;",
    "IF OBJECT_ID(N'dbo.TR_pa_action_content_frozen', N'TR') IS NOT NULL DROP TRIGGER dbo.TR_pa_action_content_frozen;",
    "IF OBJECT_ID(N'dbo.TR_pa_action_value_frozen', N'TR') IS NOT NULL DROP TRIGGER dbo.TR_pa_action_value_frozen;",
    "IF OBJECT_ID(N'dbo.TR_pa_action_signature_immutable', N'TR') IS NOT NULL DROP TRIGGER dbo.TR_pa_action_signature_immutable;",
    """
IF OBJECT_ID(N'dbo.ck_pa_action_sealed', N'C') IS NOT NULL ALTER TABLE dbo.pa_action DROP CONSTRAINT ck_pa_action_sealed;
IF OBJECT_ID(N'dbo.ck_pa_action_folio', N'C') IS NOT NULL ALTER TABLE dbo.pa_action DROP CONSTRAINT ck_pa_action_folio;
IF OBJECT_ID(N'dbo.FK_pa_action_Employee', N'F') IS NOT NULL ALTER TABLE dbo.pa_action DROP CONSTRAINT FK_pa_action_Employee;
""",
]


class Migration(migrations.Migration):
    dependencies = [("personnel_actions", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
