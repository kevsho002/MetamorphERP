"""Fase 23: alcance jerárquico de las AP en SQL Server.

dbo.fn_EmployeesUnderLeader(@LeaderEmployeeId, @On) — función de tabla con CTE recursiva sobre la cadena de mando
(dbo.ops_leader): devuelve los colaboradores bajo el líder en la fecha, directos (depth = 1) o indirectos (depth > 1):

* los líderes que le reportan (Operations Manager → Account Supervisor → Team Manager…), y
* los agentes asignados en el roster vigente (atributo team_manager, sin corregir) a cualquier Team Manager del árbol.

El selector de colaboradores de las AP y la validación del servidor usan esta función.
"""

from django.db import migrations

FN = """
CREATE OR ALTER FUNCTION dbo.fn_EmployeesUnderLeader (@LeaderEmployeeId int, @On date)
RETURNS TABLE
AS
RETURN
WITH tree AS (
    SELECT l.id, l.level, l.roster_item_id, l.employee_id, 0 AS depth
    FROM dbo.ops_leader l
    WHERE l.employee_id = @LeaderEmployeeId AND l.is_active = 1
    UNION ALL
    SELECT c.id, c.level, c.roster_item_id, c.employee_id, t.depth + 1
    FROM dbo.ops_leader c
    JOIN tree t ON c.reports_to_id = t.id
    WHERE c.is_active = 1 AND t.depth < 20
),
members AS (
    SELECT t.employee_id, t.depth FROM tree t WHERE t.depth > 0
    UNION ALL
    SELECT ra.employee_id, t.depth + 1
    FROM tree t
    JOIN dbo.roster_assignment ra ON ra.item_id = t.roster_item_id
    JOIN dbo.roster_attribute at ON at.id = ra.attribute_id AND at.code = N'team_manager'
    WHERE t.level = N'TEAM_MANAGER'
      AND ra.superseded_at IS NULL
      AND ra.effective_start <= @On
      AND (ra.effective_end IS NULL OR ra.effective_end >= @On)
)
SELECT m.employee_id, MIN(m.depth) AS depth,
       CASE WHEN MIN(m.depth) = 1 THEN N'DIRECT' ELSE N'INDIRECT' END AS relation
FROM members m
WHERE m.employee_id <> @LeaderEmployeeId
GROUP BY m.employee_id;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("personnel_actions", "0010_phase22_seed_types"),
        ("operations", "0004_leader_sql_rules_views_and_seed"),
        ("roster", "0003_seed_dimensions_and_attributes"),
    ]

    operations = [migrations.RunSQL(FN, "DROP FUNCTION IF EXISTS dbo.fn_EmployeesUnderLeader;")]
