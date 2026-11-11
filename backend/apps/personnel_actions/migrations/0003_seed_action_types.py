"""Tipos de AP de referencia (se ajustan en /admin/ › Acciones de personal).

* APH  Primera AP de asignación de horario (fundacional, se crea en el alta) — firma: RRHH.
* APH  Cambio de horario — firmas: WFM -> RRHH.
* APS  Ajuste salarial — visible solo con permisos de planilla; firmas: RRHH -> Administración.
En todos, quien envía la AP firma el primer paso si su rol corresponde (el Administrador puede firmar cualquier
paso). «Firmantes distintos» queda desactivado: actívelo cuando haya más de un firmante por rol.
"""

from django.db import migrations

SCHEDULE_HELP = "Entrada, salida y minutos de almuerzo por día; las horas diurnas y nocturnas se calculan con la regla de nocturnidad del país."
TYPES = [
    {
        "code": "AP_HORARIO_INICIAL", "name": "Primera AP de asignación de horario", "category": "SCHEDULE", "effect": "SCHEDULE",
        "folio_prefix": "APH", "is_initial_schedule": True, "creator_signs_first_step": True, "display_order": 10,
        "description": "AP fundacional del turno: se crea en el alta del colaborador con fecha efectiva = fecha de ingreso.",
        "attributes": [
            {"key": "horario", "label": "Horario semanal", "data_type": "SCHEDULE", "required": True, "display_order": 10, "help_text": SCHEDULE_HELP},
        ],
        "steps": [(1, "Autorización de Recursos Humanos", "HR")],
    },
    {
        "code": "AP_CAMBIO_HORARIO", "name": "Cambio de horario", "category": "SCHEDULE", "effect": "SCHEDULE",
        "folio_prefix": "APH", "creator_signs_first_step": True, "display_order": 20,
        "description": "Nuevo horario atómico por día a partir de la fecha efectiva (cierra el vigente el día anterior).",
        "attributes": [
            {"key": "motivo", "label": "Motivo del cambio", "data_type": "CHOICE", "required": True, "display_order": 10,
             "choices": ["Solicitud del colaborador", "Necesidad operativa", "Cambio de cuenta / LOB", "Ajuste por estudios", "Otro"]},
            {"key": "horario", "label": "Nuevo horario semanal", "data_type": "SCHEDULE", "required": True, "display_order": 20, "help_text": SCHEDULE_HELP},
        ],
        "steps": [(1, "Visto bueno de Workforce (WFM)", "WFM"), (2, "Autorización de Recursos Humanos", "HR")],
    },
    {
        "code": "AP_AJUSTE_SALARIAL", "name": "Ajuste salarial", "category": "COMPENSATION", "effect": "SALARY",
        "folio_prefix": "APS", "creator_signs_first_step": True, "display_order": 30,
        "view_permission": "payroll.view", "create_permission": "payroll.manage",
        "description": "Nuevo salario base desde la fecha efectiva (si es futura, se aplica ese día).",
        "attributes": [
            {"key": "tipo_ajuste", "label": "Tipo de ajuste", "data_type": "CHOICE", "required": True, "display_order": 10,
             "choices": ["Mérito", "Promoción", "Salario mínimo de ley", "Corrección", "Otro"]},
            {"key": "new_base_salary", "label": "Nuevo salario base", "data_type": "DECIMAL", "required": True, "display_order": 20,
             "min_value": "0.01", "help_text": "Monto mensual en la moneda del país."},
        ],
        "steps": [(1, "Autorización de Recursos Humanos", "HR"), (2, "Aprobación de Administración / Gerencia", "ADMIN")],
    },
]


def seed(apps, schema_editor):
    ActionType = apps.get_model("personnel_actions", "ActionType")
    Attribute = apps.get_model("personnel_actions", "ActionAttribute")
    Step = apps.get_model("personnel_actions", "ApprovalStep")
    for spec in TYPES:
        spec = dict(spec)
        attributes, steps = spec.pop("attributes"), spec.pop("steps")
        if ActionType.objects.filter(code=spec["code"]).exists():
            continue
        t = ActionType.objects.create(**spec)
        for a in attributes:
            Attribute.objects.create(action_type=t, **a)
        for order, label, role in steps:
            Step.objects.create(action_type=t, order=order, label=label, role=role)


class Migration(migrations.Migration):
    dependencies = [("personnel_actions", "0002_sql_integrity_and_view")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
