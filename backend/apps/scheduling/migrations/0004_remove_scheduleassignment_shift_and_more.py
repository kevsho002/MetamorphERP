"""Fase 9: se eliminan los turnos predefinidos (sch_shift).

El horario de cada empleado es ATÓMICO por día y lo crea una Acción de Personal aprobada: la asignación guarda su
propio JSON (entrada, salida, almuerzo, horas diurnas y nocturnas por día) y la AP que la originó.
Las asignaciones existentes (si las hubiera) conservan el horario de su turno copiándolo antes de borrar sch_shift.
La vista dbo.vw_SchScheduleAssignment se rehace con el folio de la AP.
"""

import django.db.models.deletion
from django.db import migrations, models

DROP_VIEW = "IF OBJECT_ID(N'dbo.vw_SchScheduleAssignment', N'V') IS NOT NULL DROP VIEW dbo.vw_SchScheduleAssignment;"

NEW_VIEW = """
CREATE OR ALTER VIEW dbo.vw_SchScheduleAssignment
AS
SELECT
    a.id                    AS AssignmentId,
    e.EmployeeId            AS EmployeeId,
    e.EmployeeCode          AS EmployeeCode,
    CONCAT_WS(N' ', e.FirstName, e.MiddleName, e.LastName, e.SecondLastName) AS FullName,
    c.CountryCode           AS CountryCode,
    e.EmploymentStatus      AS EmploymentStatus,
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

# Horario por día de la semana con su desglose diurno / nocturno (formato AP), una fila por día.
DAY_VIEW = """
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
WHERE d.[type] = 5;  -- objeto: día laboral (null = descanso)
"""


def copy_shift_definitions(apps, schema_editor):
    Assignment = apps.get_model("scheduling", "ScheduleAssignment")
    for a in Assignment.objects.select_related("shift"):
        a.definition = a.shift.definition
        a.weekly_minutes = a.shift.weekly_minutes
        a.save(update_fields=["definition", "weekly_minutes"])


class Migration(migrations.Migration):
    dependencies = [
        ("personnel_actions", "0001_initial"),
        ("scheduling", "0003_seed_reference_parameters"),
    ]

    operations = [
        migrations.RunSQL(DROP_VIEW, migrations.RunSQL.noop),
        migrations.AddField(
            model_name="scheduleassignment",
            name="definition",
            field=models.JSONField(null=True, verbose_name="horario por día (JSON)"),
        ),
        migrations.AddField(
            model_name="scheduleassignment",
            name="weekly_minutes",
            field=models.PositiveIntegerField(default=0, verbose_name="minutos programados por semana"),
        ),
        migrations.AddField(
            model_name="scheduleassignment",
            name="personnel_action",
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="schedule_assignment",
                                       to="personnel_actions.personnelaction", verbose_name="acción de personal"),
        ),
        migrations.RunPython(copy_shift_definitions, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="scheduleassignment",
            name="definition",
            field=models.JSONField(verbose_name="horario por día (JSON)"),
        ),
        migrations.RemoveField(model_name="scheduleassignment", name="shift"),
        migrations.AlterModelOptions(
            name="scheduleassignment",
            options={"ordering": ["employee_id", "-effective_start_date"], "verbose_name": "horario vigente",
                     "verbose_name_plural": "horarios vigentes (por AP)"},
        ),
        migrations.DeleteModel(name="Shift"),
        migrations.RunSQL(
            [
                """
IF OBJECT_ID(N'dbo.ck_sch_assign_definition_json', N'C') IS NULL
    ALTER TABLE dbo.sch_schedule_assignment WITH CHECK ADD CONSTRAINT ck_sch_assign_definition_json
        CHECK (ISJSON(definition) = 1 AND JSON_QUERY(definition, '$.days') IS NOT NULL);
""",
                NEW_VIEW,
                DAY_VIEW,
            ],
            [
                "IF OBJECT_ID(N'dbo.vw_SchScheduleDay', N'V') IS NOT NULL DROP VIEW dbo.vw_SchScheduleDay;",
                DROP_VIEW,
                "IF OBJECT_ID(N'dbo.ck_sch_assign_definition_json', N'C') IS NOT NULL ALTER TABLE dbo.sch_schedule_assignment DROP CONSTRAINT ck_sch_assign_definition_json;",
            ],
        ),
    ]
