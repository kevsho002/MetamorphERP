"""Fase 22: estadísticas de datos por tabla y modelo entidad-relación (panel de administrador).

* dbo.usp_SystemTableStats      procedimiento almacenado: filas, espacio reservado / usado (datos e índices), columnas,
                                llaves foráneas entrantes y salientes de cada tabla de usuario (sys.partitions +
                                sys.allocation_units; no requiere permisos de servidor).
* dbo.vw_SystemForeignKeys      vista: cada relación (FK) con su tabla / columna de origen y destino, para dibujar el ERD.
* dbo.usp_SystemTableColumns    procedimiento almacenado: columnas de una o todas las tablas (tipo, nulabilidad, PK, FK).
"""

from django.db import migrations

STATS = """
CREATE OR ALTER PROCEDURE dbo.usp_SystemTableStats
AS
BEGIN
    SET NOCOUNT ON;
    WITH sizes AS (
        SELECT p.object_id,
               SUM(CASE WHEN p.index_id IN (0, 1) THEN p.rows ELSE 0 END) AS row_count,
               SUM(a.total_pages) * 8 AS reserved_kb,
               SUM(a.used_pages) * 8 AS used_kb,
               SUM(CASE WHEN p.index_id IN (0, 1) THEN a.used_pages ELSE 0 END) * 8 AS data_kb
        FROM sys.partitions p
        JOIN sys.allocation_units a ON a.container_id = CASE WHEN a.type = 2 THEN p.partition_id ELSE p.hobt_id END
        GROUP BY p.object_id
    )
    SELECT s.name AS schema_name, t.name AS table_name, t.object_id,
           ISNULL(z.row_count, 0) AS row_count,
           ISNULL(z.reserved_kb, 0) AS reserved_kb,
           ISNULL(z.used_kb, 0) AS used_kb,
           ISNULL(z.data_kb, 0) AS data_kb,
           ISNULL(z.used_kb, 0) - ISNULL(z.data_kb, 0) AS index_kb,
           (SELECT COUNT(*) FROM sys.columns c WHERE c.object_id = t.object_id) AS column_count,
           (SELECT COUNT(*) FROM sys.foreign_keys f WHERE f.parent_object_id = t.object_id) AS fk_out,
           (SELECT COUNT(*) FROM sys.foreign_keys f WHERE f.referenced_object_id = t.object_id) AS fk_in,
           (SELECT COUNT(*) FROM sys.triggers g WHERE g.parent_id = t.object_id) AS trigger_count,
           t.create_date, t.modify_date
    FROM sys.tables t
    JOIN sys.schemas s ON s.schema_id = t.schema_id
    LEFT JOIN sizes z ON z.object_id = t.object_id
    WHERE t.is_ms_shipped = 0
    ORDER BY s.name, t.name;
END;
"""

FK_VIEW = """
CREATE OR ALTER VIEW dbo.vw_SystemForeignKeys
AS
SELECT f.name AS fk_name,
       OBJECT_SCHEMA_NAME(f.parent_object_id) AS from_schema, OBJECT_NAME(f.parent_object_id) AS from_table,
       pc.name AS from_column,
       OBJECT_SCHEMA_NAME(f.referenced_object_id) AS to_schema, OBJECT_NAME(f.referenced_object_id) AS to_table,
       rc.name AS to_column,
       fc.constraint_column_id AS column_order,
       f.delete_referential_action_desc AS on_delete,
       CONVERT(bit, f.is_disabled) AS is_disabled
FROM sys.foreign_keys f
JOIN sys.foreign_key_columns fc ON fc.constraint_object_id = f.object_id
JOIN sys.columns pc ON pc.object_id = fc.parent_object_id AND pc.column_id = fc.parent_column_id
JOIN sys.columns rc ON rc.object_id = fc.referenced_object_id AND rc.column_id = fc.referenced_column_id
WHERE OBJECTPROPERTY(f.parent_object_id, 'IsMSShipped') = 0;
"""

COLUMNS = """
CREATE OR ALTER PROCEDURE dbo.usp_SystemTableColumns
    @Schema sysname = NULL,
    @Table sysname = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SELECT s.name AS schema_name, t.name AS table_name, c.column_id, c.name AS column_name,
           ty.name AS type_name, c.max_length, c.precision, c.scale, CONVERT(bit, c.is_nullable) AS is_nullable,
           CONVERT(bit, CASE WHEN EXISTS (
               SELECT 1 FROM sys.index_columns ic JOIN sys.indexes i ON i.object_id = ic.object_id AND i.index_id = ic.index_id
               WHERE i.is_primary_key = 1 AND ic.object_id = c.object_id AND ic.column_id = c.column_id) THEN 1 ELSE 0 END) AS is_pk,
           CONVERT(bit, CASE WHEN EXISTS (
               SELECT 1 FROM sys.foreign_key_columns fc WHERE fc.parent_object_id = c.object_id AND fc.parent_column_id = c.column_id)
               THEN 1 ELSE 0 END) AS is_fk,
           CONVERT(bit, c.is_computed) AS is_computed
    FROM sys.columns c
    JOIN sys.tables t ON t.object_id = c.object_id
    JOIN sys.schemas s ON s.schema_id = t.schema_id
    JOIN sys.types ty ON ty.user_type_id = c.user_type_id
    WHERE t.is_ms_shipped = 0
      AND (@Schema IS NULL OR s.name = @Schema)
      AND (@Table IS NULL OR t.name = @Table)
    ORDER BY s.name, t.name, c.column_id;
END;
"""


class Migration(migrations.Migration):
    dependencies = [("system", "0010_phase22_appearance_notifications")]

    operations = [
        migrations.RunSQL(STATS, "DROP PROCEDURE IF EXISTS dbo.usp_SystemTableStats;"),
        migrations.RunSQL(FK_VIEW, "DROP VIEW IF EXISTS dbo.vw_SystemForeignKeys;"),
        migrations.RunSQL(COLUMNS, "DROP PROCEDURE IF EXISTS dbo.usp_SystemTableColumns;"),
    ]
