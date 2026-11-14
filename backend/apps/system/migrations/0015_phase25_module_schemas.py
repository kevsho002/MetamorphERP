"""Fase 25 — Reestructuración de SQL Server en ESQUEMAS por módulo (sin el uso genérico de dbo).

Mueve las tablas del ERP con ALTER SCHEMA … TRANSFER (sus índices, restricciones, FK y triggers se mueven con ellas) y
vuelve a crear vistas, procedimientos almacenados, funciones y triggers en el esquema de su módulo, reescribiendo sus
referencias (dbo.tabla → esquema.tabla) fuera de comentarios y literales:

    sec   seguridad: accounts_customuser (+ M2M) y sys_user_session
    adm   plataforma: parámetros, auditoría, notificaciones, preferencias y estadísticas / ERD
    hcm   capital humano (hcm_*) y General IDs (gid_*)        · core: catálogos (ya existía)
    org   estructura operativa y cadena de mando (ops_*, roster_*)
    wfm   horarios, tiempo, cortes, feriados y adherencia (sch_*, hol_*, adh_*)
    acd   estados y sesiones del ACD (acd_*)                    · pa: acciones de personal (pa_*)
    fin   planillas (pay_*) junto a las tablas SQL-first de fin · com: comunicados corporativos (com_*)

En dbo solo quedan las tablas internas del framework de Django (auth_*, django_*) y los objetos de diagramas de SSMS.
La migración es reversible (devuelve todo a dbo). Al final graba el propósito de cada objeto (MS_Description) y crea
adm.vw_SystemSqlObject, el catálogo de vistas / SP / funciones / triggers con su estado.
"""

import re

from django.db import migrations

# Copia CONGELADA de apps.common.schemas (una migración no debe depender del código que cambia).
NEW_SCHEMAS = {
    "sec": "Seguridad: cuentas de usuario, permisos y sesiones",
    "adm": "Administración de la plataforma: parámetros, auditoría, notificaciones y estadísticas",
    "hcm": "Capital humano: colaboradores, expediente digital, plantillas, cargas masivas y General IDs",
    "org": "Estructura operativa: clientes, marcas, líneas de negocio, cadena de mando y roster",
    "wfm": "Workforce Management: horarios, tiempo, cortes, feriados, segmentos y adherencia",
    "acd": "ACD: estados primarios, auxiliares, grupos y sesiones de agentes",
    "pa": "Acciones de personal: tipos, firmas, valores, adjuntos y eventos laborales",
    "fin": "Planillas: cálculo, líneas, boleta diaria, boletas, liquidaciones y retenciones de ley",
    "com": "Comunicados corporativos: periódico virtual, acuses de recibo y cumplimiento",
    "core": "Núcleo: catálogos transversales (países, centros de costos) y secuencias",
}
TABLE_SCHEMA = [
    ("sys_user_session", "sec"), ("accounts_", "sec"), ("sys_", "adm"), ("hcm_", "hcm"), ("gid_", "hcm"),
    ("ops_", "org"), ("roster_", "org"), ("sch_", "wfm"), ("adh_", "wfm"), ("hol_", "wfm"), ("acd_", "acd"),
    ("pa_", "pa"), ("pay_", "fin"), ("com_", "com"),
]
MODULE_SCHEMA = {
    "vw_OpsClientBrand": "org", "vw_OpsLeaderHierarchy": "org", "vw_RosterAgentHierarchy": "org", "vw_RosterAssignment": "org",
    "fn_EmployeesUnderLeader": "org", "vw_EmployeeGeneralId": "hcm", "vw_EmployeeTenure": "hcm",
    "vw_HolidayCalendar": "wfm", "vw_HolidaySegment": "wfm", "fn_EasterSunday": "wfm", "usp_HolidayCopyYear": "wfm",
    "vw_AcdAgentSession": "acd", "vw_AcdStatusSegment": "acd", "vw_PaActionAttachment": "pa", "vw_PersonnelAction": "pa",
    "vw_SystemForeignKeys": "adm", "usp_SystemTableStats": "adm", "usp_SystemTableColumns": "adm",
    "vw_AnnouncementCompliance": "com", "usp_AnnouncementComplianceReport": "com",
}
MODULE_PREFIX = [("vw_Sch", "wfm"), ("vw_Adh", "wfm"), ("vw_Hol", "wfm"), ("vw_Pay", "fin"), ("vw_Pa", "pa"), ("vw_Acd", "acd"),
                 ("vw_Ops", "org"), ("vw_Roster", "org"), ("vw_Employee", "hcm"), ("vw_System", "adm"), ("usp_System", "adm")]
