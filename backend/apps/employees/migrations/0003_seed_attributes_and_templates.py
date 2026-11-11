"""Datos semilla: catálogo de atributos dinámicos y plantilla base por país (SV, GT, MX, CO).

IMPORTANTE: patrones de documentos, salario mínimo y edades son VALORES DE
REFERENCIA para desarrollo; RRHH/Legal debe validarlos y ajustarlos en /admin/
(creando una nueva versión con su fecha de efectividad, no editando la vigente).
Idempotente: no sobrescribe lo que ya exista.
"""

from datetime import date

from django.db import migrations

ATTRIBUTES = [
    # code, name, data_type, sensitive, description
    ("tax_id", "Identificación tributaria", "STRING", True, "NIT / RFC según el país."),
    ("social_security_number", "Número de seguridad social", "STRING", True, "ISSS / IGSS / NSS (IMSS)."),
    ("pension_id", "Número previsional", "STRING", True, "NUP de AFP u otro identificador del sistema de pensiones."),
    ("pension_fund", "Administradora de pensiones", "CHOICE", False, "AFP / fondo de pensiones."),
    ("health_insurer", "Entidad de salud", "STRING", False, "EPS u otra entidad de salud."),
    ("occupational_risk_insurer", "Aseguradora de riesgos laborales", "STRING", False, "ARL."),
    ("compensation_fund", "Caja de compensación familiar", "STRING", False, ""),
    ("bank_name", "Banco para pago de planilla", "STRING", False, ""),
    ("bank_account_number", "Número de cuenta bancaria", "STRING", True, ""),
    ("emergency_contact_name", "Contacto de emergencia", "STRING", False, ""),
    ("emergency_contact_phone", "Teléfono de emergencia", "STRING", False, ""),
    ("dependents_count", "Número de dependientes", "INTEGER", False, ""),
]

_COMMON_ATTRS = {
    "bank_name": {},
    "bank_account_number": {"pattern": "^[0-9-]{6,30}$", "example": "0123456789", "pattern_message": "solo dígitos y guiones"},
    "emergency_contact_name": {"recommended": True},
    "emergency_contact_phone": {"recommended": True},
    "dependents_count": {"min": 0, "max": 30},
}
_PASSPORT = {"pattern": "^[A-Z0-9]{6,12}$", "example": "A1234567"}

