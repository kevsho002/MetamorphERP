"""Horarios y tiempo: integridad en SQL Server + vistas para reportería (Power BI / JOINs).

* FKs a hcm.Employee y core.catCountry (SQL-first).
* CHECKs: definición del turno = JSON válido; cada porción de tiempo cae dentro de UN día calendario.
* Triggers (la base de datos lo garantiza aunque se escriba directo en las tablas):
    50040  dos asignaciones de horario del mismo empleado en fechas que se cruzan
    50041  dos registros de tiempo (entrada/salida) del mismo empleado que se traslapan
    50042  dos reglas de nocturnidad ACTIVAS del mismo país con vigencias que se cruzan
    50043  periodos de pago traslapados en un ciclo
    50044  ventanas de corte (asistencia) traslapadas en un ciclo
* Vistas:
    dbo.vw_SchTimeByOccurrenceDate   tiempo real por fecha de ocurrencia (con turno de origen y corte)
    dbo.vw_SchScheduleAssignment     horarios asignados con su vigencia
    dbo.vw_SchPayPeriod              periodos de pago con su ventana de corte
"""

from django.db import migrations

_REQUIRE = """
IF OBJECT_ID(N'hcm.Employee', N'U') IS NULL OR OBJECT_ID(N'core.catCountry', N'U') IS NULL
    THROW 50010, N'Faltan objetos SQL-first (hcm.Employee / core.catCountry). Ejecute database/deploy.ps1 antes de migrate.', 1;
"""

_FKS = [
    ("sch_schedule_assignment", "employee_id", "Employee", "hcm.Employee (EmployeeId)"),
    ("sch_time_record", "employee_id", "Employee", "hcm.Employee (EmployeeId)"),
    ("sch_time_record_day", "employee_id", "Employee", "hcm.Employee (EmployeeId)"),
    ("sch_shift", "country_id", "Country", "core.catCountry (CountryId)"),
    ("sch_night_rule", "country_id", "Country", "core.catCountry (CountryId)"),
    ("sch_pay_cycle", "country_id", "Country", "core.catCountry (CountryId)"),
]

