"""Semilla del roster: dimensiones, atributos de la Fase 6 y tipos de documento para reportes.

Clientes, marcas, líneas y sub-líneas NO se siembran (son datos del negocio): se cargan en
/admin/ > Roster operativo. Los tipos de documento son valores de referencia por país.
Idempotente: no sobrescribe lo existente.
"""

from django.db import migrations

DIMENSIONS = [
    # code, name, parent
    ("CLIENT", "Cliente", None),
    ("BRAND", "Marca", "CLIENT"),
    ("LOB", "Línea de negocio", None),
    ("SUB_LOB", "Sub-línea de negocio", "LOB"),
    ("REPORT_ID_TYPE", "Tipo de documento para reportes", None),
]

ATTRIBUTES = [
    # code, name, group, order, data_type, dimension, depends_on, rules, help
    ("client", "Cliente", "Asignación", 10, "DIMENSION", "CLIENT", None, {}, "Cliente al que atiende el empleado."),
    ("brand", "Marca", "Asignación", 20, "DIMENSION", "BRAND", "client", {}, "Marca del cliente (debe pertenecer al cliente vigente)."),
    ("line_of_business", "Línea de negocio", "Asignación", 30, "DIMENSION", "LOB", None, {}, ""),
    ("sub_line_of_business", "Sub-línea de negocio", "Asignación", 40, "DIMENSION", "SUB_LOB", "line_of_business", {},
     "Debe pertenecer a la línea de negocio vigente."),
    ("training_wave", "Wave de training", "Training y fechas clave", 50, "STRING", None, None, {"max_length": 60},
     "Nombre de la wave o grupo de capacitación (p. ej. «Wave 12 - Marzo»)."),
    ("training_start_date", "Inicio de training", "Training y fechas clave", 60, "DATE", None, None, {}, ""),
    ("nesting_start_date", "Inicio de nesting", "Training y fechas clave", 70, "DATE", None, None,
     {"not_before": "training_start_date"}, ""),
    ("nesting_end_date", "Fin de nesting", "Training y fechas clave", 80, "DATE", None, None,
     {"not_before": "nesting_start_date"}, ""),
    ("operations_start_date", "Inicio a operaciones", "Training y fechas clave", 90, "DATE", None, None,
     {"not_before": "nesting_end_date"}, "Primer día en producción."),
    ("report_id_type", "Documento de identidad para reportes", "Reportes", 100, "DIMENSION", "REPORT_ID_TYPE", None, {},
     "Tipo de documento que los reportes de cliente/WFM/QA deben mostrar para el empleado."),
]

REPORT_ID_TYPES = [
    # code, name, country (None = todos)
    ("PASAPORTE", "Pasaporte", None),
    ("DUI", "DUI", "SV"),
    ("NIT_SV", "NIT (El Salvador)", "SV"),
    ("CARNET_RESIDENTE", "Carné de residente", "SV"),
    ("DPI", "DPI", "GT"),
    ("NIT_GT", "NIT (Guatemala)", "GT"),
    ("CURP", "CURP", "MX"),
    ("RFC", "RFC", "MX"),
    ("INE", "Credencial INE", "MX"),
    ("CC", "Cédula de ciudadanía", "CO"),
    ("CE", "Cédula de extranjería", "CO"),
]


def seed(apps, schema_editor):
    Dimension = apps.get_model("roster", "RosterDimension")
    Item = apps.get_model("roster", "RosterDimensionItem")
    Attribute = apps.get_model("roster", "RosterAttribute")
    dims = {}
    for code, name, parent in DIMENSIONS:
        dims[code], _ = Dimension.objects.get_or_create(code=code, defaults={"name": name, "parent": dims.get(parent)})
    attrs = {}
    for code, name, group, order, data_type, dimension, depends_on, rules, help_text in ATTRIBUTES:
        attrs[code], _ = Attribute.objects.get_or_create(
            code=code,
            defaults={
                "name": name, "group": group, "display_order": order, "data_type": data_type,
                "dimension": dims.get(dimension), "depends_on": attrs.get(depends_on), "rules": rules, "help": help_text,
            },
        )
    with schema_editor.connection.cursor() as cursor:  # core.catCountry es SQL-first
        cursor.execute("SELECT CountryCode, CountryId FROM core.catCountry")
        countries = dict(cursor.fetchall())
    for code, name, country in REPORT_ID_TYPES:
        if country and country not in countries:
            continue
        Item.objects.get_or_create(
            dimension=dims["REPORT_ID_TYPE"], code=code, defaults={"name": name, "country_id": countries.get(country)}
        )


def unseed(apps, schema_editor):
    Assignment = apps.get_model("roster", "RosterAssignment")
    if Assignment.objects.exists():
        return  # con historial registrado no se borra la configuración
    apps.get_model("roster", "RosterAttribute").objects.filter(code__in=[a[0] for a in ATTRIBUTES]).update(depends_on=None)
    apps.get_model("roster", "RosterAttribute").objects.filter(code__in=[a[0] for a in ATTRIBUTES]).delete()
    apps.get_model("roster", "RosterDimensionItem").objects.filter(dimension__code="REPORT_ID_TYPE").delete()
    Dimension = apps.get_model("roster", "RosterDimension")
    for code, _, _ in reversed(DIMENSIONS):
        Dimension.objects.filter(code=code, items__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("roster", "0002_sql_integrity_and_reporting_view")]

    operations = [migrations.RunPython(seed, unseed)]
