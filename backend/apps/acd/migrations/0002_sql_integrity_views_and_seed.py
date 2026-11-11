"""ACD (Fase 11): integridad en SQL Server, vistas de reportería y catálogos de referencia.

* FKs a hcm.Employee (SQL-first) de pertenencias, sesiones y segmentos.
* TR_acd_status_segment_rules:
      50060  segmentos de estado traslapados para un agente (uno termina exactamente cuando inicia el siguiente)
      50061  el auxiliar del segmento pertenece a otro estado primario
* TR_acd_aux_code_rules (50062): un sub-auxiliar tiene un solo nivel y el mismo estado primario que su padre.
* Vistas: vw_AcdStatusSegment (un segmento por fila con las columnas del reporte de Genesys Cloud, horas en UTC) y
  vw_AcdAgentSession (sesiones con el envío del tiempo pagado a horarios).
* Semilla de REFERENCIA (catálogos, sin agentes): división «Home», los 10 estados operativos de Genesys Cloud,
  auxiliares y sub-auxiliares comunes de BPO y el grupo GENERAL. Se ajustan en /admin/ y en «Grupos y auxiliares».
"""

from django.db import migrations

_REQUIRE = """
IF OBJECT_ID(N'hcm.Employee', N'U') IS NULL
    THROW 50010, N'Falta hcm.Employee. Ejecute database/deploy.ps1 antes de migrate.', 1;
"""

_FKS = [("acd_agent_member", "Employee"), ("acd_agent_session", "Employee"), ("acd_status_segment", "Employee")]

SEGMENT_TRIGGER = """
CREATE OR ALTER TRIGGER dbo.TR_acd_status_segment_rules
ON dbo.acd_status_segment
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.acd_status_segment AS s
          ON s.employee_id = i.employee_id AND s.id <> i.id
         AND s.start_at < ISNULL(i.end_at, '9999-12-31') AND i.start_at < ISNULL(s.end_at, '9999-12-31')
    )
        THROW 50060, N'ACD: el segmento de estado se traslapa con otro del mismo agente.', 1;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.acd_aux_code AS a ON a.id = i.aux_code_id
        WHERE a.primary_status_id <> i.primary_status_id
    )
        THROW 50061, N'ACD: el auxiliar no pertenece al estado primario del segmento.', 1;
END
"""

AUX_TRIGGER = """
CREATE OR ALTER TRIGGER dbo.TR_acd_aux_code_rules
ON dbo.acd_aux_code
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.acd_aux_code AS p ON p.id = i.parent_id
        WHERE p.parent_id IS NOT NULL OR p.primary_status_id <> i.primary_status_id
    ) OR EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.acd_aux_code AS c ON c.parent_id = i.id
        WHERE i.parent_id IS NOT NULL OR c.primary_status_id <> i.primary_status_id
    )
        THROW 50062, N'ACD: un sub-auxiliar tiene un solo nivel y el mismo estado primario que su auxiliar padre.', 1;
END
"""

