"""Parámetros de referencia (se ajustan en /admin/ › Horarios, tiempo y cortes).

* Nocturnidad El Salvador: 19:00–06:00 con 25 % de recargo (Código de Trabajo, arts. 161 y 168).
  Los demás países no se siembran: se configuran con su norma vigente.
* Turnos de ejemplo: diurno L-V 08:00–17:00 (60 min de almuerzo) y nocturno L-V 22:00–06:00
  (30 min de almuerzo, cruza la medianoche).
* Ciclos SV quincenal (1–15 / 16–fin) y mensual, sin corte anticipado (cutoff_lag_days = 0) y con los
  periodos de 2026 generados. Ajuste el corte interno según la operación y genere los años siguientes.
Si los registros ya existen (por código), no se modifican.
"""

from datetime import date

from django.db import migrations

SHIFTS = [
    {
        "code": "DIURNO_LV_08_17", "name": "Diurno lunes a viernes 08:00–17:00",
        "description": "Ejemplo de referencia: 8 h netas diarias con 60 min de almuerzo.",
        "definition": {
            "days": {**{d: {"start": "08:00", "end": "17:00", "lunch_minutes": 60} for d in ("mon", "tue", "wed", "thu", "fri")},
                     "sat": None, "sun": None},
            "lunch_allocation": "PROPORTIONAL",
        },
        "weekly_minutes": 5 * 480,
    },
    {
        "code": "NOCTURNO_LV_22_06", "name": "Nocturno lunes a viernes 22:00–06:00",
        "description": "Ejemplo de referencia: cruza la medianoche; 30 min de almuerzo repartidos entre ambas fechas.",
        "definition": {
            "days": {**{d: {"start": "22:00", "end": "06:00", "lunch_minutes": 30} for d in ("mon", "tue", "wed", "thu", "fri")},
                     "sat": None, "sun": None},
            "lunch_allocation": "PROPORTIONAL",
        },
        "weekly_minutes": 5 * 450,
    },
]


def seed(apps, schema_editor):
    Country = apps.get_model("common", "Country")
    NightRule = apps.get_model("scheduling", "NightRule")
    Shift = apps.get_model("scheduling", "Shift")
    PayCycle = apps.get_model("scheduling", "PayCycle")
    PayPeriod = apps.get_model("scheduling", "PayPeriod")
    from apps.scheduling import engine

    sv = Country.objects.filter(country_code="SV").first()
    if sv and not NightRule.objects.filter(country_id=sv.country_id).exists():
        NightRule.objects.create(
            country_id=sv.country_id, name="Jornada nocturna El Salvador", start_time="19:00", end_time="06:00",
            surcharge_percent="25.00", effective_start_date=date(2000, 1, 1),
            legal_reference="Código de Trabajo de El Salvador: art. 161 (horas nocturnas de 19:00 a 6:00) y "
                            "art. 168 (recargo de al menos 25 % sobre el salario diurno).",
        )
    for spec in SHIFTS:
        if not Shift.objects.filter(code=spec["code"]).exists():
            Shift.objects.create(**spec)
    if not sv:
        return
    cycles = [
        ("SV_QUINCENAL", "El Salvador quincenal", "BIWEEKLY", "HALF_MONTH"),
        ("SV_MENSUAL", "El Salvador mensual", "MONTHLY", "MONTH"),
    ]
    for code, name, frequency, rule in cycles:
        if PayCycle.objects.filter(code=code).exists():
            continue
        cycle = PayCycle.objects.create(
            code=code, name=name, country_id=sv.country_id, pay_frequency=frequency, period_rule=rule,
            first_half_end_day=15, cutoff_lag_days=0, payment_lag_days=0, is_default=True, is_active=True,
            notes="Referencia: ajuste el corte interno (días antes del fin) según la operación.",
        )
        for p in engine.generate_periods(engine.CycleRule(period_rule=rule), 2026):
            PayPeriod.objects.create(
                cycle=cycle, code=p["label"], period_start=p["period_start"], period_end=p["period_end"],
                cutoff_start=p["cutoff_start"], cutoff_end=p["cutoff_end"], payment_date=p["payment_date"],
            )


class Migration(migrations.Migration):
    dependencies = [("scheduling", "0002_sql_integrity_and_reporting_views")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