DIAGRAM_OBJECTS = {"sysdiagrams", "fn_diagramobjects", "sp_alterdiagram", "sp_creatediagram", "sp_dropdiagram",
                   "sp_helpdiagramdefinition", "sp_helpdiagrams", "sp_renamediagram", "sp_upgraddiagrams"}
KINDS = {"FN": "FUNCTION", "IF": "FUNCTION", "TF": "FUNCTION", "V": "VIEW", "P": "PROCEDURE", "TR": "TRIGGER"}
CREATE_ORDER = ["FN", "IF", "TF", "V", "P", "TR"]


def table_schema(name: str) -> str | None:
    low = name.lower()
    return next((s for prefix, s in TABLE_SCHEMA if low == prefix or low.startswith(prefix)), None)


def module_schema(name: str) -> str:
    return MODULE_SCHEMA.get(name) or next((s for p, s in MODULE_PREFIX if name.startswith(p)), "adm")


# ------------------------------------------------------------------ reescritura de definiciones
_TOKENS = re.compile(r"(--[^\n]*|/\*.*?\*/|N?'(?:[^']|'')*')", re.S)
_TWO_PART = re.compile(r"(?:\[(\w+)\]|\b(\w+))\s*\.\s*(?:\[(\w+)\]|(\w+)\b)")
_CREATE = re.compile(r"\bCREATE\s+(?:OR\s+ALTER\s+)?(TRIGGER|VIEW|PROCEDURE|PROC|FUNCTION)\b", re.I)


def rewrite(definition: str, moves: dict[str, tuple[str, str]]) -> str:
    """Cambia `origen.nombre` por `destino.nombre` (y los nombres sin esquema de objetos que salen de dbo) solo en el
    código: comentarios y literales quedan intactos. La sentencia queda como CREATE OR ALTER."""
    bare = [n for n, (src, _) in moves.items() if src == "dbo"]
    bare_re = re.compile(r"(?<![\w.\[\]@#$])(" + "|".join(map(re.escape, sorted(bare, key=len, reverse=True))) + r")\b(?!\s*\.)") if bare else None

    def code(segment: str) -> str:
        def two(m):
            schema, name = m.group(1) or m.group(2), m.group(3) or m.group(4)
            move = moves.get(name)
            if move and schema.lower() == move[0].lower():
                return f"{move[1]}.{name}"
            return m.group(0)

        out, pos = [], 0
        for m in _TWO_PART.finditer(segment):
            out.append(segment[pos:m.start()])
            if (m.group(1) or m.group(2)).lower() in ("inserted", "deleted"):
                out.append(m.group(0))
            else:
                out.append(two(m))
            pos = m.end()
        out.append(segment[pos:])
        text = "".join(out)
        if bare_re is not None:
            text = bare_re.sub(lambda m: f"{moves[m.group(1)][1]}.{m.group(1)}", text)
        return text

    parts = _TOKENS.split(definition)
    text = "".join(p if i % 2 else code(p) for i, p in enumerate(parts))
    def header(m):
        kind = m.group(1).upper()
        return f"CREATE OR ALTER {'PROCEDURE' if kind == 'PROC' else kind}"

    return _CREATE.sub(header, text, count=1)


# ------------------------------------------------------------------ movimiento
def _rows(c, sql, params=None):
    c.execute(sql, params or [])
    return c.fetchall()


def _known(name: str) -> bool:
    return name in MODULE_SCHEMA or any(name.startswith(p) for p, _ in MODULE_PREFIX)