TEMPLATES = {
    "SV": {
        "name": "El Salvador — plantilla base",
        "schema": {
            "core_fields": {
                "national_id_type": {"default": "DUI", "choices": ["DUI", "PASAPORTE", "CARNET_RESIDENTE"]},
                "national_id_number": {
                    "transform": "upper",
                    "patterns_by_type": {
                        "DUI": {"pattern": "^\\d{8}-\\d$", "example": "01234567-8"},
                        "PASAPORTE": _PASSPORT,
                        "CARNET_RESIDENTE": {"pattern": "^[0-9-]{6,15}$", "example": "123456"},
                    },
                },
                "phone_number": {"recommended": True, "pattern": "^(\\+503 ?)?[267]\\d{3}-?\\d{4}$", "example": "7123-4567"},
                "work_email": {"recommended": True},
                "cost_center": {"required": True},
            },
            "attributes": {
                "tax_id": {
                    "label": "NIT", "recommended": True, "pattern": "^(\\d{4}-\\d{6}-\\d{3}-\\d|\\d{8}-\\d)$",
                    "example": "0614-010190-101-1", "help": "Desde 2021 el DUI está homologado como NIT.",
                },
                "social_security_number": {"label": "Número de afiliación ISSS", "required": True, "pattern": "^\\d{9}$", "example": "123456789"},
                "pension_id": {"label": "NUP (AFP)", "required": True, "pattern": "^\\d{12}$", "example": "123456789012"},
                "pension_fund": {"label": "AFP", "required": True, "choices": ["CONFIA", "CRECER"]},
                **_COMMON_ATTRS,
            },
            "rules": {"min_age": 18, "min_base_salary": "408.80", "max_future_hire_days": 90},
        },
    },
    "GT": {
        "name": "Guatemala — plantilla base",
        "schema": {
            "core_fields": {
                "national_id_type": {"default": "DPI", "choices": ["DPI", "PASAPORTE"]},
                "national_id_number": {
                    "transform": "strip_spaces",
                    "patterns_by_type": {"DPI": {"pattern": "^\\d{13}$", "example": "1234567890101"}, "PASAPORTE": _PASSPORT},
                },
                "work_email": {"recommended": True},
                "cost_center": {"required": True},
            },
            "attributes": {
                "tax_id": {"label": "NIT", "required": True, "transform": "upper", "pattern": "^\\d{1,12}-?[0-9K]$", "example": "1234567-8"},
                "social_security_number": {"label": "Afiliación IGSS", "required": True, "pattern": "^\\d{6,13}$", "example": "1234567890"},
                **_COMMON_ATTRS,
            },
            "rules": {"min_age": 18, "max_future_hire_days": 90},
        },
    },
    "MX": {
        "name": "México — plantilla base",
        "schema": {
            "core_fields": {
                "national_id_type": {"default": "CURP", "choices": ["CURP", "PASAPORTE"]},
                "national_id_number": {
                    "transform": "upper",
                    "patterns_by_type": {
                        "CURP": {"pattern": "^[A-Z][AEIOUX][A-Z]{2}\\d{6}[HMX][A-Z]{5}[A-Z0-9]\\d$", "example": "GOMC900101HDFRRR09"},
                        "PASAPORTE": _PASSPORT,
                    },
                },
                "work_email": {"recommended": True},
                "cost_center": {"required": True},
            },
            "attributes": {
                "tax_id": {"label": "RFC", "required": True, "transform": "upper", "pattern": "^[A-ZÑ&]{4}\\d{6}[A-Z0-9]{3}$", "example": "GOMC900101AB1"},
                "social_security_number": {"label": "NSS (IMSS)", "required": True, "pattern": "^\\d{11}$", "example": "12345678901"},
                **_COMMON_ATTRS,
            },
            "rules": {"min_age": 18, "max_future_hire_days": 90},
        },
    },
    "CO": {
        "name": "Colombia — plantilla base",
        "schema": {
            "core_fields": {
                "national_id_type": {"default": "CC", "choices": ["CC", "CE", "PASAPORTE"]},
                "national_id_number": {
                    "transform": "upper",
                    "patterns_by_type": {
                        "CC": {"pattern": "^\\d{6,10}$", "example": "1020304050"},
                        "CE": {"pattern": "^[A-Z0-9]{6,12}$", "example": "123456"},
                        "PASAPORTE": _PASSPORT,
                    },
                },
                "work_email": {"recommended": True},
                "cost_center": {"required": True},
            },
            "attributes": {
                "health_insurer": {"label": "EPS", "required": True},
                "pension_fund": {
                    "label": "Fondo de pensiones", "required": True,
                    "choices": ["COLPENSIONES", "PORVENIR", "PROTECCION", "COLFONDOS", "SKANDIA"],
                },
                "occupational_risk_insurer": {"label": "ARL", "required": True},
                "compensation_fund": {"label": "Caja de compensación", "recommended": True},
                **_COMMON_ATTRS,
            },
            "rules": {"min_age": 18, "max_future_hire_days": 90},
        },
    },
}

EFFECTIVE_DATE = date(2000, 1, 1)  # plantilla base: cubre cualquier fecha de ingreso histórica


def seed(apps, schema_editor):
    AttributeDefinition = apps.get_model("employees", "AttributeDefinition")
    EmployeeTemplate = apps.get_model("employees", "EmployeeTemplate")
    for code, name, data_type, sensitive, description in ATTRIBUTES:
        AttributeDefinition.objects.get_or_create(
            code=code, defaults={"name": name, "data_type": data_type, "is_sensitive": sensitive, "description": description}
        )
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT CountryCode, CountryId FROM core.catCountry")
        countries = dict(cursor.fetchall())
    for code, spec in TEMPLATES.items():
        if code not in countries:
            continue
        EmployeeTemplate.objects.get_or_create(
            country_id=countries[code],
            effective_date=EFFECTIVE_DATE,
            defaults={
                "name": spec["name"],
                "schema": spec["schema"],
                "is_active": True,
                "created_by": "migración 0003",
                "notes": "Valores de referencia: validar con RRHH/Legal antes de producción.",
            },
        )


def unseed(apps, schema_editor):
    EmployeeTemplate = apps.get_model("employees", "EmployeeTemplate")
    AttributeDefinition = apps.get_model("employees", "AttributeDefinition")
    EmployeeTemplate.objects.filter(effective_date=EFFECTIVE_DATE, created_by="migración 0003", attribute_values__isnull=True).delete()
    AttributeDefinition.objects.filter(code__in=[a[0] for a in ATTRIBUTES], values__isnull=True, created_at__isnull=False).delete()


class Migration(migrations.Migration):
    dependencies = [("employees", "0002_fk_to_sql_first_tables")]

    operations = [migrations.RunPython(seed, unseed)]
