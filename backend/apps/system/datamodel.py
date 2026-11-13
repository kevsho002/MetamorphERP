"""Fase 22 — Estadísticas de datos por tabla y modelo entidad-relación (ERD) para el panel de administrador.

Fuente: SQL Server (procedimientos dbo.usp_SystemTableStats / dbo.usp_SystemTableColumns y la vista
dbo.vw_SystemForeignKeys), así que incluye las tablas SQL-first (hcm, fin, core) y las de Django.
"""

from __future__ import annotations

from collections import defaultdict

from django.apps import apps
from django.db import connection

# Módulo del ERP de cada tabla (por esquema o prefijo).
MODULES = [
    ("hcm.", "Capital Humano"), ("dbo.hcm_", "Capital Humano"), ("core.", "Núcleo y catálogos"),
    ("fin.", "Planillas"), ("dbo.pay_", "Planillas"), ("dbo.pa_", "Acciones de personal"),
    ("dbo.adh_", "Workforce (WFM)"), ("dbo.sch_", "Horarios y tiempo"), ("dbo.hol_", "Horarios y tiempo"),
    ("dbo.roster_", "Roster operativo"), ("dbo.ops_", "Roster operativo"), ("dbo.gid_", "General IDs"),
    ("dbo.acd_", "ACD · Estados"), ("dbo.accounts_", "Usuarios y seguridad"), ("dbo.auth_", "Usuarios y seguridad"),
    ("dbo.sys_", "Sistema"), ("dbo.django_", "Sistema"),
]
MODULE_COLORS = {
    "Capital Humano": "#2f7dd1", "Núcleo y catálogos": "#64748b", "Planillas": "#0f766e", "Acciones de personal": "#9333ea",
    "Workforce (WFM)": "#ea580c", "Horarios y tiempo": "#ca8a04", "Roster operativo": "#16a34a", "General IDs": "#0891b2",
    "ACD · Estados": "#db2777", "Usuarios y seguridad": "#475569", "Sistema": "#334155", "Otros": "#94a3b8",
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
    rows = _rows("EXEC dbo.usp_SystemTableStats")
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
    cols = _rows("EXEC dbo.usp_SystemTableColumns")
    fks = _rows("SELECT * FROM dbo.vw_SystemForeignKeys ORDER BY from_schema, from_table, fk_name, column_order")
    stats = {f"{r['schema_name']}.{r['table_name']}": int(r["row_count"]) for r in _rows("EXEC dbo.usp_SystemTableStats")}
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
