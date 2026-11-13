"""Fase 17: jerarquía operativa (Operations Director → Operations Manager → Account Supervisor → Team Manager).

* FK_ops_leader_Employee hacia hcm.Employee (SQL-first).
* TR_ops_leader_rules (50080): cada líder reporta a un líder ACTIVO del nivel inmediato superior (el Director a
  nadie) y un líder con subordinados activos no se desactiva.
* Dimensiones del roster OPS_DIRECTOR → OPS_MANAGER → ACCOUNT_SUPERVISOR → TEAM_MANAGER (padre = nivel superior) y el
  atributo temporal «team_manager» (Team Manager del agente por fechas; los niveles superiores se derivan).
* Vistas: dbo.vw_OpsLeaderHierarchy (cada Team Manager con su cadena completa) y dbo.vw_RosterAgentHierarchy
  (agente → Team Manager → Account Supervisor → Operations Manager → Operations Director, con vigencias del roster).
* Sin datos de personas: los líderes se registran en WFM › Jerarquía operativa.
"""

from django.db import migrations

_REQUIRE = """
IF OBJECT_ID(N'hcm.Employee', N'U') IS NULL
    THROW 50010, N'Falta hcm.Employee. Ejecute database/deploy.ps1 antes de migrate.', 1;
"""

FK = """
IF OBJECT_ID(N'dbo.FK_ops_leader_Employee', N'F') IS NULL
    ALTER TABLE dbo.ops_leader WITH CHECK ADD CONSTRAINT FK_ops_leader_Employee FOREIGN KEY (employee_id) REFERENCES hcm.Employee (EmployeeId);
"""

TRIGGER = """
CREATE OR ALTER TRIGGER dbo.TR_ops_leader_rules
ON dbo.ops_leader
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        LEFT JOIN dbo.ops_leader AS b ON b.id = i.reports_to_id
        WHERE (i.level = N'OPS_DIRECTOR' AND i.reports_to_id IS NOT NULL)
           OR (i.level <> N'OPS_DIRECTOR' AND (b.id IS NULL
               OR b.level <> CASE i.level WHEN N'OPS_MANAGER' THEN N'OPS_DIRECTOR'
                                          WHEN N'ACCOUNT_SUPERVISOR' THEN N'OPS_MANAGER'
                                          WHEN N'TEAM_MANAGER' THEN N'ACCOUNT_SUPERVISOR' END
               OR (i.is_active = 1 AND b.is_active = 0)))
    )
        THROW 50080, N'Jerarquía operativa: cada líder reporta a un líder activo del nivel inmediato superior.', 1;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.ops_leader AS s ON s.reports_to_id = i.id AND s.is_active = 1
        WHERE i.is_active = 0
    )
        THROW 50080, N'Jerarquía operativa: un líder con subordinados activos no se puede desactivar.', 1;
END
"""

LEADER_VIEW = """
CREATE OR ALTER VIEW dbo.vw_OpsLeaderHierarchy
AS
SELECT
    tm.id                AS TeamManagerLeaderId,
    etm.EmployeeCode     AS TeamManagerId,
    CONCAT_WS(N' ', etm.FirstName, etm.LastName) AS TeamManagerName,
    eas.EmployeeCode     AS AccountSupervisorId,
    CONCAT_WS(N' ', eas.FirstName, eas.LastName) AS AccountSupervisorName,
    eom.EmployeeCode     AS OperationsManagerId,
    CONCAT_WS(N' ', eom.FirstName, eom.LastName) AS OperationsManagerName,
    eod.EmployeeCode     AS OperationsDirectorId,
    CONCAT_WS(N' ', eod.FirstName, eod.LastName) AS OperationsDirectorName,
    c.code               AS ClientCode,
    tm.is_active         AS IsActive
FROM dbo.ops_leader AS tm
JOIN hcm.Employee AS etm ON etm.EmployeeId = tm.employee_id
LEFT JOIN dbo.ops_leader AS sup ON sup.id = tm.reports_to_id
LEFT JOIN hcm.Employee AS eas ON eas.EmployeeId = sup.employee_id
LEFT JOIN dbo.ops_leader AS om ON om.id = sup.reports_to_id
LEFT JOIN hcm.Employee AS eom ON eom.EmployeeId = om.employee_id
LEFT JOIN dbo.ops_leader AS od ON od.id = om.reports_to_id
LEFT JOIN hcm.Employee AS eod ON eod.EmployeeId = od.employee_id
LEFT JOIN dbo.ops_client AS c ON c.id = COALESCE(tm.client_id, sup.client_id, om.client_id)
WHERE tm.level = N'TEAM_MANAGER';
"""

