"""Fase 25 — Esquemas de SQL Server por módulo del ERP (fuente única para modelos, ERD y documentación).

dbo solo conserva las tablas internas del framework de Django (auth_*, django_*) y los objetos de diagramas de SSMS.
"""

from contextlib import contextmanager

SCHEMAS = {
    "sec": "Seguridad: cuentas de usuario, permisos y sesiones",
    "adm": "Administración de la plataforma: parámetros, auditoría, notificaciones y estadísticas",
    "core": "Núcleo: catálogos transversales (países, centros de costos) y secuencias",
    "hcm": "Capital humano: colaboradores, expediente digital, plantillas, cargas masivas y General IDs",
    "org": "Estructura operativa: clientes, marcas, líneas de negocio, cadena de mando y roster",
    "wfm": "Workforce Management: horarios, tiempo, cortes, feriados, segmentos y adherencia",
    "acd": "ACD: estados primarios, auxiliares, grupos y sesiones de agentes",
    "pa": "Acciones de personal: tipos, firmas, valores, adjuntos y eventos laborales",
    "fin": "Planillas: cálculo, líneas, boleta diaria, boletas, liquidaciones y retenciones de ley",
    "com": "Comunicados corporativos: periódico virtual, acuses de recibo y cumplimiento",
}

# Prefijo de la tabla (o nombre exacto) -> esquema. El primero que coincide gana.
TABLE_SCHEMA = [
    ("sys_user_session", "sec"), ("accounts_", "sec"),
    ("sys_", "adm"),
    ("hcm_", "hcm"), ("gid_", "hcm"),
    ("ops_", "org"), ("roster_", "org"),
    ("sch_", "wfm"), ("adh_", "wfm"), ("hol_", "wfm"),
    ("acd_", "acd"),
    ("pa_", "pa"),
    ("pay_", "fin"),
    ("com_", "com"),
]


def schema_for(table: str) -> str | None:
    low = table.lower()
    return next((s for prefix, s in TABLE_SCHEMA if low == prefix or low.startswith(prefix)), None)


@contextmanager
def tables_where_they_are(connection):
    """Para migraciones de DATOS anteriores a system.0015 que usan los modelos actuales (cuyo db_table ya apunta al
    esquema del módulo): mientras dura el bloque, cada modelo cuya tabla aún está en dbo usa ese nombre."""
    from django.apps import apps

    with connection.cursor() as c:
        c.execute("SELECT name FROM sys.tables WHERE schema_id = SCHEMA_ID(N'dbo')")
        in_dbo = {r[0] for r in c.fetchall()}
    swapped = []
    for model in apps.get_models(include_auto_created=True):
        table = model._meta.db_table
        if table.startswith("[") and "].[" in table:
            schema, name = table[1:-1].split("].[", 1)
            if schema in SCHEMAS and name in in_dbo:
                swapped.append((model._meta, table))
                model._meta.db_table = name
    _forget_cached_cols(swapped)
    try:
        yield
    finally:
        for meta, table in swapped:
            meta.db_table = table
        _forget_cached_cols(swapped)


def _forget_cached_cols(swapped) -> None:
    """`Field.cached_col` memoriza `Col(db_table, field)`: sin invalidarlo, las consultas posteriores seguirían usando el
    nombre sin esquema como alias (`[sch_pay_period].[period_start]` junto a `FROM [wfm].[sch_pay_period]`)."""
    for meta, _ in swapped:
        for field in meta.local_concrete_fields:
            field.__dict__.pop("cached_col", None)
