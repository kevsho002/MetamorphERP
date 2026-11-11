"""Fase 10 — reglas de SQL Server para cortes BPO, varias AP por día y reglas de almuerzo.

* Ciclos de pago (TR_sch_pay_period_rules): los periodos pueden cruzar de un mes al siguiente (10–24 y 25–9).
  Se valida solo la continuidad contra el periodo ANTERIOR del ciclo:
      50043  colisión: el periodo se traslapa con otro del ciclo
      50044  colisión: la ventana de corte se traslapa con otra
      50045  hueco o colisión: el periodo no inicia el día siguiente al fin del periodo anterior
      50046  hueco o colisión: la ventana de corte no inicia el día siguiente al corte anterior
* Horarios (TR_sch_schedule_assignment_rules, 50040): un solo horario PRINCIPAL por fecha; las asignaciones
  ADICIONALES (turno partido / doble, con fecha de fin) conviven con él. Que los bloques no pidan las mismas horas
  lo valida la aplicación al elaborar y al aprobar la AP (es una regla sobre el JSON de bloques).
* Reglas de almuerzo (TR_sch_lunch_rule_rules, 50047): un umbral por país y fechas.
* Vistas: vw_SchScheduleAssignment (+ AssignmentMode), vw_SchScheduleDay (una fila por BLOQUE),
  vw_SchLunchRule (nueva).
* Semillas: regla de almuerzo SV de referencia (≥ 6 h continuas → 30 min, advertencia) y el ciclo de ejemplo
  SV_QUINCENAL_BPO (10–24 / 25–9, NO predeterminado) con sus periodos 2026.
"""

from datetime import date

from django.db import migrations

ASSIGNMENT_TRIGGER = """
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
         AND a.mode = N'PRIMARY' AND i.mode = N'PRIMARY'
         AND a.effective_start_date <= ISNULL(i.effective_end_date, '9999-12-31')
         AND i.effective_start_date <= ISNULL(a.effective_end_date, '9999-12-31')
    )
        THROW 50040, N'Horarios: el empleado ya tiene otro horario PRINCIPAL en fechas que se cruzan (use una asignación adicional para turnos partidos o dobles).', 1;
END
"""

ASSIGNMENT_TRIGGER_OLD = """
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
"""

PERIOD_TRIGGER = """
CREATE OR ALTER TRIGGER dbo.TR_sch_pay_period_rules
ON dbo.sch_pay_period
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT (UPDATE(period_start) OR UPDATE(period_end) OR UPDATE(cutoff_start) OR UPDATE(cutoff_end) OR UPDATE(cycle_id))
        RETURN;  -- cerrar / reabrir un corte no cambia sus fechas
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.sch_pay_period AS p
          ON p.cycle_id = i.cycle_id AND p.id <> i.id
         AND p.period_start <= i.period_end AND i.period_start <= p.period_end
    )
        THROW 50043, N'Ciclos de pago: el periodo colisiona con otro periodo del mismo ciclo.', 1;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.sch_pay_period AS p
          ON p.cycle_id = i.cycle_id AND p.id <> i.id
         AND p.cutoff_start <= i.cutoff_end AND i.cutoff_start <= p.cutoff_end
    )
        THROW 50044, N'Ciclos de pago: la ventana de corte colisiona con la de otro periodo del mismo ciclo.', 1;
    -- Continuidad contra el periodo ANTERIOR (los periodos pueden cruzar de mes: 10–24 y 25–9).
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        CROSS APPLY (
            SELECT TOP (1) p.period_end
            FROM dbo.sch_pay_period AS p
            WHERE p.cycle_id = i.cycle_id AND p.id <> i.id AND p.period_start < i.period_start
            ORDER BY p.period_start DESC
        ) AS prev
        WHERE prev.period_end <> DATEADD(DAY, -1, i.period_start)
    )
        THROW 50045, N'Ciclos de pago: el periodo debe iniciar el día siguiente al fin del periodo anterior (sin huecos ni colisiones).', 1;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        CROSS APPLY (
            SELECT TOP (1) p.cutoff_end
            FROM dbo.sch_pay_period AS p
            WHERE p.cycle_id = i.cycle_id AND p.id <> i.id AND p.period_start < i.period_start
            ORDER BY p.period_start DESC
        ) AS prev
        WHERE prev.cutoff_end <> DATEADD(DAY, -1, i.cutoff_start)
    )
        THROW 50046, N'Ciclos de pago: la ventana de corte debe iniciar el día siguiente al corte del periodo anterior.', 1;
END
"""

PERIOD_TRIGGER_OLD = """
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
"""

