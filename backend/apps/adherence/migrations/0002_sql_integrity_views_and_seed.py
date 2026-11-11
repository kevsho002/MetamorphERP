"""Fase 16: integridad en SQL Server, vistas para nómina / calidad y catálogo de actividades de referencia.

* FKs a hcm.Employee (SQL-first) de segmentos, justificaciones y resultados.
* TR_adh_schedule_segment_rules (50070): segmentos de actividad traslapados para un agente.
* TR_adh_exception_rules (50071): la AP que justifica debe estar APROBADA y ser del mismo empleado.
* Vistas: vw_AdhScheduleSegment (plan programado), vw_AdhAdherenceDay (adherencia, pago válido, billing, trabajo
  principal vs auxiliares secundarios y Unpaid Excess Login por agente y fecha, con el corte de asistencia y el periodo
  de pago) y vw_AdhDeviation (Out of Adherence / Unpaid Excess Login con lo programado vs lo real).
* Semilla de REFERENCIA (catálogo, sin agentes ni horarios): Producción (predeterminada), Back Office, Break,
  Almuerzo, Capacitación, Coaching y Reunión, con los estados ACD de la Fase 11 que cumplen cada una.
"""

from django.db import migrations

_REQUIRE = """
IF OBJECT_ID(N'hcm.Employee', N'U') IS NULL
    THROW 50010, N'Falta hcm.Employee. Ejecute database/deploy.ps1 antes de migrate.', 1;
"""

_FKS = [("adh_schedule_segment", "Employee"), ("adh_exception", "Employee"), ("adh_adherence_day", "Employee"),
        ("adh_deviation", "Employee")]

SEGMENT_TRIGGER = """
CREATE OR ALTER TRIGGER dbo.TR_adh_schedule_segment_rules
ON dbo.adh_schedule_segment
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.adh_schedule_segment AS s
          ON s.employee_id = i.employee_id AND s.id <> i.id
         AND s.start_at < i.end_at AND i.start_at < s.end_at
    )
        THROW 50070, N'Segmentos: el segmento de actividad se traslapa con otro del mismo agente.', 1;
END
"""

EXCEPTION_TRIGGER = """
CREATE OR ALTER TRIGGER dbo.TR_adh_exception_rules
ON dbo.adh_exception
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.pa_action AS a ON a.id = i.personnel_action_id
        WHERE a.status <> N'APPROVED' OR a.employee_id <> i.employee_id
    )
        THROW 50071, N'Justificaciones: la AP debe estar aprobada y ser del mismo empleado.', 1;
END
"""

SEGMENT_VIEW = """
CREATE OR ALTER VIEW dbo.vw_AdhScheduleSegment
AS
SELECT
    s.id                AS SegmentId,
    e.EmployeeCode      AS EmployeeId,
    CONCAT_WS(N' ', e.FirstName, e.MiddleName, e.LastName, e.SecondLastName) AS EmployeeName,
    s.shift_date        AS ShiftDate,
    s.start_at          AS StartLocal,
    s.end_at            AS EndLocal,
    DATEDIFF(MINUTE, s.start_at, s.end_at) AS Minutes,
    t.code              AS ActivityCode,
    t.name              AS ActivityName,
    t.category          AS ActivityCategory,
    t.is_paid           AS IsPaid,
    t.is_billable       AS IsBillable,
    pa.folio            AS ScheduleActionFolio,
    s.notes             AS Notes
FROM dbo.adh_schedule_segment AS s
JOIN hcm.Employee AS e ON e.EmployeeId = s.employee_id
JOIN dbo.adh_activity_type AS t ON t.id = s.activity_id
LEFT JOIN dbo.sch_schedule_assignment AS sa ON sa.id = s.assignment_id
LEFT JOIN dbo.pa_action AS pa ON pa.id = sa.personnel_action_id;
"""

