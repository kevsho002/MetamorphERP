"""Fase 22: justificaciones y permisos en el módulo regular de AP, y roster automático.

* Atributos del roster: Puesto (job_title) y Tipo de contrato (contract_type, como la columna «Contract Type» del
  Optimum ES Payroll Hours: define las retenciones de ley).
* «Justificación de tiempo» pasa a tener efecto JUSTIFY: hora desde / hasta y actividad opcional (sub-segmento del Time
  Utilization). Al aprobarse justifica la ventana en la adherencia y coloca el segmento en la grilla; ya no se registra
  aparte en WFM. Los campos de texto anteriores (fecha / horario) se desactivan (las AP históricas los conservan).
* Permiso con goce / sin goce (efecto LEAVE): justifican el día laborable completo o por horas de cada día del rango con
  la actividad Paid / Unpaid Time Off elegida.
* Promoción y Cambio organizacional (efecto ROSTER) y el puesto en el Ajuste salarial: actualizan roster y expediente.
"""

from django.db import migrations

DAY_SCOPE = [{"value": "DIA", "label": "Día laborable completo"}, {"value": "HORAS", "label": "Por horas"}]


def _leave(code, name, prefix, folio, excluded, order, description):
    return {
        "code": code, "name": name, "category": "STATUS", "effect": "LEAVE", "folio_prefix": folio,
        "creator_signs_first_step": True, "display_order": order, "creator_roles": ["WFM", "HR", "ADMIN"],
        "description": description,
        "attributes": [
            {"key": "actividad", "label": "Tipo de permiso", "data_type": "ACTIVITY", "required": True, "display_order": 10,
             "choices": [prefix] + [f"!{c}" for c in excluded],
             "help_text": "Sub-segmento del Time Utilization que se coloca en la grilla."},
            {"key": "alcance", "label": "Alcance", "data_type": "CHOICE", "required": True, "display_order": 20,
             "choices": DAY_SCOPE, "help_text": "Día completo: cubre todo el turno de cada día laborable del rango."},
            {"key": "fecha_fin", "label": "Hasta (inclusive)", "data_type": "DATE", "required": False, "display_order": 30,
             "help_text": "Vacío = solo la fecha efectiva. Máximo 31 días; los días de descanso se omiten."},
            {"key": "desde", "label": "Hora desde", "data_type": "TIME", "required": False, "display_order": 40,
             "help_text": "Solo «Por horas»."},
            {"key": "hasta", "label": "Hora hasta", "data_type": "TIME", "required": False, "display_order": 50,
             "help_text": "Solo «Por horas»."},
        ],
        "steps": [(1, "Visto bueno de Workforce (WFM)", "WFM"), (2, "Autorización de Recursos Humanos", "HR")],
    }


AP_TYPES = [
    _leave("AP_PERMISO_CON_GOCE", "Permiso con goce de sueldo", "HRP_", "APPG", [], 41,
           "Justifica automáticamente las horas del día laborable (o la ventana) con Paid Time Off: se pagan como programadas."),
    _leave("AP_PERMISO_SIN_GOCE", "Permiso sin goce de sueldo", "HRU_", "APSG", ["HRU_SUSPENSION", "HRU_ATTRITION"], 42,
           "Justifica automáticamente las horas del día laborable (o la ventana) con Unpaid Time Off: no se pagan, pero no "
           "cuentan como Unjustified Absence ni Lateness."),
    {
        "code": "AP_PROMOCION", "name": "Promoción", "category": "POSITION", "effect": "ROSTER", "folio_prefix": "APPR",
        "view_permission": "payroll.view", "create_permission": "hcm.manage", "creator_signs_first_step": True,
        "display_order": 31, "creator_roles": ["HR", "ADMIN"],
        "description": "Nuevo puesto (y salario): actualiza el roster y el expediente en la fecha efectiva.",
        "attributes": [
            {"key": "job_title", "label": "Nuevo puesto", "data_type": "ROSTER", "required": True, "display_order": 10},
            {"key": "new_base_salary", "label": "Nuevo salario base mensual", "data_type": "DECIMAL", "required": False,
             "display_order": 20, "min_value": "0.01", "help_text": "Vacío = conserva el salario actual."},
            {"key": "team_manager", "label": "Nuevo Team Manager", "data_type": "ROSTER", "required": False, "display_order": 30},
            {"key": "line_of_business", "label": "Línea de negocio", "data_type": "ROSTER", "required": False, "display_order": 40},
        ],
        "steps": [(1, "Autorización de Recursos Humanos", "HR"), (2, "Aprobación de Administración / Gerencia", "ADMIN")],
    },
    {
        "code": "AP_CAMBIO_ORGANIZACIONAL", "name": "Cambio organizacional", "category": "POSITION", "effect": "ROSTER",
        "folio_prefix": "APCO", "creator_signs_first_step": True, "display_order": 32, "creator_roles": ["WFM", "HR", "ADMIN"],
        "description": "Traslado de cuenta, marca, línea, Team Manager o centro de costos: actualiza el roster y el expediente.",
        "attributes": [
            {"key": "client", "label": "Cliente (cuenta)", "data_type": "ROSTER", "required": False, "display_order": 10},
            {"key": "brand", "label": "Marca", "data_type": "ROSTER", "required": False, "display_order": 20},
            {"key": "line_of_business", "label": "Línea de negocio", "data_type": "ROSTER", "required": False, "display_order": 30},
            {"key": "sub_line_of_business", "label": "Sub-línea de negocio", "data_type": "ROSTER", "required": False, "display_order": 40},
            {"key": "team_manager", "label": "Team Manager", "data_type": "ROSTER", "required": False, "display_order": 50},
            {"key": "job_title", "label": "Puesto", "data_type": "ROSTER", "required": False, "display_order": 60},
            {"key": "contract_type", "label": "Tipo de contrato", "data_type": "ROSTER", "required": False, "display_order": 70},
            {"key": "cost_center", "label": "Centro de costos (expediente)", "data_type": "ROSTER", "required": False, "display_order": 80},
        ],
        "steps": [(1, "Visto bueno de Workforce (WFM)", "WFM"), (2, "Autorización de Recursos Humanos", "HR")],
    },
]