def _plan(c, forward: bool):
    """Tablas a transferir, módulos a recrear (con su esquema destino) y el mapa {nombre: (origen, destino)}."""
    if forward:
        tables = {n: ("dbo", s) for (n,) in _rows(c, "SELECT name FROM sys.tables WHERE schema_id = SCHEMA_ID(N'dbo') AND is_ms_shipped = 0")
                  if n not in DIAGRAM_OBJECTS and (s := table_schema(n))}
    else:
        tables = {n: (sch, "dbo") for n, sch in _rows(c, "SELECT name, SCHEMA_NAME(schema_id) FROM sys.tables WHERE is_ms_shipped = 0")
                  if sch != "dbo" and table_schema(n) == sch}
    found = [r for r in _rows(c, """
            SELECT o.name, RTRIM(o.type), SCHEMA_NAME(o.schema_id), OBJECT_NAME(o.parent_object_id), m.definition
            FROM sys.objects o JOIN sys.sql_modules m ON m.object_id = o.object_id
            WHERE o.is_ms_shipped = 0 AND o.type IN ('V', 'P', 'FN', 'IF', 'TF', 'TR')""")
             if r[0] not in DIAGRAM_OBJECTS and r[0] != "vw_SystemSqlObject"]
    moves = dict(tables)
    planned: dict[str, tuple] = {}
    for name, kind, schema, parent, definition in found:
        if kind == "TR":
            if parent in tables:  # el trigger se mueve con su tabla; se recrea para reescribir sus referencias
                planned[name] = (name, kind, schema, tables[parent][1], definition)
                moves[name] = (schema, tables[parent][1])
            continue
        if forward and schema == "dbo":
            target = module_schema(name)
        elif not forward and schema != "dbo" and _known(name) and module_schema(name) == schema:
            target = "dbo"
        else:
            continue
        moves[name] = (schema, target)
        planned[name] = (name, kind, schema, target, definition)
    # Objetos que no cambian de esquema pero REFERENCIAN algo que sí (p. ej. triggers SQL-first de fin): se recrean en su lugar.
    for name, kind, schema, parent, definition in found:
        if name not in planned and _normalized(rewrite(definition, moves)) != _normalized(definition):
            planned[name] = (name, kind, schema, schema, definition)
    return tables, list(planned.values()), moves


def _normalized(text: str) -> str:
    return _CREATE.sub("CREATE", text, count=1)


def _create_all(c, modules, moves):
    pending = sorted(modules, key=lambda m: CREATE_ORDER.index(m[1]))
    for _ in range(len(pending) + 1):
        failed, last_error = [], None
        for m in pending:
            name, kind, src, dst, definition = m
            try:
                c.execute(rewrite(definition, moves))
            except Exception as exc:  # una vista que depende de otra aún no creada: se reintenta
                failed.append(m)
                last_error = (name, exc)
        if not failed:
            return
        if len(failed) == len(pending):
            raise RuntimeError(f"No se pudo recrear {last_error[0]} en su esquema: {last_error[1]}")
        pending = failed


def move(apps, schema_editor, forward: bool = True):
    with schema_editor.connection.cursor() as c:
        for schema in NEW_SCHEMAS:
            c.execute(f"IF SCHEMA_ID(N'{schema}') IS NULL EXEC (N'CREATE SCHEMA [{schema}] AUTHORIZATION dbo;')")
        if not forward:
            c.execute("DROP VIEW IF EXISTS adm.vw_SystemSqlObject")
        tables, modules, moves = _plan(c, forward)
        for name, (src, dst) in sorted(tables.items()):
            c.execute(f"ALTER SCHEMA [{dst}] TRANSFER [{src}].[{name}]")
        _create_all(c, modules, moves)
        for name, kind, src, dst, _ in modules:
            if kind != "TR" and src != dst:
                c.execute(f"DROP {KINDS[kind]} IF EXISTS [{src}].[{name}]")
        if forward:
            for schema, text in NEW_SCHEMAS.items():
                c.execute("""
                    IF EXISTS (SELECT 1 FROM sys.extended_properties WHERE class = 3 AND major_id = SCHEMA_ID(%s) AND name = N'MS_Description')
                        EXEC sys.sp_updateextendedproperty @name = N'MS_Description', @value = %s, @level0type = N'SCHEMA', @level0name = %s
                    ELSE
                        EXEC sys.sp_addextendedproperty @name = N'MS_Description', @value = %s, @level0type = N'SCHEMA', @level0name = %s
                    """, [schema, text, schema, text, schema])
            try:
                from apps.system.sqlcatalog import apply_descriptions
            except ImportError:  # pragma: no cover - el catálogo es documentación
                apply_descriptions = None
            c.execute(CATALOG_VIEW)
            if apply_descriptions:
                apply_descriptions(c)