FORWARD = [
    _REQUIRE,
    "\n".join(
        f"IF OBJECT_ID(N'dbo.FK_{t}_{n}', N'F') IS NULL\n"
        f"    ALTER TABLE dbo.{t} WITH CHECK ADD CONSTRAINT FK_{t}_{n} FOREIGN KEY ({c}) REFERENCES {ref};"
        for t, c, n, ref in _FKS
    ),
    """
IF OBJECT_ID(N'dbo.ck_sch_shift_definition_json', N'C') IS NULL
    ALTER TABLE dbo.sch_shift WITH CHECK ADD CONSTRAINT ck_sch_shift_definition_json
        CHECK (ISJSON(definition) = 1 AND JSON_QUERY(definition, '$.days') IS NOT NULL);
IF OBJECT_ID(N'dbo.ck_sch_time_day_single_day', N'C') IS NULL
    ALTER TABLE dbo.sch_time_record_day WITH CHECK ADD CONSTRAINT ck_sch_time_day_single_day
        CHECK (
            (start_at IS NULL AND end_at IS NULL)
            OR (start_at IS NOT NULL AND end_at IS NOT NULL
                AND CAST(start_at AS date) = occurrence_date
                AND end_at > start_at
                AND end_at <= DATEADD(DAY, 1, CAST(occurrence_date AS datetime2(0))))
        );
""",
    """
CREATE OR ALTER TRIGGER dbo.TR_sch_schedule_assignment_rules
ON dbo.sch_schedule_assignment
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.sch_schedule_assignment AS a
          ON a.employee_id = i.employee_id
         AND a.id <> i.id
         AND a.effective_start_date <= ISNULL(i.effective_end_date, '9999-12-31')
         AND i.effective_start_date <= ISNULL(a.effective_end_date, '9999-12-31')
    )
        THROW 50040, N'Horarios: el empleado ya tiene otro horario activo en fechas que se cruzan.', 1;
END
""",
    """
CREATE OR ALTER TRIGGER dbo.TR_sch_time_record_rules
ON dbo.sch_time_record
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.sch_time_record AS r
          ON r.employee_id = i.employee_id
         AND r.id <> i.id
         AND r.kind = N'INTERVAL' AND i.kind = N'INTERVAL'
         AND r.start_at < i.end_at
         AND i.start_at < r.end_at
    )
        THROW 50041, N'Tiempo: el registro se traslapa con otro registro de entrada/salida del empleado.', 1;
END
""",
    """
CREATE OR ALTER TRIGGER dbo.TR_sch_night_rule_rules
ON dbo.sch_night_rule
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.sch_night_rule AS r
          ON r.country_id = i.country_id
         AND r.id <> i.id
         AND r.is_active = 1 AND i.is_active = 1
         AND r.effective_start_date <= ISNULL(i.effective_end_date, '9999-12-31')
         AND i.effective_start_date <= ISNULL(r.effective_end_date, '9999-12-31')
    )
        THROW 50042, N'Nocturnidad: ya hay otra regla activa para el país en fechas que se cruzan.', 1;
END
""",
    """
CREATE OR ALTER TRIGGER dbo.TR_sch_pay_period_rules
ON dbo.sch_pay_period
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.sch_pay_period AS p
          ON p.cycle_id = i.cycle_id AND p.id <> i.id
         AND p.period_start <= i.period_end AND i.period_start <= p.period_end
    )
        THROW 50043, N'Ciclos de pago: el periodo se traslapa con otro periodo del mismo ciclo.', 1;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.sch_pay_period AS p
          ON p.cycle_id = i.cycle_id AND p.id <> i.id
         AND p.cutoff_start <= i.cutoff_end AND i.cutoff_start <= p.cutoff_end
    )
        THROW 50044, N'Ciclos de pago: la ventana de corte se traslapa con la de otro periodo del mismo ciclo.', 1;
END
""",
    """
CREATE OR ALTER VIEW dbo.vw_SchPayPeriod
AS
SELECT
    p.id                AS PayPeriodId,
    c.code              AS CycleCode,
    c.name              AS CycleName,
    cc.CountryCode      AS CountryCode,
    c.pay_frequency     AS PayFrequency,
    c.is_default        AS IsDefaultCycle,
    p.code              AS PeriodCode,
    p.period_start      AS PeriodStart,
    p.period_end        AS PeriodEnd,
    p.cutoff_start      AS CutoffStart,
    p.cutoff_end        AS CutoffEnd,
    p.payment_date      AS PaymentDate,
    p.status            AS PeriodStatus
FROM dbo.sch_pay_period AS p
JOIN dbo.sch_pay_cycle AS c ON c.id = p.cycle_id
JOIN core.catCountry AS cc ON cc.CountryId = c.country_id;
""",
    """
CREATE OR ALTER VIEW dbo.vw_SchScheduleAssignment
AS
SELECT
    a.id                    AS AssignmentId,
    e.EmployeeId            AS EmployeeId,
    e.EmployeeCode          AS EmployeeCode,
    CONCAT_WS(N' ', e.FirstName, e.MiddleName, e.LastName, e.SecondLastName) AS FullName,
    c.CountryCode           AS CountryCode,
    e.EmploymentStatus      AS EmploymentStatus,
    s.code                  AS ShiftCode,
    s.name                  AS ShiftName,
    s.weekly_minutes        AS WeeklyScheduledMinutes,
    s.definition            AS ShiftDefinition,
    a.effective_start_date  AS EffectiveStart,
    a.effective_end_date    AS EffectiveEnd,
    CAST(CASE WHEN a.effective_end_date IS NULL THEN 1 ELSE 0 END AS BIT) AS IsNow
FROM dbo.sch_schedule_assignment AS a
JOIN dbo.sch_shift AS s ON s.id = a.shift_id
JOIN hcm.Employee AS e ON e.EmployeeId = a.employee_id
JOIN core.catCountry AS c ON c.CountryId = e.CountryId;
""",
    """
CREATE OR ALTER VIEW dbo.vw_SchTimeByOccurrenceDate
AS
SELECT
    d.id                    AS TimeDayId,
    d.record_id             AS TimeRecordId,
    e.EmployeeId            AS EmployeeId,
    e.EmployeeCode          AS EmployeeCode,
    CONCAT_WS(N' ', e.FirstName, e.MiddleName, e.LastName, e.SecondLastName) AS FullName,
    c.CountryCode           AS CountryCode,
    d.occurrence_date       AS OccurrenceDate,
    d.shift_date            AS ShiftDate,
    d.start_at              AS StartAt,
    d.end_at                AS EndAt,
    d.minutes               AS WorkedMinutes,
    d.night_minutes         AS NightMinutes,
    nr.surcharge_percent    AS NightSurchargePercent,
    r.kind                  AS RecordKind,
    r.source                AS Source,
    r.external_ref          AS ExternalRef,
    pp.code                 AS PayPeriodCode,
    pp.status               AS PayPeriodStatus
FROM dbo.sch_time_record_day AS d
JOIN dbo.sch_time_record AS r ON r.id = d.record_id
JOIN hcm.Employee AS e ON e.EmployeeId = d.employee_id
JOIN core.catCountry AS c ON c.CountryId = e.CountryId
LEFT JOIN dbo.sch_night_rule AS nr ON nr.id = d.night_rule_id
LEFT JOIN dbo.sch_pay_cycle AS pc
       ON pc.country_id = e.CountryId AND pc.pay_frequency = e.PayFrequency AND pc.is_default = 1 AND pc.is_active = 1
LEFT JOIN dbo.sch_pay_period AS pp
       ON pp.cycle_id = pc.id AND d.occurrence_date BETWEEN pp.cutoff_start AND pp.cutoff_end;
""",
]

