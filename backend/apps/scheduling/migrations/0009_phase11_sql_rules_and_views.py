"""Fase 11 — reglas de SQL Server independientes para periodos de pago y cortes internos de asistencia.

* TR_sch_pay_period_rules (periodos de PAGO, 1–15 / 16–fin):
      50043  colisión: el periodo se traslapa con otro periodo de pago del ciclo
      50045  hueco o colisión: el periodo no inicia el día siguiente al fin del periodo anterior
      50048  un corte mapeado a este periodo quedaría con su cierre fuera de él
* TR_sch_attendance_cutoff_rules (cortes internos, pueden cruzar de mes: 25–9 / 10–24):
      50044  colisión: la ventana se traslapa con otro corte del ciclo
      50046  hueco o colisión: la ventana no inicia el día siguiente al cierre del corte anterior
      50048  el periodo de pago mapeado es de otro ciclo o no contiene la fecha de cierre del corte
      50049  las fechas de un corte CERRADO no se modifican (se reabre primero)
  Cerrar / reabrir un corte no cambia fechas: no dispara las reglas de continuidad.
* Vistas: vw_SchPayPeriod (periodo + resumen de sus cortes), vw_SchAttendanceCutoff (nueva),
  vw_SchTimeByOccurrenceDate (corte y periodo de pago de cada día) y vw_SchPayrollHours (nueva: horas por
  empleado y corte, con el periodo de pago al que se mapean; base del cálculo de planilla).
* Semilla: el ciclo de ejemplo SV_QUINCENAL_BPO (Fase 10) pasa al modelo desacoplado si nadie cerró sus cortes:
  pago 1–15 / 16–fin y asistencia 25–9 / 10–24.
"""

from django.db import migrations

PERIOD_TRIGGER = """
CREATE OR ALTER TRIGGER dbo.TR_sch_pay_period_rules
ON dbo.sch_pay_period
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT (UPDATE(period_start) OR UPDATE(period_end) OR UPDATE(cycle_id))
        RETURN;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.sch_pay_period AS p
          ON p.cycle_id = i.cycle_id AND p.id <> i.id
         AND p.period_start <= i.period_end AND i.period_start <= p.period_end
    )
        THROW 50043, N'Periodos de pago: el periodo colisiona con otro periodo de pago del mismo ciclo.', 1;
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
        THROW 50045, N'Periodos de pago: el periodo debe iniciar el día siguiente al fin del periodo anterior (sin huecos ni colisiones).', 1;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.sch_attendance_cutoff AS c ON c.pay_period_id = i.id
        WHERE c.cycle_id <> i.cycle_id OR c.cutoff_end < i.period_start OR c.cutoff_end > i.period_end
    )
        THROW 50048, N'Periodos de pago: un corte de asistencia mapeado a este periodo quedaría con su cierre fuera de él.', 1;
END
"""

CUTOFF_TRIGGER = """
CREATE OR ALTER TRIGGER dbo.TR_sch_attendance_cutoff_rules
ON dbo.sch_attendance_cutoff
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT (UPDATE(cutoff_start) OR UPDATE(cutoff_end) OR UPDATE(cycle_id) OR UPDATE(pay_period_id))
        RETURN;  -- cerrar / reabrir no cambia fechas
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN deleted AS d ON d.id = i.id
        WHERE d.status = N'CLOSED' AND i.status = N'CLOSED'
          AND (d.cutoff_start <> i.cutoff_start OR d.cutoff_end <> i.cutoff_end OR d.pay_period_id <> i.pay_period_id)
    )
        THROW 50049, N'Cortes de asistencia: el corte está cerrado; reábralo antes de modificar sus fechas.', 1;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.sch_attendance_cutoff AS c
          ON c.cycle_id = i.cycle_id AND c.id <> i.id
         AND c.cutoff_start <= i.cutoff_end AND i.cutoff_start <= c.cutoff_end
    )
        THROW 50044, N'Cortes de asistencia: la ventana colisiona con otro corte del mismo ciclo.', 1;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        CROSS APPLY (
            SELECT TOP (1) c.cutoff_end
            FROM dbo.sch_attendance_cutoff AS c
            WHERE c.cycle_id = i.cycle_id AND c.id <> i.id AND c.cutoff_start < i.cutoff_start
            ORDER BY c.cutoff_start DESC
        ) AS prev
        WHERE prev.cutoff_end <> DATEADD(DAY, -1, i.cutoff_start)
    )
        THROW 50046, N'Cortes de asistencia: la ventana debe iniciar el día siguiente al cierre del corte anterior (sin huecos ni colisiones).', 1;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.sch_pay_period AS p ON p.id = i.pay_period_id
        WHERE p.cycle_id <> i.cycle_id OR i.cutoff_end < p.period_start OR i.cutoff_end > p.period_end
    )
        THROW 50048, N'Cortes de asistencia: el corte se mapea al periodo de pago de su ciclo que contiene su fecha de cierre.', 1;
END
"""

