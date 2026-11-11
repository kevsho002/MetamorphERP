"""Fase 7: catálogo de bancos (hcm_bank) y máscaras de entrada en las plantillas base.

1. Crea hcm_bank con FK real a core.catCountry y la siembra con bancos de REFERENCIA por país
   (RRHH/Finanzas los ajusta en /admin/ › Bancos: agregar, renombrar, desactivar).
2. Plantillas base (vigentes desde 2000-01-01):
   * `bank_name` deja de ser texto libre: `{"catalog": "BANK"}` (lista desplegable del país).
     Un valor de texto libre registrado antes se conserva mientras no se cambie (la validación lo
     reporta como advertencia y pide elegir un banco del catálogo; ver validation.py).
   * Máscaras (`mask`) para documento de identidad, NIT y teléfonos, de modo que el usuario no
     escriba guiones ni espacios. Las máscaras solo formatean: `pattern` sigue validando.
"""

from datetime import date

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models

BASE_DATE = date(2000, 1, 1)

BANKS = {
    "SV": [
        ("AGRICOLA", "Banco Agrícola"), ("CUSCATLAN", "Banco Cuscatlán"), ("DAVIVIENDA", "Banco Davivienda Salvadoreño"),
        ("BAC", "BAC Credomatic"), ("PROMERICA", "Banco Promerica"), ("HIPOTECARIO", "Banco Hipotecario"),
        ("INDUSTRIAL", "Banco Industrial El Salvador"), ("ATLANTIDA", "Banco Atlántida"), ("AZUL", "Banco Azul"),
        ("BFA", "Banco de Fomento Agropecuario"),
    ],
    "GT": [
        ("BANRURAL", "Banrural"), ("INDUSTRIAL", "Banco Industrial"), ("BAM", "Banco Agromercantil (BAM)"),
        ("GYT", "Banco G&T Continental"), ("BAC", "BAC Credomatic"), ("PROMERICA", "Banco Promerica"),
        ("INTERBANCO", "Interbanco"), ("FICOHSA", "Banco Ficohsa"),
    ],
    "MX": [
        ("BBVA", "BBVA México"), ("BANORTE", "Banorte"), ("SANTANDER", "Santander México"), ("BANAMEX", "Banamex"),
        ("HSBC", "HSBC México"), ("SCOTIABANK", "Scotiabank"), ("INBURSA", "Banco Inbursa"), ("AZTECA", "Banco Azteca"),
        ("BANCOPPEL", "BanCoppel"),
    ],
    "CO": [
        ("BANCOLOMBIA", "Bancolombia"), ("BOGOTA", "Banco de Bogotá"), ("DAVIVIENDA", "Davivienda"),
        ("BBVA", "BBVA Colombia"), ("OCCIDENTE", "Banco de Occidente"), ("POPULAR", "Banco Popular"),
        ("AV_VILLAS", "Banco AV Villas"), ("CAJA_SOCIAL", "Banco Caja Social"), ("COLPATRIA", "Scotiabank Colpatria"),
        ("ITAU", "Itaú"),
    ],
}

# Máscaras por país: (sección, clave) -> máscara. "id:<TIPO>" = patterns_by_type de national_id_number.
MASKS = {
    "SV": {
        ("core_fields", "phone_number"): "####-####",
        ("core_fields", "id:DUI"): "########-#",
        ("attributes", "tax_id"): ["########-#", "####-######-###-#"],
        ("attributes", "emergency_contact_phone"): "####-####",
    },
    "GT": {
        ("core_fields", "phone_number"): "####-####",
        ("core_fields", "id:DPI"): "#### ##### ####",
        ("attributes", "emergency_contact_phone"): "####-####",
    },
    "MX": {
        ("core_fields", "phone_number"): "## #### ####",
        ("attributes", "emergency_contact_phone"): "## #### ####",
    },
    "CO": {
        ("core_fields", "phone_number"): "### ### ####",
        ("attributes", "emergency_contact_phone"): "### ### ####",
    },
}

FK_SQL = """
IF OBJECT_ID(N'dbo.FK_hcm_bank_Country', N'F') IS NULL
    ALTER TABLE dbo.hcm_bank WITH CHECK ADD CONSTRAINT FK_hcm_bank_Country
        FOREIGN KEY (country_id) REFERENCES core.catCountry (CountryId);
IF OBJECT_ID(N'dbo.ck_hcm_bank_code', N'C') IS NULL
    ALTER TABLE dbo.hcm_bank WITH CHECK ADD CONSTRAINT ck_hcm_bank_code
        CHECK (code COLLATE Latin1_General_BIN NOT LIKE N'%[^A-Z0-9_]%' AND LEN(code) > 0);
"""
FK_SQL_REVERSE = """
IF OBJECT_ID(N'dbo.ck_hcm_bank_code', N'C') IS NOT NULL ALTER TABLE dbo.hcm_bank DROP CONSTRAINT ck_hcm_bank_code;
IF OBJECT_ID(N'dbo.FK_hcm_bank_Country', N'F') IS NOT NULL ALTER TABLE dbo.hcm_bank DROP CONSTRAINT FK_hcm_bank_Country;
"""


