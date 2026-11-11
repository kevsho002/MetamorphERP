"""Catálogos operativos: FKs reales a core.catCountry, vista de reportes e importación desde el roster.

* FK_ops_*_Country hacia core.catCountry (SQL-first).
* dbo.vw_OpsClientBrand: clientes y marcas en una sola consulta (Power BI / SQL).
* Si ya existían elementos de las dimensiones CLIENT, BRAND, LOB o SUB_LOB en el roster (Fase 6),
  se copian a las tablas de catálogo y quedan enlazados (`roster_item`): las asignaciones
  históricas del roster siguen apuntando al mismo elemento.
"""

from django.db import migrations

_REQUIRE = """
IF OBJECT_ID(N'core.catCountry', N'U') IS NULL
    THROW 50010, N'Falta core.catCountry. Ejecute database/deploy.ps1 antes de migrate.', 1;
"""

_TABLES = ["ops_client", "ops_brand", "ops_line_of_business", "ops_sub_line_of_business"]

FORWARD = [
    _REQUIRE,
    "".join(
        f"""
IF OBJECT_ID(N'dbo.FK_{t}_Country', N'F') IS NULL
    ALTER TABLE dbo.{t} WITH CHECK ADD CONSTRAINT FK_{t}_Country FOREIGN KEY (country_id) REFERENCES core.catCountry (CountryId);
"""
        for t in _TABLES
    ),
    """
CREATE OR ALTER VIEW dbo.vw_OpsClientBrand
AS
SELECT
    c.code       AS ClientCode,
    c.name       AS ClientName,
    c.legal_name AS ClientLegalName,
    cc.CountryCode AS ClientCountryCode,
    c.is_active  AS ClientIsActive,
    b.code       AS BrandCode,
    b.name       AS BrandName,
    bc.CountryCode AS BrandCountryCode,
    b.is_active  AS BrandIsActive
FROM dbo.ops_client AS c
LEFT JOIN dbo.ops_brand AS b ON b.client_id = c.id
LEFT JOIN core.catCountry AS cc ON cc.CountryId = c.country_id
LEFT JOIN core.catCountry AS bc ON bc.CountryId = b.country_id;
""",
]

REVERSE = [
    "IF OBJECT_ID(N'dbo.vw_OpsClientBrand', N'V') IS NOT NULL DROP VIEW dbo.vw_OpsClientBrand;",
    "".join(
        f"IF OBJECT_ID(N'dbo.FK_{t}_Country', N'F') IS NOT NULL ALTER TABLE dbo.{t} DROP CONSTRAINT FK_{t}_Country;\n"
        for t in _TABLES
    ),
]


def import_from_roster(apps, schema_editor):
    Item = apps.get_model("roster", "RosterDimensionItem")
    Client = apps.get_model("operations", "Client")
    Brand = apps.get_model("operations", "Brand")
    Line = apps.get_model("operations", "LineOfBusiness")
    SubLine = apps.get_model("operations", "SubLineOfBusiness")

    def common(item):
        return {"code": item.code, "name": item.name, "country_id": item.country_id, "is_active": item.is_active, "roster_item": item}

    clients = {}
    for item in Item.objects.filter(dimension__code="CLIENT"):
        clients[item.pk] = Client.objects.get_or_create(code=item.code, defaults=common(item))[0]
    for item in Item.objects.filter(dimension__code="BRAND", parent_id__in=list(clients)):
        Brand.objects.get_or_create(code=item.code, defaults={**common(item), "client": clients[item.parent_id]})
    lines = {}
    for item in Item.objects.filter(dimension__code="LOB"):
        lines[item.pk] = Line.objects.get_or_create(code=item.code, defaults=common(item))[0]
    for item in Item.objects.filter(dimension__code="SUB_LOB", parent_id__in=list(lines)):
        SubLine.objects.get_or_create(code=item.code, defaults={**common(item), "line": lines[item.parent_id]})


class Migration(migrations.Migration):
    dependencies = [("operations", "0001_initial")]

    operations = [
        migrations.RunSQL(FORWARD, REVERSE),
        migrations.RunPython(import_from_roster, migrations.RunPython.noop),
    ]
