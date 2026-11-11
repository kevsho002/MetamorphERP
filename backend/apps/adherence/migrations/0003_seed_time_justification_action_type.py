"""Fase 16: tipo de AP «Justificación de tiempo» (catálogo de referencia).

Respalda las justificaciones de adherencia: permiso, cita médica, misión oficial, falla de sistema o tiempo extra
autorizado. Al aprobarse no cambia horario ni salario: WFM registra la ventana exacta en «Justificaciones (AP)» con su
folio y ese tiempo deja de marcarse como Out of Adherence / Unpaid Excess Login. Firmas: WFM -> RRHH. Se ajusta en /admin/.
"""

from django.db import migrations


def seed(apps, schema_editor):
    ActionType = apps.get_model("personnel_actions", "ActionType")
    Attribute = apps.get_model("personnel_actions", "ActionAttribute")
    Step = apps.get_model("personnel_actions", "ApprovalStep")
    if ActionType.objects.filter(code="AP_JUSTIFICACION_TIEMPO").exists():
        return
    t = ActionType.objects.create(
        code="AP_JUSTIFICACION_TIEMPO", name="Justificación de tiempo (permiso / tiempo extra autorizado)", category="OTHER",
        effect="NONE", folio_prefix="APJ", creator_signs_first_step=True, display_order=40,
        description="Justifica tiempo fuera del plan de WFM: no se marca como Out of Adherence ni Unpaid Excess Login.",
    )
    for a in [
        {"key": "motivo", "label": "Motivo", "data_type": "CHOICE", "required": True, "display_order": 10,
         "choices": ["Permiso personal", "Cita médica / incapacidad", "Misión oficial", "Falla de sistema", "Tiempo extra autorizado", "Otro"]},
        {"key": "fecha", "label": "Fecha", "data_type": "DATE", "required": True, "display_order": 20},
        {"key": "horario", "label": "Horas (desde – hasta)", "data_type": "TEXT", "required": True, "display_order": 30,
         "help_text": "Ej.: 08:00 – 10:30. WFM registra la ventana exacta al aplicar la justificación."},
        {"key": "pagado", "label": "Tiempo pagado", "data_type": "BOOLEAN", "required": False, "display_order": 40},
    ]:
        Attribute.objects.create(action_type=t, **a)
    for order, label, role in [(1, "Visto bueno de Workforce (WFM)", "WFM"), (2, "Autorización de Recursos Humanos", "HR")]:
        Step.objects.create(action_type=t, order=order, label=label, role=role)


class Migration(migrations.Migration):
    dependencies = [("adherence", "0002_sql_integrity_views_and_seed"), ("personnel_actions", "0005_seed_additional_schedule_type")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
