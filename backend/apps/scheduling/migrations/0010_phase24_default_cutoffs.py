"""Fase 24 — Los ciclos quincenales PREDETERMINADOS cuentan la asistencia en los cortes internos del 25 al 9 y del 10 al
24 (se pagan en la quincena 1–15 y 16–fin que contiene su cierre), no del 1 al 15.

Hasta la Fase 23 solo el ciclo de ejemplo SV_QUINCENAL_BPO tenía ventanas propias; el predeterminado (SV_QUINCENAL)
derivaba el corte del periodo de pago, así que la planilla contaba horas, actuals y cumplimiento del 1 al 15. Esta
migración fija la regla (inicio 10, fin de la primera ventana 24) en los ciclos quincenales predeterminados que no
tenían ventanas propias y realinea sus cortes ABIERTOS (los cerrados, o pagados en una planilla cerrada, no se tocan).
El devengo (periodos de pago y fechas de pago) no cambia.
"""

from django.db import migrations

CUTOFF_START_DAY, CUTOFF_FIRST_END_DAY = 10, 24


def forwards(apps, schema_editor):
    if schema_editor.connection.alias != "default":
        return
    from apps.common.schemas import tables_where_they_are

    # Fase 25: usa los modelos actuales; mientras sus tablas sigan en dbo (antes de system.0015) se apuntan ahí.
    with tables_where_they_are(schema_editor.connection):
        _realign()


def _realign():
    from apps.scheduling.models import PayCycle
    from apps.scheduling.services import realign_cutoffs

    cycles = PayCycle.objects.filter(is_default=True, is_active=True, pay_frequency="BIWEEKLY", period_rule="HALF_MONTH",
                                     cutoff_start_day__isnull=True)
    for cycle in cycles:
        PayCycle.objects.filter(pk=cycle.pk).update(cutoff_start_day=CUTOFF_START_DAY, cutoff_first_end_day=CUTOFF_FIRST_END_DAY,
                                                    cutoff_lag_days=0)
        cycle.refresh_from_db()
        realign_cutoffs(cycle, audit=False)


class Migration(migrations.Migration):
    dependencies = [
        ("scheduling", "0009_phase11_sql_rules_and_views"),
        ("payroll", "0004_phase21_sql_rules_and_seed"),
        ("system", "0012_phase23_preferences_and_ap_scope"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