SEGMENT_VIEW = """
CREATE OR ALTER VIEW dbo.vw_AcdStatusSegment
AS
SELECT
    s.id                AS SegmentId,
    e.EmployeeId        AS EmployeeKey,
    e.EmployeeCode      AS EmployeeId,
    CONCAT_WS(N' ', e.FirstName, e.MiddleName, e.LastName, e.SecondLastName) AS EmployeeName,
    d.division_uid      AS DivisionId,
    d.name              AS DivisionName,
    g.code              AS GroupCode,
    g.name              AS GroupName,
    s.start_at          AS StartTimeUtc,
    s.end_at            AS EndTimeUtc,
    ps.code             AS PrimaryStatusCode,
    ps.label            AS PrimaryStatus,
    a.code              AS AuxCode,
    CASE WHEN a.id IS NULL THEN N'' WHEN pa.id IS NULL THEN a.name ELSE CONCAT(pa.name, N' - ', a.name) END AS SecondaryStatus,
    ISNULL(s.duration_ms, DATEDIFF_BIG(MILLISECOND, s.start_at, SYSUTCDATETIME())) AS DurationMs,
    CAST(CASE WHEN s.end_at IS NULL THEN 1 ELSE 0 END AS BIT) AS IsOpen,
    ps.is_productive    AS IsProductive,
    s.source            AS Source,
    s.session_id        AS SessionId
FROM dbo.acd_status_segment AS s
JOIN hcm.Employee AS e ON e.EmployeeId = s.employee_id
JOIN dbo.acd_primary_status AS ps ON ps.id = s.primary_status_id
LEFT JOIN dbo.acd_aux_code AS a ON a.id = s.aux_code_id
LEFT JOIN dbo.acd_aux_code AS pa ON pa.id = a.parent_id
LEFT JOIN dbo.acd_division AS d ON d.id = s.division_id
LEFT JOIN dbo.acd_agent_group AS g ON g.id = s.group_id;
"""

SESSION_VIEW = """
CREATE OR ALTER VIEW dbo.vw_AcdAgentSession
AS
SELECT
    x.id                AS SessionId,
    e.EmployeeCode      AS EmployeeId,
    CONCAT_WS(N' ', e.FirstName, e.MiddleName, e.LastName, e.SecondLastName) AS EmployeeName,
    g.code              AS GroupCode,
    d.name              AS DivisionName,
    x.login_at          AS LoginUtc,
    x.logout_at         AS LogoutUtc,
    DATEDIFF_BIG(MILLISECOND, x.login_at, ISNULL(x.logout_at, SYSUTCDATETIME())) AS SessionMs,
    x.logout_source     AS LogoutSource,
    x.sync_status       AS TimeSyncStatus,
    x.paid_minutes      AS PaidMinutesSent,
    x.sync_message      AS TimeSyncMessage
FROM dbo.acd_agent_session AS x
JOIN hcm.Employee AS e ON e.EmployeeId = x.employee_id
JOIN dbo.acd_agent_group AS g ON g.id = x.group_id
JOIN dbo.acd_division AS d ON d.id = g.division_id;
"""

FORWARD = [
    _REQUIRE,
    "\n".join(
        f"IF OBJECT_ID(N'dbo.FK_{t}_{n}', N'F') IS NULL\n"
        f"    ALTER TABLE dbo.{t} WITH CHECK ADD CONSTRAINT FK_{t}_{n} FOREIGN KEY (employee_id) REFERENCES hcm.Employee (EmployeeId);"
        for t, n in _FKS
    ),
    SEGMENT_TRIGGER, AUX_TRIGGER, SEGMENT_VIEW, SESSION_VIEW,
]
REVERSE = [
    "IF OBJECT_ID(N'dbo.vw_AcdAgentSession', N'V') IS NOT NULL DROP VIEW dbo.vw_AcdAgentSession;",
    "IF OBJECT_ID(N'dbo.vw_AcdStatusSegment', N'V') IS NOT NULL DROP VIEW dbo.vw_AcdStatusSegment;",
    "IF OBJECT_ID(N'dbo.TR_acd_aux_code_rules', N'TR') IS NOT NULL DROP TRIGGER dbo.TR_acd_aux_code_rules;",
    "IF OBJECT_ID(N'dbo.TR_acd_status_segment_rules', N'TR') IS NOT NULL DROP TRIGGER dbo.TR_acd_status_segment_rules;",
    "\n".join(
        f"IF OBJECT_ID(N'dbo.FK_{t}_{n}', N'F') IS NOT NULL ALTER TABLE dbo.{t} DROP CONSTRAINT FK_{t}_{n};" for t, n in _FKS
    ),
]