PAY_PERIOD_VIEW = """
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
    p.payment_date      AS PaymentDate,
    ISNULL(x.CutoffCount, 0) AS CutoffCount,
    x.CutoffStart       AS CutoffStart,
    x.CutoffEnd         AS CutoffEnd,
    ISNULL(x.ClosedCutoffs, 0) AS ClosedCutoffs,
    CASE WHEN ISNULL(x.CutoffCount, 0) = 0 THEN N'NO_CUTOFF'
         WHEN x.ClosedCutoffs = x.CutoffCount THEN N'CLOSED'
         ELSE N'OPEN' END AS AttendanceStatus
FROM dbo.sch_pay_period AS p
JOIN dbo.sch_pay_cycle AS c ON c.id = p.cycle_id
JOIN core.catCountry AS cc ON cc.CountryId = c.country_id
OUTER APPLY (
    SELECT COUNT(*) AS CutoffCount, MIN(a.cutoff_start) AS CutoffStart, MAX(a.cutoff_end) AS CutoffEnd,
           SUM(CASE WHEN a.status = N'CLOSED' THEN 1 ELSE 0 END) AS ClosedCutoffs
    FROM dbo.sch_attendance_cutoff AS a
    WHERE a.pay_period_id = p.id
) AS x;
"""

PAY_PERIOD_VIEW_OLD = """
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
    p.payment_date      AS PaymentDate
FROM dbo.sch_pay_period AS p
JOIN dbo.sch_pay_cycle AS c ON c.id = p.cycle_id
JOIN core.catCountry AS cc ON cc.CountryId = c.country_id;
"""

CUTOFF_VIEW = """
CREATE OR ALTER VIEW dbo.vw_SchAttendanceCutoff
AS
SELECT
    a.id                AS CutoffId,
    c.code              AS CycleCode,
    c.name              AS CycleName,
    cc.CountryCode      AS CountryCode,
    c.pay_frequency     AS PayFrequency,
    c.is_default        AS IsDefaultCycle,
    a.code              AS CutoffCode,
    a.cutoff_start      AS CutoffStart,
    a.cutoff_end        AS CutoffEnd,
    a.status            AS CutoffStatus,
    a.closed_at         AS ClosedAt,
    p.id                AS PayPeriodId,
    p.code              AS PayPeriodCode,
    p.period_start      AS PayPeriodStart,
    p.period_end        AS PayPeriodEnd,
    p.payment_date      AS PaymentDate
FROM dbo.sch_attendance_cutoff AS a
JOIN dbo.sch_pay_cycle AS c ON c.id = a.cycle_id
JOIN core.catCountry AS cc ON cc.CountryId = c.country_id
JOIN dbo.sch_pay_period AS p ON p.id = a.pay_period_id;
"""

_TIME_SELECT = """
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
    pc.code                 AS CycleCode,
    ac.id                   AS CutoffId,
    ac.code                 AS CutoffCode,
    ac.status               AS CutoffStatus,
    pp.id                   AS PayPeriodId,
    pp.code                 AS PayPeriodCode,
    pp.payment_date         AS PaymentDate,
    ac.status               AS PayPeriodStatus  -- compatibilidad (Fase 8): estado del CORTE de asistencia
FROM dbo.sch_time_record_day AS d
JOIN dbo.sch_time_record AS r ON r.id = d.record_id
JOIN hcm.Employee AS e ON e.EmployeeId = d.employee_id
JOIN core.catCountry AS c ON c.CountryId = e.CountryId
LEFT JOIN dbo.sch_night_rule AS nr ON nr.id = d.night_rule_id
LEFT JOIN dbo.sch_pay_cycle AS pc
       ON pc.country_id = e.CountryId AND pc.pay_frequency = e.PayFrequency AND pc.is_default = 1 AND pc.is_active = 1
LEFT JOIN dbo.sch_attendance_cutoff AS ac
       ON ac.cycle_id = pc.id AND d.occurrence_date BETWEEN ac.cutoff_start AND ac.cutoff_end
LEFT JOIN dbo.sch_pay_period AS pp ON pp.id = ac.pay_period_id
"""

TIME_VIEW = "CREATE OR ALTER VIEW dbo.vw_SchTimeByOccurrenceDate\nAS" + _TIME_SELECT + ";"