def forwards(apps, schema_editor):
    move(apps, schema_editor, forward=True)


def backwards(apps, schema_editor):
    move(apps, schema_editor, forward=False)


CATALOG_VIEW = r"""
CREATE OR ALTER VIEW adm.vw_SystemSqlObject
AS
SELECT o.object_id AS ObjectId,
       SCHEMA_NAME(o.schema_id) AS SchemaName,
       o.name AS ObjectName,
       CASE RTRIM(o.type) WHEN 'V' THEN N'VIEW' WHEN 'P' THEN N'PROCEDURE' WHEN 'TR' THEN N'TRIGGER' ELSE N'FUNCTION' END AS ObjectType,
       RTRIM(o.type) AS TypeCode,
       CASE WHEN o.parent_object_id = 0 THEN NULL ELSE SCHEMA_NAME(p.schema_id) + N'.' + p.name END AS ParentTable,
       CAST(ISNULL(t.is_disabled, 0) AS bit) AS IsDisabled,
       CASE WHEN t.object_id IS NULL THEN NULL WHEN t.is_instead_of_trigger = 1 THEN N'INSTEAD OF' ELSE N'AFTER' END AS TriggerTiming,
       STUFF((SELECT N', ' + te.type_desc FROM sys.trigger_events te WHERE te.object_id = o.object_id ORDER BY te.type
              FOR XML PATH(''), TYPE).value('.', 'nvarchar(200)'), 1, 2, N'') AS TriggerEvents,
       (SELECT COUNT(*) FROM sys.sql_expression_dependencies d
        WHERE d.referencing_id = o.object_id AND d.referenced_id IS NULL AND d.referenced_schema_name IS NOT NULL
          AND d.referenced_database_name IS NULL AND d.is_ambiguous = 0) AS UnresolvedReferences,
       (SELECT COUNT(DISTINCT d.referenced_id) FROM sys.sql_expression_dependencies d
        WHERE d.referencing_id = o.object_id AND d.referenced_id IS NOT NULL) AS ReferencedObjects,
       CAST(m.uses_ansi_nulls AS bit) AS UsesAnsiNulls,
       LEN(m.definition) AS DefinitionLength,
       o.create_date AS CreatedAt,
       o.modify_date AS ModifiedAt,
       CAST(ep.value AS nvarchar(500)) AS Purpose
FROM sys.objects o
JOIN sys.sql_modules m ON m.object_id = o.object_id
LEFT JOIN sys.objects p ON p.object_id = o.parent_object_id
LEFT JOIN sys.triggers t ON t.object_id = o.object_id
LEFT JOIN sys.extended_properties ep ON ep.class = 1 AND ep.major_id = o.object_id AND ep.minor_id = 0 AND ep.name = N'MS_Description'
WHERE o.is_ms_shipped = 0 AND o.type IN ('V', 'P', 'FN', 'IF', 'TF', 'TR')
  AND o.name NOT IN (N'fn_diagramobjects', N'sp_alterdiagram', N'sp_creatediagram', N'sp_dropdiagram', N'sp_helpdiagramdefinition',
                     N'sp_helpdiagrams', N'sp_renamediagram', N'sp_upgraddiagrams');
"""


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("system", "0014_phase25"),
        ("accounts", "0003_phase25"),
        ("acd", "0002_sql_integrity_views_and_seed"),
        ("adherence", "0008_phase19_time_utilization_and_sql"),
        ("communications", "0002_phase25_sql"),
        ("employees", "0005_bank_catalog_and_input_masks"),
        ("general_ids", "0004_seed_tools_and_types"),
        ("holidays", "0003_phase23_calendar_sql"),
        ("operations", "0004_leader_sql_rules_views_and_seed"),
        ("payroll", "0006_phase25_payroll_day_sql"),
        ("personnel_actions", "0013_phase24_attachment_sql"),
        ("roster", "0003_seed_dimensions_and_attributes"),
        ("scheduling", "0010_phase24_default_cutoffs"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
