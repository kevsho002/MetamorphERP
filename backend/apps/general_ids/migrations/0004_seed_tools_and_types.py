"""Semilla de REFERENCIA: dos herramientas genéricas y los tipos de ID mencionados en el requerimiento.

Son parámetros (no datos de personas): el administrador los renombra, agrega herramientas reales
(Avaya, Genesys, NICE, ADP…), define patrones y restringe por cliente/marca en /admin/.
"""

from django.db import migrations

TOOLS = [
    ("ACD", "Plataforma ACD / telefonía", "TELEPHONY", "Identificador del agente en la plataforma de llamadas."),
    ("PAYROLL_TOOL", "Herramienta de planilla", "PAYROLL", "Sistema externo de planilla / nómina."),
]
TYPES = [
    # code, name, tool, scope, multiple, description, order
    ("ACD_ID", "ACD ID", "ACD", "CLIENT", True,
     "ID de agente en la plataforma ACD. Se registra por cliente (marca opcional); puede haber uno por cliente/marca.", 10),
    ("PAYROLL_TOOL_ID", "Payroll Tool ID", "PAYROLL_TOOL", "GLOBAL", False,
     "ID del colaborador en la herramienta de planilla. Uno vigente a la vez.", 20),
]


def seed(apps, schema_editor):
    Tool = apps.get_model("general_ids", "SourceTool")
    IdType = apps.get_model("general_ids", "GeneralIdType")
    tools = {}
    for code, name, category, description in TOOLS:
        tools[code] = Tool.objects.get_or_create(code=code, defaults={"name": name, "category": category, "description": description})[0]
    for code, name, tool, scope, multiple, description, order in TYPES:
        IdType.objects.get_or_create(
            code=code,
            defaults={"name": name, "tool": tools[tool], "scope_level": scope, "allow_multiple_active": multiple,
                      "description": description, "display_order": order},
        )


def unseed(apps, schema_editor):
    IdType = apps.get_model("general_ids", "GeneralIdType")
    Tool = apps.get_model("general_ids", "SourceTool")
    IdType.objects.filter(code__in=[t[0] for t in TYPES], assignments__isnull=True).delete()
    Tool.objects.filter(code__in=[t[0] for t in TOOLS], id_types__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("general_ids", "0003_sql_integrity_and_reporting_view")]

    operations = [migrations.RunPython(seed, unseed)]