DAY_VIEW = """
CREATE OR ALTER VIEW dbo.vw_AdhAdherenceDay
AS
SELECT
    d.id                AS AdherenceDayId,
    e.EmployeeCode      AS EmployeeId,
    CONCAT_WS(N' ', e.FirstName, e.MiddleName, e.LastName, e.SecondLastName) AS EmployeeName,
    d.shift_date        AS ShiftDate,
    d.scheduled_seconds / 60.0              AS ScheduledMinutes,
    d.in_adherence_seconds / 60.0           AS InAdherenceMinutes,
    d.out_of_adherence_seconds / 60.0       AS OutOfAdherenceMinutes,
    d.justified_seconds / 60.0              AS JustifiedMinutes,
    d.logged_seconds / 60.0                 AS LoggedMinutes,
    d.paid_valid_seconds / 60.0             AS PaidValidMinutes,
    d.billable_seconds / 60.0               AS BillableMinutes,
    d.primary_work_seconds / 60.0           AS PrimaryWorkMinutes,
    d.secondary_paid_seconds / 60.0         AS SecondaryPaidMinutes,
    d.unpaid_excess_seconds / 60.0          AS UnpaidExcessLoginMinutes,
    d.adherence_pct     AS AdherencePct,
    d.conformance_pct   AS ConformancePct,
    c.code              AS AttendanceCutoff,
    c.status            AS CutoffStatus,
    p.code              AS PayPeriod,
    d.computed_at       AS ComputedAtUtc
FROM dbo.adh_adherence_day AS d
JOIN hcm.Employee AS e ON e.EmployeeId = d.employee_id
OUTER APPLY (
    SELECT TOP (1) ac.code, ac.status, ac.pay_period_id
    FROM dbo.sch_attendance_cutoff AS ac
    JOIN dbo.sch_pay_cycle AS pc ON pc.id = ac.cycle_id AND pc.is_default = 1 AND pc.is_active = 1
    WHERE pc.country_id = e.CountryId AND pc.pay_frequency = e.PayFrequency
      AND d.shift_date BETWEEN ac.cutoff_start AND ac.cutoff_end
) AS c
LEFT JOIN dbo.sch_pay_period AS p ON p.id = c.pay_period_id;
"""

DEVIATION_VIEW = """
CREATE OR ALTER VIEW dbo.vw_AdhDeviation
AS
SELECT
    x.id                AS DeviationId,
    e.EmployeeCode      AS EmployeeId,
    CONCAT_WS(N' ', e.FirstName, e.MiddleName, e.LastName, e.SecondLastName) AS EmployeeName,
    x.shift_date        AS ShiftDate,
    x.kind              AS DeviationKind,
    CASE x.kind WHEN N'UNPAID_EXCESS_LOGIN' THEN N'Unpaid Excess Login' ELSE N'Out of Adherence' END AS DeviationLabel,
    x.start_at          AS StartLocal,
    x.end_at            AS EndLocal,
    x.seconds           AS DurationSeconds,
    t.code              AS ScheduledActivity,
    ps.label            AS ActualPrimaryStatus,
    CASE WHEN pa.id IS NULL THEN a.name ELSE CONCAT(pa.name, N' - ', a.name) END AS ActualSecondaryStatus
FROM dbo.adh_deviation AS x
JOIN hcm.Employee AS e ON e.EmployeeId = x.employee_id
LEFT JOIN dbo.adh_activity_type AS t ON t.id = x.expected_activity_id
LEFT JOIN dbo.acd_primary_status AS ps ON ps.id = x.actual_status_id
LEFT JOIN dbo.acd_aux_code AS a ON a.id = x.actual_aux_id
LEFT JOIN dbo.acd_aux_code AS pa ON pa.id = a.parent_id;
"""