AGENT_VIEW = """
CREATE OR ALTER VIEW dbo.vw_RosterAgentHierarchy
AS
SELECT
    e.EmployeeCode       AS EmployeeId,
    CONCAT_WS(N' ', e.FirstName, e.MiddleName, e.LastName, e.SecondLastName) AS EmployeeName,
    r.effective_start    AS EffectiveStart,
    r.effective_end      AS EffectiveEnd,
    h.TeamManagerId, h.TeamManagerName,
    h.AccountSupervisorId, h.AccountSupervisorName,
    h.OperationsManagerId, h.OperationsManagerName,
    h.OperationsDirectorId, h.OperationsDirectorName
FROM dbo.roster_assignment AS r
JOIN dbo.roster_attribute AS a ON a.id = r.attribute_id AND a.code = N'team_manager'
JOIN hcm.Employee AS e ON e.EmployeeId = r.employee_id
JOIN dbo.ops_leader AS l ON l.roster_item_id = r.item_id
JOIN dbo.vw_OpsLeaderHierarchy AS h ON h.TeamManagerLeaderId = l.id
WHERE r.superseded_at IS NULL;
"""

FORWARD = [_REQUIRE, FK, TRIGGER, LEADER_VIEW, AGENT_VIEW]
REVERSE = [
    "IF OBJECT_ID(N'dbo.vw_RosterAgentHierarchy', N'V') IS NOT NULL DROP VIEW dbo.vw_RosterAgentHierarchy;",
    "IF OBJECT_ID(N'dbo.vw_OpsLeaderHierarchy', N'V') IS NOT NULL DROP VIEW dbo.vw_OpsLeaderHierarchy;",
    "IF OBJECT_ID(N'dbo.TR_ops_leader_rules', N'TR') IS NOT NULL DROP TRIGGER dbo.TR_ops_leader_rules;",
    "IF OBJECT_ID(N'dbo.FK_ops_leader_Employee', N'F') IS NOT NULL ALTER TABLE dbo.ops_leader DROP CONSTRAINT FK_ops_leader_Employee;",
]

DIMENSIONS = [
    ("OPS_DIRECTOR", "Operations Director", None),
    ("OPS_MANAGER", "Operations Manager", "OPS_DIRECTOR"),
    ("ACCOUNT_SUPERVISOR", "Account Supervisor", "OPS_MANAGER"),
    ("TEAM_MANAGER", "Team Manager", "ACCOUNT_SUPERVISOR"),
]


def seed(apps, schema_editor):
    Dimension = apps.get_model("roster", "RosterDimension")
    Attribute = apps.get_model("roster", "RosterAttribute")
    dims = {}
    for code, name, parent in DIMENSIONS:
        dims[code], _ = Dimension.objects.get_or_create(code=code, defaults={"name": name, "parent": dims.get(parent)})
    Attribute.objects.get_or_create(
        code="team_manager",
        defaults={
            "name": "Team Manager", "group": "Jerarquía operativa", "display_order": 45, "data_type": "DIMENSION",
            "dimension": dims["TEAM_MANAGER"],
            "help": "Team Manager del agente. Account Supervisor, Operations Manager y Operations Director se derivan "
                    "de la jerarquía operativa (WFM › Jerarquía operativa).",
        },
    )


def unseed(apps, schema_editor):
    Attribute = apps.get_model("roster", "RosterAttribute")
    if apps.get_model("roster", "RosterAssignment").objects.filter(attribute__code="team_manager").exists():
        return
    Attribute.objects.filter(code="team_manager").delete()
    Dimension = apps.get_model("roster", "RosterDimension")
    for code, _, _ in reversed(DIMENSIONS):
        Dimension.objects.filter(code=code, items__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("operations", "0003_operationalleader"), ("roster", "0003_seed_dimensions_and_attributes")]

    operations = [
        migrations.RunSQL(FORWARD, REVERSE),
        migrations.RunPython(seed, unseed),
    ]
