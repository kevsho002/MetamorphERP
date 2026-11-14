"""Fase 22 — Estadísticas de datos por tabla y modelo entidad-relación (ERD) para el panel de administrador.

Fuente: SQL Server (procedimientos adm.usp_SystemTableStats / adm.usp_SystemTableColumns y las vistas
adm.vw_SystemForeignKeys / adm.vw_SystemSqlObject), así que incluye las tablas SQL-first (hcm, fin, core) y las de Django.
"""

from __future__ import annotations

from collections import defaultdict

from django.apps import apps
from django.db import connection

# Módulo del ERP de cada tabla (Fase 25: por su ESQUEMA de SQL Server; General IDs se distingue por prefijo).
MODULES = [
    ("hcm.gid_", "General IDs"), ("hcm.", "Capital Humano"), ("core.", "Núcleo y catálogos"), ("fin.", "Planillas"),
    ("pa.", "Acciones de personal"), ("wfm.adh_", "Workforce (WFM)"), ("wfm.", "Horarios y tiempo"), ("org.", "Roster operativo"),
    ("acd.", "ACD · Estados"), ("sec.", "Usuarios y seguridad"), ("dbo.auth_", "Usuarios y seguridad"), ("adm.", "Sistema"),
    ("dbo.django_", "Sistema"), ("com.", "Comunicados"),
]
MODULE_COLORS = {
    "Capital Humano": "#2f7dd1", "Núcleo y catálogos": "#64748b", "Planillas": "#0f766e", "Acciones de personal": "#9333ea",
    "Workforce (WFM)": "#ea580c", "Horarios y tiempo": "#ca8a04", "Roster operativo": "#16a34a", "General IDs": "#0891b2",
    "ACD · Estados": "#db2777", "Usuarios y seguridad": "#475569", "Sistema": "#334155", "Comunicados": "#c2410c",
    "Otros": "#94a3b8",
}


def module_of(full_name: str) -> str:
    low = full_name.lower()
    for prefix, label in MODULES:
        if low.startswith(prefix.lower()):
            return label
    return "Otros"


def _rows(sql: str, params=None) -> list[dict]:
    with connection.cursor() as c:
        c.execute(sql, params or [])
        cols = [d[0] for d in c.description]
        return [dict(zip(cols, r)) for r in c.fetchall()]


def _django_models() -> dict[str, tuple[str, str]]:
    """«schema.tabla» → (app, nombre legible) de los modelos de Django."""
    from apps.common.fields import split_sql_table

    out = {}
    for m in apps.get_models():
        table = m._meta.db_table
        schema, name = split_sql_table(table)
        out[f"{schema}.{name}".lower()] = (m._meta.app_label, str(m._meta.verbose_name_plural))
    return out


def table_stats() -> dict:
    rows = _rows("EXEC adm.usp_SystemTableStats")
    models = _django_models()
    tables, modules = [], defaultdict(lambda: {"tables": 0, "rows": 0, "reserved_kb": 0})
    for r in rows:
        full = f"{r['schema_name']}.{r['table_name']}"
        mod = module_of(full)
        app, label = models.get(full.lower(), ("", ""))
        tables.append({
            "name": full, "schema": r["schema_name"], "table": r["table_name"], "module": mod, "label": label, "app": app,
            "rows": int(r["row_count"]), "reserved_kb": int(r["reserved_kb"]), "used_kb": int(r["used_kb"]),
            "data_kb": int(r["data_kb"]), "index_kb": max(0, int(r["index_kb"])), "columns": int(r["column_count"]),
            "fk_out": int(r["fk_out"]), "fk_in": int(r["fk_in"]), "triggers": int(r["trigger_count"]),
            "created": r["create_date"], "modified": r["modify_date"], "source": "Django" if app else "SQL-first",
        })
        m = modules[mod]
        m["tables"] += 1
        m["rows"] += int(r["row_count"])
        m["reserved_kb"] += int(r["reserved_kb"])
    with connection.cursor() as c:
        c.execute("SELECT DB_NAME(), SUM(CAST(size AS bigint)) * 8 FROM sys.database_files")
        db_name, db_kb = c.fetchone()
        c.execute("SELECT COUNT(*) FROM sys.procedures WHERE is_ms_shipped = 0")
        procedures = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM sys.views WHERE is_ms_shipped = 0")
        views = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM sys.triggers WHERE is_ms_shipped = 0 AND parent_class = 1")
        triggers = c.fetchone()[0]
    totals = {"tables": len(tables), "rows": sum(t["rows"] for t in tables), "reserved_kb": sum(t["reserved_kb"] for t in tables),
              "empty_tables": sum(1 for t in tables if t["rows"] == 0), "database": db_name, "database_kb": int(db_kb or 0),
              "procedures": procedures, "views": views, "triggers": triggers}
    return {"totals": totals, "tables": tables,
            "modules": [{"module": k, "color": MODULE_COLORS.get(k, "#94a3b8"), **v} for k, v in sorted(modules.items())]}


