"""Fase 22: retiro del módulo mock «Asistencias y downtimes» (esquema wfm, sin datos operativos).

La misma limpieza está en database/scripts/097_drop_wfm_attendance_mock.sql para despliegues con deploy.ps1.
"""

from django.db import migrations

TABLES = ["AttendanceDowntime", "Attendance", "IngestionBatchError", "IngestionBatch", "DowntimeCodeMap",
          "IngestionFieldMap", "catDowntimeType", "catIngestionSource"]


def drop(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"IF OBJECT_ID(N'wfm.{table}', N'U') IS NOT NULL DROP TABLE wfm.[{table}];")
        cursor.execute(
            "IF SCHEMA_ID(N'wfm') IS NOT NULL AND NOT EXISTS (SELECT 1 FROM sys.objects WHERE schema_id = SCHEMA_ID(N'wfm')) "
            "EXEC (N'DROP SCHEMA wfm;');"
        )


class Migration(migrations.Migration):
    dependencies = [("system", "0008_alter_auditevent_category")]

    operations = [migrations.RunPython(drop, migrations.RunPython.noop)]