PAYROLL_HOURS_VIEW = """
CREATE OR ALTER VIEW dbo.vw_SchPayrollHours
AS
SELECT
    t.CycleCode,
    t.PayPeriodId,
    t.PayPeriodCode,
    pp.period_start         AS PayPeriodStart,
    pp.period_end           AS PayPeriodEnd,
    pp.payment_date         AS PaymentDate,
    t.CutoffId,
    t.CutoffCode,
    ac.cutoff_start         AS CutoffStart,
    ac.cutoff_end           AS CutoffEnd,
    t.CutoffStatus,
    t.EmployeeId,
    t.EmployeeCode,
    t.FullName,
    t.CountryCode,
    SUM(t.WorkedMinutes)    AS WorkedMinutes,
    SUM(t.NightMinutes)     AS NightMinutes,
    COUNT(DISTINCT t.OccurrenceDate) AS DaysWithTime
FROM dbo.vw_SchTimeByOccurrenceDate AS t
JOIN dbo.sch_attendance_cutoff AS ac ON ac.id = t.CutoffId
JOIN dbo.sch_pay_period AS pp ON pp.id = t.PayPeriodId
GROUP BY t.CycleCode, t.PayPeriodId, t.PayPeriodCode, pp.period_start, pp.period_end, pp.payment_date, t.CutoffId,
         t.CutoffCode, ac.cutoff_start, ac.cutoff_end, t.CutoffStatus, t.EmployeeId, t.EmployeeCode, t.FullName, t.CountryCode;
"""

FORWARD = [PERIOD_TRIGGER, CUTOFF_TRIGGER, PAY_PERIOD_VIEW, CUTOFF_VIEW, TIME_VIEW, PAYROLL_HOURS_VIEW]
REVERSE = [
    "IF OBJECT_ID(N'dbo.vw_SchPayrollHours', N'V') IS NOT NULL DROP VIEW dbo.vw_SchPayrollHours;",
    "IF OBJECT_ID(N'dbo.vw_SchAttendanceCutoff', N'V') IS NOT NULL DROP VIEW dbo.vw_SchAttendanceCutoff;",
    PAY_PERIOD_VIEW_OLD,
    "IF OBJECT_ID(N'dbo.TR_sch_attendance_cutoff_rules', N'TR') IS NOT NULL DROP TRIGGER dbo.TR_sch_attendance_cutoff_rules;",
    "IF OBJECT_ID(N'dbo.TR_sch_pay_period_rules', N'TR') IS NOT NULL DROP TRIGGER dbo.TR_sch_pay_period_rules;",
]


def convert_bpo_example(apps, schema_editor):
    """SV_QUINCENAL_BPO (ejemplo de la Fase 10, no predeterminado) pasa al modelo desacoplado: la quincena de pago
    vuelve a ser 1–15 / 16–fin y la asistencia se corta del 25 al 9 y del 10 al 24. Solo si ningún corte está cerrado."""
    from apps.scheduling import engine

    PayCycle = apps.get_model("scheduling", "PayCycle")
    PayPeriod = apps.get_model("scheduling", "PayPeriod")
    AttendanceCutoff = apps.get_model("scheduling", "AttendanceCutoff")
    cycle = PayCycle.objects.filter(code="SV_QUINCENAL_BPO").first()
    if not cycle or cycle.cutoff_start_day or AttendanceCutoff.objects.filter(cycle=cycle, status="CLOSED").exists():
        return
    years = sorted({p.period_start.year for p in PayPeriod.objects.filter(cycle=cycle)}) or [2026]
    AttendanceCutoff.objects.filter(cycle=cycle).delete()
    PayPeriod.objects.filter(cycle=cycle).delete()
    cycle.name = "El Salvador quincenal BPO (pago 1–15 / 16–fin; asistencia 25–9 / 10–24)"
    cycle.period_start_day, cycle.first_half_end_day = 1, 15
    cycle.cutoff_start_day, cycle.cutoff_first_end_day, cycle.cutoff_lag_days = 10, 24, 0
    cycle.notes = ("Ejemplo de corte BPO desacoplado: se paga por quincena calendario y las horas se cuentan del 25 al 9 y "
                   "del 10 al 24. No es el predeterminado: márquelo como tal (y desmarque SV_QUINCENAL) si la operación lo usa.")
    cycle.save()
    rule = engine.CycleRule(period_rule="HALF_MONTH", first_half_end_day=15, period_start_day=1,
                            cutoff_start_day=10, cutoff_first_end_day=24, payment_lag_days=cycle.payment_lag_days)
    periods = [p for y in years for p in engine.generate_periods(rule, y)]
    by_label = {}
    for p in periods:
        by_label[p["label"]] = PayPeriod.objects.create(
            cycle=cycle, code=p["label"], period_start=p["period_start"], period_end=p["period_end"], payment_date=p["payment_date"])
    for w in engine.cutoff_windows(rule, periods):
        label = w["period"]["label"]
        AttendanceCutoff.objects.create(cycle=cycle, pay_period=by_label[label], code=f"C-{label}",
                                        cutoff_start=w["cutoff_start"], cutoff_end=w["cutoff_end"])


class Migration(migrations.Migration):
    dependencies = [("scheduling", "0008_phase11_drop_period_cutoff")]

    operations = [
        migrations.RunSQL(FORWARD, REVERSE),
        migrations.RunPython(convert_bpo_example, migrations.RunPython.noop),
    ]