LUNCH_TRIGGER = """
CREATE OR ALTER TRIGGER dbo.TR_sch_lunch_rule_rules
ON dbo.sch_lunch_rule
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.sch_lunch_rule AS r
          ON r.country_id = i.country_id
         AND r.id <> i.id
         AND r.is_active = 1 AND i.is_active = 1
         AND r.min_block_minutes = i.min_block_minutes
         AND r.effective_start_date <= ISNULL(i.effective_end_date, '9999-12-31')
         AND i.effective_start_date <= ISNULL(r.effective_end_date, '9999-12-31')
    )
        THROW 50047, N'Almuerzo: ya hay otra regla activa del país con el mismo umbral en fechas que se cruzan.', 1;
END
"""

ASSIGNMENT_VIEW = """
CREATE OR ALTER VIEW dbo.vw_SchScheduleAssignment
AS
SELECT
    a.id                    AS AssignmentId,
    e.EmployeeId            AS EmployeeId,
    e.EmployeeCode          AS EmployeeCode,
    CONCAT_WS(N' ', e.FirstName, e.MiddleName, e.LastName, e.SecondLastName) AS FullName,
    c.CountryCode           AS CountryCode,
    e.EmploymentStatus      AS EmploymentStatus,
    a.mode                  AS AssignmentMode,
    pa.folio                AS ActionFolio,
    t.code                  AS ActionTypeCode,
    a.weekly_minutes        AS WeeklyScheduledMinutes,
    a.definition            AS ScheduleDefinition,
    a.effective_start_date  AS EffectiveStart,
    a.effective_end_date    AS EffectiveEnd,
    CAST(CASE WHEN a.effective_end_date IS NULL THEN 1 ELSE 0 END AS BIT) AS IsNow
FROM dbo.sch_schedule_assignment AS a
JOIN hcm.Employee AS e ON e.EmployeeId = a.employee_id
JOIN core.catCountry AS c ON c.CountryId = e.CountryId
LEFT JOIN dbo.pa_action AS pa ON pa.id = a.personnel_action_id
LEFT JOIN dbo.pa_action_type AS t ON t.id = pa.action_type_id;
"""

# Una fila por BLOQUE: el día puede ser un objeto (un bloque, formato anterior) o una lista de bloques.
DAY_VIEW = """
CREATE OR ALTER VIEW dbo.vw_SchScheduleDay
AS
SELECT
    a.id                    AS AssignmentId,
    a.employee_id           AS EmployeeId,
    e.EmployeeCode          AS EmployeeCode,
    pa.folio                AS ActionFolio,
    a.mode                  AS AssignmentMode,
    a.effective_start_date  AS EffectiveStart,
    a.effective_end_date    AS EffectiveEnd,
    d.[key]                 AS DayKey,
    b.BlockNo               AS BlockNo,
    JSON_VALUE(b.BlockJson, '$.start')                     AS StartTime,
    JSON_VALUE(b.BlockJson, '$.end')                       AS EndTime,
    TRY_CAST(JSON_VALUE(b.BlockJson, '$.lunch_minutes') AS INT) AS LunchMinutes,
    TRY_CAST(JSON_VALUE(b.BlockJson, '$.day_minutes') AS INT)   AS DayMinutes,
    TRY_CAST(JSON_VALUE(b.BlockJson, '$.night_minutes') AS INT) AS NightMinutes
FROM dbo.sch_schedule_assignment AS a
JOIN hcm.Employee AS e ON e.EmployeeId = a.employee_id
LEFT JOIN dbo.pa_action AS pa ON pa.id = a.personnel_action_id
CROSS APPLY OPENJSON(a.definition, '$.days') AS d
CROSS APPLY (
    SELECT CAST(x.[key] AS INT) + 1 AS BlockNo, x.[value] AS BlockJson
    FROM OPENJSON(CASE WHEN d.[type] = 4 THEN d.[value] END) AS x
    WHERE x.[type] = 5
    UNION ALL
    SELECT 1, d.[value] WHERE d.[type] = 5
) AS b;
"""

DAY_VIEW_OLD = """
CREATE OR ALTER VIEW dbo.vw_SchScheduleDay
AS
SELECT
    a.id                    AS AssignmentId,
    a.employee_id           AS EmployeeId,
    e.EmployeeCode          AS EmployeeCode,
    pa.folio                AS ActionFolio,
    a.effective_start_date  AS EffectiveStart,
    a.effective_end_date    AS EffectiveEnd,
    d.[key]                 AS DayKey,
    JSON_VALUE(d.[value], '$.start')                     AS StartTime,
    JSON_VALUE(d.[value], '$.end')                       AS EndTime,
    TRY_CAST(JSON_VALUE(d.[value], '$.lunch_minutes') AS INT) AS LunchMinutes,
    TRY_CAST(JSON_VALUE(d.[value], '$.day_minutes') AS INT)   AS DayMinutes,
    TRY_CAST(JSON_VALUE(d.[value], '$.night_minutes') AS INT) AS NightMinutes
FROM dbo.sch_schedule_assignment AS a
JOIN hcm.Employee AS e ON e.EmployeeId = a.employee_id
LEFT JOIN dbo.pa_action AS pa ON pa.id = a.personnel_action_id
CROSS APPLY OPENJSON(a.definition, '$.days') AS d
WHERE d.[type] = 5;
"""

