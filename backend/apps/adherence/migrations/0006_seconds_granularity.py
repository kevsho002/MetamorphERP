"""Fase 18: granularidad al SEGUNDO en la planificación y la adherencia.

* adh_activity_type.default_minutes → default_seconds (duración sugerida exacta).
* adh_grid_setting.snap_minutes → snap_seconds (ajuste al soltar desde 1 s).
* SQL Server: los segmentos, justificaciones y desviaciones guardan SEGUNDOS ENTEROS (sin fracciones: el cálculo es al
  segundo en la aplicación y en los reportes) y las vistas calculan con DATEDIFF(SECOND): DATEDIFF(MINUTE) cuenta
  fronteras de minuto y redondeaba (10:00:50–10:01:10 daba 1 minuto).
"""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models
from django.db.models import Q


def forward(apps, schema_editor):
    ActivityType = apps.get_model("adherence", "ActivityType")
    for a in ActivityType.objects.exclude(default_minutes__isnull=True):
        a.default_seconds = a.default_minutes * 60
        a.save(update_fields=["default_seconds"])
    GridSetting = apps.get_model("adherence", "GridSetting")
    for s in GridSetting.objects.all():
        s.snap_seconds = s.snap_minutes * 60
        s.save(update_fields=["snap_seconds"])


def backward(apps, schema_editor):
    ActivityType = apps.get_model("adherence", "ActivityType")
    for a in ActivityType.objects.exclude(default_seconds__isnull=True):
        a.default_minutes = max(1, round(a.default_seconds / 60))
        a.save(update_fields=["default_minutes"])
    GridSetting = apps.get_model("adherence", "GridSetting")
    for s in GridSetting.objects.all():
        s.snap_minutes = min((1, 5, 15, 30), key=lambda m: abs(m * 60 - s.snap_seconds))
        s.save(update_fields=["snap_minutes"])


_WHOLE = [("adh_schedule_segment", "segment"), ("adh_exception", "exception"), ("adh_deviation", "deviation")]

WHOLE_SECONDS = "\n".join(
    f"IF OBJECT_ID(N'dbo.ck_adh_{n}_whole_seconds', N'C') IS NULL\n"
    f"    ALTER TABLE dbo.{t} WITH CHECK ADD CONSTRAINT ck_adh_{n}_whole_seconds\n"
    f"        CHECK (DATEPART(NANOSECOND, start_at) = 0 AND DATEPART(NANOSECOND, end_at) = 0);"
    for t, n in _WHOLE
)
DROP_WHOLE_SECONDS = "\n".join(
    f"IF OBJECT_ID(N'dbo.ck_adh_{n}_whole_seconds', N'C') IS NOT NULL ALTER TABLE dbo.{t} DROP CONSTRAINT ck_adh_{n}_whole_seconds;"
    for t, n in _WHOLE
)

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
    DATEDIFF(SECOND, s.start_at, s.end_at)                              AS DurationSeconds,
    CAST(DATEDIFF(SECOND, s.start_at, s.end_at) / 60.0 AS decimal(9, 4)) AS Minutes,
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

OLD_SEGMENT_VIEW = SEGMENT_VIEW.replace(
    "    DATEDIFF(SECOND, s.start_at, s.end_at)                              AS DurationSeconds,\n"
    "    CAST(DATEDIFF(SECOND, s.start_at, s.end_at) / 60.0 AS decimal(9, 4)) AS Minutes,\n",
    "    DATEDIFF(MINUTE, s.start_at, s.end_at) AS Minutes,\n",
)

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
    d.computed_at       AS ComputedAtUtc,
    d.scheduled_seconds                     AS ScheduledSeconds,
    d.in_adherence_seconds                  AS InAdherenceSeconds,
    d.out_of_adherence_seconds              AS OutOfAdherenceSeconds,
    d.justified_seconds                     AS JustifiedSeconds,
    d.logged_seconds                        AS LoggedSeconds,
    d.paid_valid_seconds                    AS PaidValidSeconds,
    d.billable_seconds                      AS BillableSeconds,
    d.primary_work_seconds                  AS PrimaryWorkSeconds,
    d.secondary_paid_seconds                AS SecondaryPaidSeconds,
    d.unpaid_excess_seconds                 AS UnpaidExcessLoginSeconds
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


def _old_day_view() -> str:
    lines = DAY_VIEW.splitlines()
    out = [ln for ln in lines if not (ln.strip().startswith("d.") and ln.strip().endswith(("Seconds,", "Seconds")))]
    return "\n".join(out).replace("d.computed_at       AS ComputedAtUtc,", "d.computed_at       AS ComputedAtUtc")


class Migration(migrations.Migration):
    dependencies = [("adherence", "0005_seed_icons_and_grid_setting")]

    operations = [
        migrations.AddField(
            model_name="activitytype", name="default_seconds",
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name="duración sugerida (s)",
                                              help_text="Segundos (60 = 1 min; máx. 12 h).",
                                              validators=[MinValueValidator(60), MaxValueValidator(43200)]),
        ),
        migrations.AddField(
            model_name="gridsetting", name="snap_seconds",
            field=models.PositiveSmallIntegerField(
                choices=[(1, "1 s"), (15, "15 s"), (30, "30 s"), (60, "1 min"), (300, "5 min"), (900, "15 min"), (1800, "30 min")],
                default=300, verbose_name="ajuste al soltar (s)"),
        ),
        migrations.RunPython(forward, backward),
        migrations.RemoveConstraint(model_name="gridsetting", name="ck_adh_grid_snap"),
        migrations.RemoveField(model_name="activitytype", name="default_minutes"),
        migrations.RemoveField(model_name="gridsetting", name="snap_minutes"),
        migrations.AddConstraint(
            model_name="gridsetting",
            constraint=models.CheckConstraint(condition=Q(snap_seconds__in=[1, 15, 30, 60, 300, 900, 1800]),
                                              name="ck_adh_grid_snap_seconds"),
        ),
        migrations.RunSQL([WHOLE_SECONDS, SEGMENT_VIEW, DAY_VIEW], [DROP_WHOLE_SECONDS, OLD_SEGMENT_VIEW, _old_day_view()]),
    ]