REVERSE = [
    "IF OBJECT_ID(N'dbo.vw_SchTimeByOccurrenceDate', N'V') IS NOT NULL DROP VIEW dbo.vw_SchTimeByOccurrenceDate;",
    "IF OBJECT_ID(N'dbo.vw_SchScheduleAssignment', N'V') IS NOT NULL DROP VIEW dbo.vw_SchScheduleAssignment;",
    "IF OBJECT_ID(N'dbo.vw_SchPayPeriod', N'V') IS NOT NULL DROP VIEW dbo.vw_SchPayPeriod;",
    "IF OBJECT_ID(N'dbo.TR_sch_pay_period_rules', N'TR') IS NOT NULL DROP TRIGGER dbo.TR_sch_pay_period_rules;",
    "IF OBJECT_ID(N'dbo.TR_sch_night_rule_rules', N'TR') IS NOT NULL DROP TRIGGER dbo.TR_sch_night_rule_rules;",
    "IF OBJECT_ID(N'dbo.TR_sch_time_record_rules', N'TR') IS NOT NULL DROP TRIGGER dbo.TR_sch_time_record_rules;",
    "IF OBJECT_ID(N'dbo.TR_sch_schedule_assignment_rules', N'TR') IS NOT NULL DROP TRIGGER dbo.TR_sch_schedule_assignment_rules;",
    """
IF OBJECT_ID(N'dbo.ck_sch_time_day_single_day', N'C') IS NOT NULL ALTER TABLE dbo.sch_time_record_day DROP CONSTRAINT ck_sch_time_day_single_day;
IF OBJECT_ID(N'dbo.ck_sch_shift_definition_json', N'C') IS NOT NULL ALTER TABLE dbo.sch_shift DROP CONSTRAINT ck_sch_shift_definition_json;
""",
    "\n".join(
        f"IF OBJECT_ID(N'dbo.FK_{t}_{n}', N'F') IS NOT NULL ALTER TABLE dbo.{t} DROP CONSTRAINT FK_{t}_{n};"
        for t, c, n, ref in _FKS
    ),
]


class Migration(migrations.Migration):
    dependencies = [("scheduling", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
