"""Fase 25 — Reglas de SQL Server del periódico virtual (los objetos pasan al esquema `com` en system.0015).

* TR_com_announcement_ack_rules (AFTER INSERT/UPDATE/DELETE): un acuse solo se registra sobre un comunicado PUBLICADO
  que requiere acuse (50121) y nunca se modifica ni se borra (50120).
* TR_com_announcement_rules (AFTER UPDATE): publicado con acuse, el contenido queda congelado (50122).
* TR_com_announcement_no_delete (INSTEAD OF DELETE): solo se eliminan borradores (50123).
* TR_com_compliance_snapshot_locked: las fotos de cumplimiento son inmutables (50124).
* vw_AnnouncementCompliance: audiencia (usuarios activos del rol), confirmados y % por comunicado con acuse.
* usp_AnnouncementComplianceReport @AnnouncementId: detalle por usuario (CONFIRMADO / FUERA DE PLAZO / PENDIENTE / VENCIDO).
"""

from django.db import migrations

TRIGGERS = [
    r"""
CREATE OR ALTER TRIGGER dbo.TR_com_announcement_ack_rules ON dbo.com_announcement_ack
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (SELECT 1 FROM deleted)
        THROW 50120, N'Los acuses de recibo son inmutables: no se modifican ni se eliminan.', 1;
    IF EXISTS (SELECT 1 FROM inserted i JOIN dbo.com_announcement a ON a.id = i.announcement_id
               WHERE a.status <> N'PUBLISHED' OR a.requires_ack = 0)
        THROW 50121, N'Solo se confirma un comunicado publicado que requiere acuse de recibo.', 1;
END
""",
    r"""
CREATE OR ALTER TRIGGER dbo.TR_com_announcement_rules ON dbo.com_announcement
AFTER UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1 FROM inserted i JOIN deleted d ON d.id = i.id
        WHERE d.status <> N'DRAFT' AND d.requires_ack = 1
          AND (i.title <> d.title OR i.summary <> d.summary OR i.body <> d.body OR i.category <> d.category
               OR i.link_url <> d.link_url OR i.requires_ack <> d.requires_ack OR i.content_hash <> d.content_hash
               OR i.status = N'DRAFT')
    )
        THROW 50122, N'El contenido de un comunicado con acuse de recibo publicado está congelado.', 1;
END
""",
    r"""
CREATE OR ALTER TRIGGER dbo.TR_com_announcement_no_delete ON dbo.com_announcement
INSTEAD OF DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (SELECT 1 FROM deleted WHERE status <> N'DRAFT')
        THROW 50123, N'Solo se eliminan borradores: un comunicado publicado se archiva.', 1;
    DELETE a FROM dbo.com_announcement a JOIN deleted d ON d.id = a.id;
END
""",
    r"""
CREATE OR ALTER TRIGGER dbo.TR_com_compliance_snapshot_locked ON dbo.com_compliance_snapshot
AFTER UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 50124, N'Las fotos de cumplimiento (compliance) son inmutables.', 1;
END
""",
]

VIEW = r"""
CREATE OR ALTER VIEW dbo.vw_AnnouncementCompliance
AS
WITH aud AS (
    SELECT a.id AS AnnouncementId, u.id AS UserId
    FROM dbo.com_announcement a
    JOIN dbo.accounts_customuser u ON u.is_active = 1
    WHERE a.requires_ack = 1 AND a.status <> N'DRAFT'
      AND (ISNULL(a.audience_roles, N'[]') IN (N'[]', N'')
           OR EXISTS (SELECT 1 FROM OPENJSON(a.audience_roles) r
                      WHERE r.value = CASE WHEN u.is_superuser = 1 THEN N'ADMIN' ELSE u.role END))
)
SELECT a.id AS AnnouncementId, a.title AS Title, a.category AS Category, a.status AS Status, a.published_at AS PublishedAt,
       a.ack_due_date AS AckDueDate,
       COUNT(aud.UserId) AS Audience,
       COUNT(k.id) AS Acknowledged,
       COUNT(aud.UserId) - COUNT(k.id) AS Pending,
       CASE WHEN a.ack_due_date < CAST(GETDATE() AS date) THEN COUNT(aud.UserId) - COUNT(k.id) ELSE 0 END AS Overdue,
       CAST(CASE WHEN COUNT(aud.UserId) = 0 THEN 100.0
                 ELSE 100.0 * COUNT(k.id) / COUNT(aud.UserId) END AS decimal(5, 2)) AS CompliancePct
FROM dbo.com_announcement a
LEFT JOIN aud ON aud.AnnouncementId = a.id
LEFT JOIN dbo.com_announcement_ack k ON k.announcement_id = a.id AND k.user_id = aud.UserId
WHERE a.requires_ack = 1 AND a.status <> N'DRAFT'
GROUP BY a.id, a.title, a.category, a.status, a.published_at, a.ack_due_date;
"""

PROC = r"""
CREATE OR ALTER PROCEDURE dbo.usp_AnnouncementComplianceReport
    @AnnouncementId int
AS
BEGIN
    SET NOCOUNT ON;
    SELECT u.username AS Username, LTRIM(RTRIM(CONCAT(u.first_name, N' ', u.last_name))) AS FullName,
           CASE WHEN u.is_superuser = 1 THEN N'ADMIN' ELSE u.role END AS Role, u.employee_code AS EmployeeCode,
           k.acknowledged_at AS AcknowledgedAt, k.ip_address AS IpAddress,
           CASE WHEN k.id IS NOT NULL AND CAST(k.acknowledged_at AS date) > a.ack_due_date THEN N'LATE'
                WHEN k.id IS NOT NULL THEN N'ACKNOWLEDGED'
                WHEN a.ack_due_date < CAST(GETDATE() AS date) THEN N'OVERDUE'
                ELSE N'PENDING' END AS ComplianceStatus,
           CASE WHEN k.id IS NULL THEN NULL WHEN k.content_hash = a.content_hash THEN 1 ELSE 0 END AS HashMatches
    FROM dbo.com_announcement a
    JOIN dbo.accounts_customuser u ON u.is_active = 1
    LEFT JOIN dbo.com_announcement_ack k ON k.announcement_id = a.id AND k.user_id = u.id
    WHERE a.id = @AnnouncementId AND a.requires_ack = 1
      AND (ISNULL(a.audience_roles, N'[]') IN (N'[]', N'')
           OR EXISTS (SELECT 1 FROM OPENJSON(a.audience_roles) r
                      WHERE r.value = CASE WHEN u.is_superuser = 1 THEN N'ADMIN' ELSE u.role END))
    ORDER BY CASE WHEN k.id IS NULL THEN 0 ELSE 1 END, u.username;
END
"""

REVERSE = [
    "DROP PROCEDURE IF EXISTS dbo.usp_AnnouncementComplianceReport",
    "DROP VIEW IF EXISTS dbo.vw_AnnouncementCompliance",
    "DROP TRIGGER IF EXISTS dbo.TR_com_compliance_snapshot_locked",
    "DROP TRIGGER IF EXISTS dbo.TR_com_announcement_no_delete",
    "DROP TRIGGER IF EXISTS dbo.TR_com_announcement_rules",
    "DROP TRIGGER IF EXISTS dbo.TR_com_announcement_ack_rules",
]


class Migration(migrations.Migration):
    dependencies = [("communications", "0001_phase25"), ("accounts", "0003_phase25")]

    operations = [
        migrations.RunSQL(sql=[*TRIGGERS, VIEW, PROC], reverse_sql=REVERSE),
    ]