ROSTER_ATTRIBUTES = [
    {"code": "job_title", "name": "Puesto", "group": "Puesto y contratación", "display_order": 60, "data_type": "STRING",
     "rules": {"max_length": 120}, "help": "Lo actualizan las AP de promoción, ajuste salarial y cambio organizacional."},
    {"code": "contract_type", "name": "Tipo de contrato", "group": "Puesto y contratación", "display_order": 61,
     "data_type": "CHOICE", "choices": ["PERMANENTE", "PERMANENTE JB", "SERVICIOS PROFESIONALES", "SERVICIOS PROF. INTERNACIONAL"],
     "help": "Define las retenciones de ley de la planilla (ISSS, AFP, Renta). Vacío = PERMANENTE."},
]


def seed(apps, schema_editor):
    ActionType = apps.get_model("personnel_actions", "ActionType")
    Attribute = apps.get_model("personnel_actions", "ActionAttribute")
    Step = apps.get_model("personnel_actions", "ApprovalStep")
    RosterAttribute = apps.get_model("roster", "RosterAttribute")
    for spec in ROSTER_ATTRIBUTES:
        RosterAttribute.objects.get_or_create(code=spec["code"], defaults={k: v for k, v in spec.items() if k != "code"})

    j = ActionType.objects.filter(code="AP_JUSTIFICACION_TIEMPO").first()
    if j is not None and j.effect == "NONE":
        j.effect = "JUSTIFY"
        j.description = ("Justifica una ventana del turno (permiso corto, cita, falla de sistema, tiempo extra autorizado): al "
                         "aprobarse se registra en la adherencia y, con actividad, se coloca el segmento en la grilla.")
        j.save(update_fields=["effect", "description"])
        Attribute.objects.filter(action_type=j, key__in=["fecha", "horario"]).update(is_active=False, required=False)
        for a in [
            {"key": "desde", "label": "Hora desde", "data_type": "TIME", "required": True, "display_order": 21},
            {"key": "hasta", "label": "Hora hasta", "data_type": "TIME", "required": True, "display_order": 22,
             "help_text": "Si es menor que «desde», termina al día siguiente (turno nocturno)."},
            {"key": "actividad", "label": "Actividad en la grilla (opcional)", "data_type": "ACTIVITY", "required": False,
             "display_order": 25, "choices": ["!HRU_SUSPENSION", "!HRU_ATTRITION"],
             "help_text": "Sub-segmento del Time Utilization que reemplaza la ventana en la grilla (p. ej. Tech Issues Paid)."},
        ]:
            if not Attribute.objects.filter(action_type=j, key=a["key"]).exists():
                Attribute.objects.create(action_type=j, **a)

    s = ActionType.objects.filter(code="AP_AJUSTE_SALARIAL").first()
    if s is not None and not Attribute.objects.filter(action_type=s, key="job_title").exists():
        Attribute.objects.create(action_type=s, key="job_title", label="Puesto (roster)", data_type="ROSTER", required=False,
                                 display_order=30, help_text="Opcional: si el ajuste acompaña un cambio de puesto.")

    for spec in AP_TYPES:
        spec = dict(spec)
        attributes, steps = spec.pop("attributes"), spec.pop("steps")
        if ActionType.objects.filter(code=spec["code"]).exists():
            continue
        t = ActionType.objects.create(**spec)
        for a in attributes:
            Attribute.objects.create(action_type=t, **a)
        for order, label, role in steps:
            Step.objects.create(action_type=t, order=order, label=label, role=role)


def unseed(apps, schema_editor):
    ActionType = apps.get_model("personnel_actions", "ActionType")
    Action = apps.get_model("personnel_actions", "PersonnelAction")
    for spec in AP_TYPES:
        if not Action.objects.filter(action_type__code=spec["code"]).exists():
            ActionType.objects.filter(code=spec["code"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("personnel_actions", "0009_phase22_effects_and_types"),
        ("roster", "0003_seed_dimensions_and_attributes"),
        ("adherence", "0008_phase19_time_utilization_and_sql"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