def _country_codes(schema_editor) -> dict[int, str]:
    with schema_editor.connection.cursor() as cursor:  # core.catCountry es SQL-first (sin migraciones)
        cursor.execute("SELECT CountryId, CountryCode FROM core.catCountry")
        return dict(cursor.fetchall())


def seed_banks(apps, schema_editor):
    Bank = apps.get_model("employees", "Bank")
    for country_id, code in _country_codes(schema_editor).items():
        for order, (bank_code, name) in enumerate(BANKS.get(code, []), start=1):
            Bank.objects.get_or_create(
                country_id=country_id, code=bank_code, defaults={"name": name, "display_order": order * 10}
            )


def unseed_banks(apps, schema_editor):
    apps.get_model("employees", "Bank").objects.all().delete()


def update_templates(apps, schema_editor):
    Template = apps.get_model("employees", "EmployeeTemplate")
    codes = _country_codes(schema_editor)
    for template in Template.objects.filter(effective_date=BASE_DATE):
        country = codes.get(template.country_id)
        schema = dict(template.schema or {})
        core = {k: dict(v) for k, v in schema.get("core_fields", {}).items()}
        attributes = {k: dict(v) for k, v in schema.get("attributes", {}).items()}
        for (section, key), mask in MASKS.get(country, {}).items():
            if key.startswith("id:"):
                by_type = core.get("national_id_number", {}).get("patterns_by_type", {})
                rule = by_type.get(key[3:])
                if rule is not None and "mask" not in rule:
                    rule["mask"] = mask
                continue
            target = core if section == "core_fields" else attributes
            if section == "attributes" and key not in target:
                continue
            target.setdefault(key, {}).setdefault("mask", mask)
        bank = attributes.get("bank_name")
        if bank is not None and "catalog" not in bank and "choices" not in bank:
            bank["catalog"] = "BANK"
        schema["core_fields"], schema["attributes"] = core, attributes
        template.schema = schema
        template.save(update_fields=["schema", "updated_at"])


def revert_templates(apps, schema_editor):
    Template = apps.get_model("employees", "EmployeeTemplate")
    for template in Template.objects.filter(effective_date=BASE_DATE):
        schema = dict(template.schema or {})
        for section in ("core_fields", "attributes"):
            for rules in schema.get(section, {}).values():
                rules.pop("mask", None)
                rules.pop("catalog", None)
                for rule in rules.get("patterns_by_type", {}).values():
                    rule.pop("mask", None)
        template.schema = schema
        template.save(update_fields=["schema", "updated_at"])


class Migration(migrations.Migration):
    dependencies = [("employees", "0004_template_layout_and_documents")]

    operations = [
        migrations.CreateModel(
            name="Bank",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "code",
                    models.CharField(
                        help_text="Valor que se guarda en el expediente y se acepta en cargas masivas (también se acepta el nombre).",
                        max_length=20,
                        validators=[django.core.validators.RegexValidator("^[A-Z0-9][A-Z0-9_]*$", "Use MAYÚSCULAS, dígitos y guion bajo.")],
                        verbose_name="código",
                    ),
                ),
                ("name", models.CharField(max_length=150, verbose_name="nombre")),
                (
                    "swift_code",
                    models.CharField(
                        blank=True,
                        max_length=11,
                        validators=[django.core.validators.RegexValidator("^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$", "SWIFT/BIC de 8 u 11 caracteres.")],
                        verbose_name="código SWIFT/BIC",
                    ),
                ),
                ("display_order", models.PositiveSmallIntegerField(default=100, verbose_name="orden")),
                ("is_active", models.BooleanField(default=True, verbose_name="activo")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="creado")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="actualizado")),
                (
                    "country",
                    models.ForeignKey(
                        db_column="country_id",
                        db_constraint=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="banks",
                        to="common.country",
                        verbose_name="país",
                    ),
                ),
            ],
            options={
                "verbose_name": "banco",
                "verbose_name_plural": "bancos",
                "db_table": "hcm_bank",
                "ordering": ["country_id", "display_order", "name"],
                "constraints": [models.UniqueConstraint(fields=("country", "code"), name="uq_hcm_bank_country_code")],
            },
        ),
        migrations.RunSQL(FK_SQL, FK_SQL_REVERSE),
        migrations.RunPython(seed_banks, unseed_banks),
        migrations.RunPython(update_templates, revert_templates),
    ]
