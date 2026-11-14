"""Fase 24 — Reglas de SQL Server para los adjuntos (evidencias) de las AP y su vista de auditoría.

* TR_pa_action_attachment_no_delete (INSTEAD OF DELETE)
      50110  los adjuntos no se eliminan: se retiran con motivo (queda la huella en la auditoría)
* TR_pa_action_attachment_rules (AFTER INSERT, UPDATE)
      50111  no se adjuntan archivos a una AP aprobada, rechazada o anulada (solo en borrador o en aprobación)
      50112  el contenido de un adjunto es inmutable (AP, archivo, ruta, tamaño, SHA-256, clase y MIME)
      50113  retirar un adjunto exige motivo, solo mientras la AP está en borrador o en aprobación, y no se revierte
* dbo.vw_PaActionAttachment: adjuntos con folio, tipo y colaborador de la AP (vigentes y retirados).
"""

from django.db import migrations

NO_DELETE = """
CREATE OR ALTER TRIGGER dbo.TR_pa_action_attachment_no_delete
ON dbo.pa_action_attachment
INSTEAD OF DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (SELECT 1 FROM deleted)
        THROW 50110, N'Adjuntos de AP: no se eliminan; retírelos con un motivo (la evidencia queda en la auditoría).', 1;
END
"""

RULES = """
CREATE OR ALTER TRIGGER dbo.TR_pa_action_attachment_rules
ON dbo.pa_action_attachment
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT EXISTS (SELECT 1 FROM deleted)
    BEGIN
        IF EXISTS (
            SELECT 1 FROM inserted AS i JOIN dbo.pa_action AS a ON a.id = i.action_id
            WHERE a.status NOT IN (N'DRAFT', N'PENDING') OR i.removed_at IS NOT NULL
        )
            THROW 50111, N'Adjuntos de AP: solo se adjuntan archivos a una AP en borrador o en aprobación.', 1;
        RETURN;
    END
    IF EXISTS (
        SELECT 1 FROM inserted AS i JOIN deleted AS d ON d.id = i.id
        WHERE i.action_id <> d.action_id OR i.original_name <> d.original_name OR i.storage_path <> d.storage_path
           OR i.size_bytes <> d.size_bytes OR i.sha256_hash <> d.sha256_hash OR i.kind <> d.kind OR i.mime_type <> d.mime_type
    )
        THROW 50112, N'Adjuntos de AP: el contenido de un adjunto es inmutable.', 1;
    IF EXISTS (
        SELECT 1 FROM inserted AS i JOIN deleted AS d ON d.id = i.id JOIN dbo.pa_action AS a ON a.id = i.action_id
        WHERE (d.removed_at IS NOT NULL AND (i.removed_at IS NULL OR i.removed_at <> d.removed_at))
           OR (d.removed_at IS NULL AND i.removed_at IS NOT NULL
               AND (a.status NOT IN (N'DRAFT', N'PENDING') OR LEN(LTRIM(RTRIM(i.removed_reason))) = 0))
    )
        THROW 50113, N'Adjuntos de AP: se retiran con motivo, solo mientras la AP está en borrador o en aprobación, y el retiro no se revierte.', 1;
END
"""

VIEW = """
CREATE OR ALTER VIEW dbo.vw_PaActionAttachment
AS
SELECT
    f.id                    AS AttachmentId,
    a.folio                 AS Folio,
    t.code                  AS ActionTypeCode,
    t.name                  AS ActionTypeName,
    a.status                AS ActionStatus,
    e.EmployeeCode          AS EmployeeCode,
    CONCAT_WS(N' ', e.FirstName, e.MiddleName, e.LastName, e.SecondLastName) AS FullName,
    f.category              AS Category,
    f.kind                  AS Kind,
    f.description           AS Description,
    f.original_name         AS OriginalName,
    f.mime_type             AS MimeType,
    f.size_bytes            AS SizeBytes,
    f.sha256_hash           AS Sha256Hash,
    f.status_at_upload      AS StatusAtUpload,
    f.uploaded_at           AS UploadedAt,
    f.uploaded_by_username  AS UploadedBy,
    f.removed_at            AS RemovedAt,
    f.removed_by_username   AS RemovedBy,
    f.removed_reason        AS RemovedReason,
    CAST(CASE WHEN f.removed_at IS NULL THEN 1 ELSE 0 END AS bit) AS IsCurrent
FROM dbo.pa_action_attachment AS f
JOIN dbo.pa_action AS a ON a.id = f.action_id
JOIN dbo.pa_action_type AS t ON t.id = a.action_type_id
JOIN hcm.Employee AS e ON e.EmployeeId = a.employee_id;
"""

DROP = """
DROP VIEW IF EXISTS dbo.vw_PaActionAttachment;
DROP TRIGGER IF EXISTS dbo.TR_pa_action_attachment_rules;
DROP TRIGGER IF EXISTS dbo.TR_pa_action_attachment_no_delete;
"""


class Migration(migrations.Migration):
    dependencies = [("personnel_actions", "0012_phase24_attachments")]

    operations = [
        migrations.RunSQL(NO_DELETE, migrations.RunSQL.noop),
        migrations.RunSQL(RULES, migrations.RunSQL.noop),
        migrations.RunSQL(VIEW, DROP),
    ]