LUNCH_VIEW = """
CREATE OR ALTER VIEW dbo.vw_SchLunchRule
AS
SELECT
    r.id                    AS LunchRuleId,
    c.CountryCode           AS CountryCode,
    r.name                  AS RuleName,
    r.min_block_minutes     AS MinContinuousMinutes,
    r.lunch_minutes         AS LunchMinutes,
    r.enforcement           AS Enforcement,
    r.effective_start_date  AS EffectiveStart,
    r.effective_end_date    AS EffectiveEnd,
    r.is_active             AS IsActive
FROM dbo.sch_lunch_rule AS r
JOIN core.catCountry AS c ON c.CountryId = r.country_id;
"""

FORWARD = [
    "IF OBJECT_ID(N'dbo.FK_sch_lunch_rule_Country', N'F') IS NULL\n"
    "    ALTER TABLE dbo.sch_lunch_rule WITH CHECK ADD CONSTRAINT FK_sch_lunch_rule_Country FOREIGN KEY (country_id) REFERENCES core.catCountry (CountryId);",
    ASSIGNMENT_TRIGGER, PERIOD_TRIGGER, LUNCH_TRIGGER, ASSIGNMENT_VIEW, DAY_VIEW, LUNCH_VIEW,
]
REVERSE = [
    "IF OBJECT_ID(N'dbo.vw_SchLunchRule', N'V') IS NOT NULL DROP VIEW dbo.vw_SchLunchRule;",
    DAY_VIEW_OLD,
    "IF OBJECT_ID(N'dbo.TR_sch_lunch_rule_rules', N'TR') IS NOT NULL DROP TRIGGER dbo.TR_sch_lunch_rule_rules;",
    PERIOD_TRIGGER_OLD, ASSIGNMENT_TRIGGER_OLD,
    "IF OBJECT_ID(N'dbo.FK_sch_lunch_rule_Country', N'F') IS NOT NULL ALTER TABLE dbo.sch_lunch_rule DROP CONSTRAINT FK_sch_lunch_rule_Country;",
]


def seed(apps, schema_editor):
    Country = apps.get_model("common", "Country")
    LunchRule = apps.get_model("scheduling", "LunchRule")
    PayCycle = apps.get_model("scheduling", "PayCycle")
    PayPeriod = apps.get_model("scheduling", "PayPeriod")
    from apps.scheduling import engine

    sv = Country.objects.filter(country_code="SV").first()
    if not sv:
        return
    if not LunchRule.objects.filter(country_id=sv.country_id).exists():
        LunchRule.objects.create(
            country_id=sv.country_id, name="Almuerzo en jornada continua de 6 h o más", min_block_minutes=360,
            lunch_minutes=30, enforcement="WARN", effective_start_date=date(2026, 1, 1),
            legal_reference="Parámetro inicial de referencia (advertencia): valide umbral y duración con Legal / Planilla.",
        )
    if not PayCycle.objects.filter(code="SV_QUINCENAL_BPO").exists():
        cycle = PayCycle.objects.create(
            code="SV_QUINCENAL_BPO", name="El Salvador quincenal BPO (10–24 / 25–9)", country_id=sv.country_id,
            pay_frequency="BIWEEKLY", period_rule="HALF_MONTH", period_start_day=10, first_half_end_day=24,
            cutoff_lag_days=0, payment_lag_days=0, is_default=False, is_active=True,
            notes="Ejemplo de corte BPO que cruza de mes. No es el predeterminado: márquelo como tal (y desmarque "
                  "SV_QUINCENAL) si la operación usa este corte.",
        )
        rule = engine.CycleRule(period_rule="HALF_MONTH", first_half_end_day=24, period_start_day=10)
        for p in engine.generate_periods(rule, 2026):
            PayPeriod.objects.create(
                cycle=cycle, code=p["label"], period_start=p["period_start"], period_end=p["period_end"],
                cutoff_start=p["period_start"], cutoff_end=p["period_end"], payment_date=p["payment_date"],  # corte = periodo (sin anticipación)
            )


class Migration(migrations.Migration):
    dependencies = [("scheduling", "0005_phase10")]

    operations = [
        migrations.RunSQL(FORWARD, REVERSE),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