def erd() -> dict:
    cols = _rows("EXEC adm.usp_SystemTableColumns")
    fks = _rows("SELECT * FROM adm.vw_SystemForeignKeys ORDER BY from_schema, from_table, fk_name, column_order")
    stats = {f"{r['schema_name']}.{r['table_name']}": int(r["row_count"]) for r in _rows("EXEC adm.usp_SystemTableStats")}
    tables: dict[str, dict] = {}
    for c in cols:
        full = f"{c['schema_name']}.{c['table_name']}"
        t = tables.setdefault(full, {"name": full, "schema": c["schema_name"], "table": c["table_name"], "module": module_of(full),
                                     "rows": stats.get(full, 0), "columns": []})
        t["columns"].append({"name": c["column_name"], "type": _type(c), "nullable": bool(c["is_nullable"]),
                             "pk": bool(c["is_pk"]), "fk": bool(c["is_fk"]), "computed": bool(c["is_computed"])})
    relations: dict[str, dict] = {}
    for f in fks:
        rel = relations.setdefault(f["fk_name"], {
            "name": f["fk_name"], "from": f"{f['from_schema']}.{f['from_table']}", "to": f"{f['to_schema']}.{f['to_table']}",
            "columns": [], "on_delete": f["on_delete"], "disabled": bool(f["is_disabled"])})
        rel["columns"].append([f["from_column"], f["to_column"]])
    return {"tables": sorted(tables.values(), key=lambda t: (t["module"], t["name"])), "relations": list(relations.values()),
            "modules": [{"module": k, "color": v} for k, v in MODULE_COLORS.items()]}


def _type(c: dict) -> str:
    t = c["type_name"]
    if t in ("varchar", "char", "varbinary", "binary"):
        return f"{t}({'max' if c['max_length'] == -1 else c['max_length']})"
    if t in ("nvarchar", "nchar"):
        return f"{t}({'max' if c['max_length'] == -1 else c['max_length'] // 2})"
    if t in ("decimal", "numeric"):
        return f"{t}({c['precision']},{c['scale']})"
    return t


# ================================================================ Fase 25: catálogo de objetos programables
TYPE_LABELS = {"VIEW": "Vista", "PROCEDURE": "Procedimiento almacenado", "FUNCTION": "Función", "TRIGGER": "Trigger"}


def _usage() -> dict[int, tuple[int, object]]:
    """Ejecuciones desde el último reinicio de SQL Server (requiere VIEW SERVER STATE; sin él, vacío)."""
    out: dict[int, tuple[int, object]] = {}
    for view in ("sys.dm_exec_procedure_stats", "sys.dm_exec_trigger_stats", "sys.dm_exec_function_stats"):
        try:
            for r in _rows(f"SELECT object_id, SUM(execution_count) AS n, MAX(last_execution_time) AS last FROM {view} "
                           "WHERE database_id = DB_ID() GROUP BY object_id"):
                out[int(r["object_id"])] = (int(r["n"]), r["last"])
        except Exception:  # noqa: BLE001 - sin permiso o vista inexistente: el uso se omite
            continue
    return out


def sql_objects() -> dict:
    from apps.system.sqlcatalog import PURPOSES

    usage = _usage()
    rows = _rows("SELECT * FROM adm.vw_SystemSqlObject ORDER BY SchemaName, ObjectType, ObjectName")
    items = []
    for r in rows:
        unresolved = int(r["UnresolvedReferences"] or 0)
        status = "DISABLED" if r["IsDisabled"] else "BROKEN" if unresolved else "OK"
        used = usage.get(int(r["ObjectId"]))
        full = f"{r['SchemaName']}.{r['ObjectName']}"
        items.append({
            "name": full, "schema": r["SchemaName"], "object": r["ObjectName"], "type": r["ObjectType"],
            "type_label": TYPE_LABELS.get(r["ObjectType"], r["ObjectType"]), "parent": r["ParentTable"],
            "module": module_of(r["ParentTable"] or full), "status": status,
            "status_label": {"OK": "Activo", "DISABLED": "Deshabilitado", "BROKEN": "Referencias sin resolver"}[status],
            "timing": r["TriggerTiming"], "events": r["TriggerEvents"], "unresolved": unresolved,
            "references": int(r["ReferencedObjects"] or 0), "purpose": r["Purpose"] or PURPOSES.get(r["ObjectName"], ""),
            "created": r["CreatedAt"], "modified": r["ModifiedAt"], "executions": used[0] if used else None,
            "last_execution": used[1] if used else None,
        })
    counts: dict[str, int] = defaultdict(int)
    for i in items:
        counts[i["type"]] += 1
    schemas: dict[str, int] = defaultdict(int)
    for i in items:
        schemas[i["schema"]] += 1
    from apps.common.schemas import SCHEMAS

    return {"results": items, "counts": dict(counts), "by_schema": dict(sorted(schemas.items())),
            "schemas": [{"schema": k, "description": v} for k, v in SCHEMAS.items()],
            "problems": sum(1 for i in items if i["status"] != "OK"), "usage_available": bool(usage),
            "types": [{"value": k, "label": v} for k, v in TYPE_LABELS.items()]}