FORWARD = [
    _REQUIRE,
    "\n".join(
        f"IF OBJECT_ID(N'dbo.FK_{t}_{n}', N'F') IS NULL\n"
        f"    ALTER TABLE dbo.{t} WITH CHECK ADD CONSTRAINT FK_{t}_{n} FOREIGN KEY (employee_id) REFERENCES hcm.Employee (EmployeeId);"
        for t, n in _FKS
    ),
    SEGMENT_TRIGGER, EXCEPTION_TRIGGER, SEGMENT_VIEW, DAY_VIEW, DEVIATION_VIEW,
]
REVERSE = [
    "IF OBJECT_ID(N'dbo.vw_AdhDeviation', N'V') IS NOT NULL DROP VIEW dbo.vw_AdhDeviation;",
    "IF OBJECT_ID(N'dbo.vw_AdhAdherenceDay', N'V') IS NOT NULL DROP VIEW dbo.vw_AdhAdherenceDay;",
    "IF OBJECT_ID(N'dbo.vw_AdhScheduleSegment', N'V') IS NOT NULL DROP VIEW dbo.vw_AdhScheduleSegment;",
    "IF OBJECT_ID(N'dbo.TR_adh_exception_rules', N'TR') IS NOT NULL DROP TRIGGER dbo.TR_adh_exception_rules;",
    "IF OBJECT_ID(N'dbo.TR_adh_schedule_segment_rules', N'TR') IS NOT NULL DROP TRIGGER dbo.TR_adh_schedule_segment_rules;",
    "\n".join(
        f"IF OBJECT_ID(N'dbo.FK_{t}_{n}', N'F') IS NOT NULL ALTER TABLE dbo.{t} DROP CONSTRAINT FK_{t}_{n};" for t, n in _FKS
    ),
]

# code, nombre, categoría, color, pagada, facturable, predeterminada, minutos sugeridos, orden,
# reglas: (estado primario, auxiliar | None, rol)
ACTIVITIES = [
    ("PRODUCTION", "Producción (Calls / Chats / Tickets)", "PRODUCTION", "#0284c7", True, True, True, None, 10,
     [("ON_QUEUE", None, "PRIMARY"), ("BUSY", "ACW", "SECONDARY")]),
    ("BACK_OFFICE", "Back Office", "BACK_OFFICE", "#0f766e", True, True, False, 60, 20,
     [("BUSY", "BACK_OFFICE", "PRIMARY")]),
    ("BREAK", "Break programado", "BREAK", "#ca8a04", True, False, False, 15, 30,
     [("BREAK", None, "PRIMARY")]),
    ("MEAL", "Almuerzo", "MEAL", "#ea580c", False, False, False, 60, 40,
     [("MEAL", None, "PRIMARY")]),
    ("TRAINING", "Conexión a capacitación", "TRAINING", "#4f46e5", True, False, False, 60, 50,
     [("TRAINING", None, "PRIMARY")]),
    ("COACHING", "Coaching", "COACHING", "#7c3aed", True, False, False, 30, 60,
     [("MEETING", "COACHING", "PRIMARY")]),
    ("MEETING", "Reunión de equipo", "MEETING", "#9333ea", True, False, False, 30, 70,
     [("MEETING", "TEAM_MEETING", "PRIMARY")]),
]


def seed(apps, schema_editor):
    ActivityType = apps.get_model("adherence", "ActivityType")
    ActivityStatusRule = apps.get_model("adherence", "ActivityStatusRule")
    PrimaryStatus = apps.get_model("acd", "PrimaryStatus")
    AuxCode = apps.get_model("acd", "AuxCode")
    statuses = {s.code: s for s in PrimaryStatus.objects.all()}
    auxes = {a.code: a for a in AuxCode.objects.all()}
    has_default = ActivityType.objects.filter(is_default=True).exists()
    for code, name, category, color, paid, billable, default, minutes, order, rules in ACTIVITIES:
        if ActivityType.objects.filter(code=code).exists():
            continue
        a = ActivityType.objects.create(code=code, name=name, category=category, color=color, is_paid=paid, is_billable=billable,
                                        is_default=default and not has_default, default_minutes=minutes, sort_order=order)
        for primary, aux, role in rules:
            if primary in statuses and (aux is None or aux in auxes):
                ActivityStatusRule.objects.create(activity=a, primary_status=statuses[primary], aux_code=auxes.get(aux) if aux else None, role=role)


class Migration(migrations.Migration):
    dependencies = [
        ("adherence", "0001_initial"),
        ("acd", "0002_sql_integrity_views_and_seed"),
        ("personnel_actions", "0005_seed_additional_schedule_type"),
        ("scheduling", "0009_phase11_sql_rules_and_views"),
    ]

    operations = [
        migrations.RunSQL(FORWARD, REVERSE),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
