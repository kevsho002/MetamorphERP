"""Fase 10: tipo de AP «Asignación adicional de horario» (varias AP el mismo día: turno partido o doble asignación).

Se suma al horario principal entre la fecha efectiva y «vigente_hasta»; sus bloques no pueden pedir las mismas
horas que otra asignación. Firmas: WFM -> RRHH (como el cambio de horario). Se ajusta en /admin/.
"""

from django.db import migrations

SCHEDULE_HELP = ("Bloques por día (entrada, salida y almuerzo opcional) que se SUMAN al horario principal; las horas diurnas y "
                 "nocturnas se calculan con la regla de nocturnidad del país.")


def seed(apps, schema_editor):
    ActionType = apps.get_model("personnel_actions", "ActionType")
    Attribute = apps.get_model("personnel_actions", "ActionAttribute")
    Step = apps.get_model("personnel_actions", "ApprovalStep")
    if ActionType.objects.filter(code="AP_HORARIO_ADICIONAL").exists():
        return
    t = ActionType.objects.create(
        code="AP_HORARIO_ADICIONAL", name="Asignación adicional de horario (turno partido / doble)", category="SCHEDULE",
        effect="SCHEDULE", schedule_mode="ADDITIONAL", folio_prefix="APH", creator_signs_first_step=True, display_order=25,
        description="Bloques de horario adicionales al principal (otra campaña, refuerzo, turno partido) hasta una fecha de fin.",
    )
    for a in [
        {"key": "motivo", "label": "Motivo de la asignación adicional", "data_type": "CHOICE", "required": True, "display_order": 10,
         "choices": ["Turno partido", "Doble asignación / otra campaña", "Refuerzo operativo", "Capacitación", "Otro"]},
        {"key": "horario", "label": "Horario adicional", "data_type": "SCHEDULE", "required": True, "display_order": 20, "help_text": SCHEDULE_HELP},
        {"key": "vigente_hasta", "label": "Vigente hasta", "data_type": "DATE", "required": True, "display_order": 30,
         "help_text": "Último día de la asignación adicional (incluido)."},
    ]:
        Attribute.objects.create(action_type=t, **a)
    for order, label, role in [(1, "Visto bueno de Workforce (WFM)", "WFM"), (2, "Autorización de Recursos Humanos", "HR")]:
        Step.objects.create(action_type=t, order=order, label=label, role=role)


class Migration(migrations.Migration):
    dependencies = [("personnel_actions", "0004_phase10")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