# code, label (Genesys), nombre, sesión iniciada, productivo, pagado, elegible por el agente, color, orden
PRIMARY = [
    ("OFFLINE", "Offline", "Desconectado", False, False, False, False, "#94a3b8", 10),
    ("AVAILABLE", "Available", "Disponible", True, False, True, True, "#16a34a", 20),
    ("ON_QUEUE", "On Queue", "En cola", True, True, True, True, "#0284c7", 30),
    ("BUSY", "Busy", "Ocupado", True, False, True, True, "#dc2626", 40),
    ("AWAY", "Away", "Ausente", True, False, True, True, "#d97706", 50),
    ("BREAK", "Break", "Descanso", True, False, True, True, "#ca8a04", 60),
    ("MEAL", "Meal", "Almuerzo", True, False, False, True, "#ea580c", 70),
    ("MEETING", "Meeting", "Reunión", True, False, True, True, "#7c3aed", 80),
    ("TRAINING", "Training", "Capacitación", True, False, True, True, "#4f46e5", 90),
    ("IDLE", "Idle", "Inactivo", True, False, True, False, "#78716c", 100),
]

# code, estado primario, nombre (Secondary Status), padre, productivo, máx. minutos, restringido, orden
AUX = [
    ("BREAK_STD", "BREAK", "Break", None, False, 15, False, 10),
    ("BREAK_PERSONAL", "BREAK", "Personal", None, False, 10, False, 20),
    ("LUNCH", "MEAL", "Lunch", None, False, 60, False, 10),
    ("ACW", "BUSY", "ACW", None, True, 10, False, 10),
    ("BACK_OFFICE", "BUSY", "Back Office", None, True, None, True, 20),
    ("SYSTEM_ISSUE", "AWAY", "System Issue", None, False, None, False, 10),
    ("COACHING", "MEETING", "Coaching", None, False, None, True, 10),
    ("COACHING_QA", "MEETING", "Calidad", "COACHING", False, 60, True, 11),
    ("COACHING_SUP", "MEETING", "Supervisor", "COACHING", False, 60, True, 12),
    ("TEAM_MEETING", "MEETING", "Team Meeting", None, False, None, True, 20),
    ("TRAINING_SESSION", "TRAINING", "Training", None, False, None, True, 10),
]


def seed(apps, schema_editor):
    Division = apps.get_model("acd", "Division")
    PrimaryStatus = apps.get_model("acd", "PrimaryStatus")
    AuxCode = apps.get_model("acd", "AuxCode")
    AgentGroup = apps.get_model("acd", "AgentGroup")
    GroupAuxAccess = apps.get_model("acd", "GroupAuxAccess")

    home, _ = Division.objects.get_or_create(code="HOME", defaults={"name": "Home"})
    statuses = {}
    for code, label, name, logged, productive, paid, selectable, color, order in PRIMARY:
        statuses[code], _ = PrimaryStatus.objects.get_or_create(code=code, defaults={
            "label": label, "name_es": name, "is_logged_in": logged, "is_productive": productive, "is_paid": paid,
            "agent_selectable": selectable, "color": color, "sort_order": order,
        })
    auxes = {}
    for code, primary, name, parent, productive, max_minutes, restricted, order in AUX:
        auxes[code], _ = AuxCode.objects.get_or_create(code=code, defaults={
            "primary_status": statuses[primary], "name": name, "parent": auxes.get(parent), "is_productive": productive,
            "max_minutes": max_minutes, "is_restricted": restricted, "sort_order": order,
        })
    general, created = AgentGroup.objects.get_or_create(code="GENERAL", defaults={
        "name": "Agentes (general)", "division": home,
        "description": "Grupo de referencia: auxiliares generales + Coaching, Team Meeting y Training. Ajuste el acceso por campaña.",
    })
    if created:
        for code in ("COACHING", "TEAM_MEETING", "TRAINING_SESSION"):
            GroupAuxAccess.objects.create(group=general, aux_code=auxes[code])


class Migration(migrations.Migration):
    dependencies = [("acd", "0001_initial")]

    operations = [
        migrations.RunSQL(FORWARD, REVERSE),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
