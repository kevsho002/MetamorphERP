"""Fase 5: pestañas/secciones (`layout`) y documentos exigidos (`documents`) en las plantillas base.

Solo agrega las claves a las plantillas semilla (vigentes desde 2000-01-01) que aún
no las tengan: no cambia reglas de validación ni toca versiones creadas por RRHH.
Las etiquetas de documentos por país son REFERENCIAS para desarrollo (RRHH/Legal las ajusta).
"""

from datetime import date

from django.db import migrations

BASE_DATE = date(2000, 1, 1)

TABS = [
    ("personal", "Datos personales", [
        ("identity", "Identificación", ["first_name", "middle_name", "last_name", "second_last_name", "birth_date", "gender"]),
        ("id_document", "Documento de identidad", ["national_id_type", "national_id_number"]),
        ("contact", "Contacto", ["work_email", "personal_email", "phone_number"]),
        ("emergency", "Contacto de emergencia", ["emergency_contact_name", "emergency_contact_phone"]),
        ("family", "Familia", ["dependents_count"]),
    ]),
    ("employment", "Datos laborales", [
        ("hiring", "Contratación y compensación", ["hire_date", "cost_center", "base_salary", "pay_frequency"]),
        ("payment", "Pago de planilla", ["bank_name", "bank_account_number"]),
    ]),
    ("social_security", "Seguridad social y previsión", [
        ("tax", "Tributario", ["tax_id"]),
        ("social", "Seguridad social y salud", ["social_security_number", "health_insurer", "occupational_risk_insurer", "compensation_fund"]),
        ("pension", "Pensiones", ["pension_fund", "pension_id"]),
    ]),
]

CORE_KEYS = {
    "first_name", "middle_name", "last_name", "second_last_name", "birth_date", "gender", "national_id_type",
    "national_id_number", "work_email", "personal_email", "phone_number", "hire_date", "cost_center", "base_salary",
    "pay_frequency",
}

DOCUMENTS = {
    "SV": {
        "NATIONAL_ID": {"label": "DUI (ambas caras)", "required": True},
        "TAX_ID": {"label": "NIT", "required": False, "help": "Si el DUI está homologado como NIT, no es necesario."},
    },
    "GT": {"NATIONAL_ID": {"label": "DPI (ambas caras)", "required": True}, "TAX_ID": {"label": "Constancia de NIT", "required": True}},
    "MX": {
        "NATIONAL_ID": {"label": "Identificación oficial (INE / pasaporte)", "required": True},
        "TAX_ID": {"label": "Constancia de situación fiscal (RFC)", "required": True},
    },
    "CO": {"NATIONAL_ID": {"label": "Cédula de ciudadanía", "required": True}, "TAX_ID": {"label": "RUT", "required": True}},
}


def _layout(schema: dict) -> dict:
    available = CORE_KEYS | set(schema.get("attributes", {}))
    tabs = []
    for tab_id, label, sections in TABS:
        resolved = [
            {"id": sid, "title": title, "fields": [k for k in keys if k in available]}
            for sid, title, keys in sections
        ]
        resolved = [s for s in resolved if s["fields"]]
        if resolved:
            tabs.append({"id": tab_id, "label": label, "sections": resolved})
    return {"tabs": tabs}


def forwards(apps, schema_editor):
    Template = apps.get_model("employees", "EmployeeTemplate")
    with schema_editor.connection.cursor() as cursor:  # core.catCountry es SQL-first (sin migraciones)
        cursor.execute("SELECT CountryId, CountryCode FROM core.catCountry")
        codes = dict(cursor.fetchall())
    for template in Template.objects.filter(effective_date=BASE_DATE):
        schema = dict(template.schema or {})
        changed = False
        if "layout" not in schema:
            schema["layout"] = _layout(schema)
            changed = True
        country = codes.get(template.country_id)
        if "documents" not in schema and country in DOCUMENTS:
            schema["documents"] = DOCUMENTS[country]
            changed = True
        if changed:
            template.schema = schema
            template.save(update_fields=["schema", "updated_at"])


def backwards(apps, schema_editor):
    Template = apps.get_model("employees", "EmployeeTemplate")
    for template in Template.objects.filter(effective_date=BASE_DATE):
        schema = dict(template.schema or {})
        if "layout" in schema or "documents" in schema:
            schema.pop("layout", None)
            schema.pop("documents", None)
            template.schema = schema
            template.save(update_fields=["schema", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("employees", "0003_seed_attributes_and_templates")]

    operations = [migrations.RunPython(forwards, backwards)]
