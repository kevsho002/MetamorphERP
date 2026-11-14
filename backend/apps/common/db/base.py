"""Fase 25 — Backend de SQL Server de Metamorph ERP: mssql-django + tablas en ESQUEMAS por módulo.

Las tablas del ERP viven en esquemas funcionales (sec, adm, hcm, org, wfm, acd, pa, fin, com) y sus modelos declaran
`db_table = "[esquema].[tabla]"` (apps.common.fields.sql_table). mssql-django ya usa ese nombre tal cual en las consultas
y en los nombres de índices; esta capa delgada hace que la INTROSPECCIÓN (la que usan las migraciones para encontrar
llaves, índices y restricciones, y `table_names()`) también entienda el esquema, de modo que las migraciones futuras
(AlterField, RemoveField, AddConstraint…) funcionen sobre las tablas que ya no están en dbo.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager

import mssql.introspection as mssql_introspection
from mssql.base import DatabaseWrapper as MssqlDatabaseWrapper
from mssql.introspection import DatabaseIntrospection as MssqlIntrospection

_schema = contextvars.ContextVar("metamorph_schema", default=None)
_original_schema_name = mssql_introspection.get_schema_name


def _schema_name() -> str:
    schema = _schema.get()
    return f"N'{schema}'" if schema else _original_schema_name()


# mssql-django arma sus consultas con get_schema_name() en el momento de la llamada.
mssql_introspection.get_schema_name = _schema_name


@contextmanager
def _in_schema(schema: str | None):
    token = _schema.set(schema if schema and schema != "dbo" else None)
    try:
        yield
    finally:
        _schema.reset(token)


def _split(table_name: str) -> tuple[str | None, str]:
    if table_name.startswith("[") and table_name.endswith("]") and "].[" in table_name:
        schema, table = table_name[1:-1].split("].[", 1)
        return schema, table
    return None, table_name


class _SchemaCursor:
    """Proxy del cursor que fija el esquema en cursor.columns() (pyodbc)."""

    def __init__(self, cursor, schema):
        self._cursor, self._schema = cursor, schema

    def columns(self, **kwargs):
        return self._cursor.columns(schema=self._schema, **kwargs)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class DatabaseIntrospection(MssqlIntrospection):
    def get_table_list(self, cursor):
        """Tablas y vistas de TODOS los esquemas: las de dbo con su nombre simple; las demás como [esquema].[nombre]."""
        cursor.execute("SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES")
        types = {"BASE TABLE": "t", "VIEW": "v"}
        info = mssql_introspection.TableInfo
        return [info(name if schema == "dbo" else f"[{schema}].[{name}]", types.get(kind), "")
                for schema, name, kind in cursor.fetchall() if name not in self.ignored_tables]

    def _call(self, method, cursor, table_name, *args, **kwargs):
        schema, name = _split(table_name)
        if schema is None:
            return method(cursor, table_name, *args, **kwargs)
        with _in_schema(schema):
            return method(cursor, name, *args, **kwargs)

    def get_constraints(self, cursor, table_name):
        return self._call(super().get_constraints, cursor, table_name)

    def get_relations(self, cursor, table_name):
        return self._call(super().get_relations, cursor, table_name)

    def get_key_columns(self, cursor, table_name):
        return self._call(super().get_key_columns, cursor, table_name)

    def get_sequences(self, cursor, table_name, table_fields=()):
        schema, name = _split(table_name)
        if schema is None:
            return super().get_sequences(cursor, table_name, table_fields)
        with _in_schema(schema):
            rows = super().get_sequences(cursor, name, table_fields)
        return [{**r, "table": table_name} for r in rows]

    def get_primary_key_column(self, cursor, table_name):
        schema, name = _split(table_name)
        if schema is None:
            return super().get_primary_key_column(cursor, table_name)
        for constraint in self.get_constraints(cursor, table_name).values():
            if constraint["primary_key"]:
                return constraint["columns"][0]
        return None

    def get_table_description(self, cursor, table_name, identity_check=True):
        schema, name = _split(table_name)
        if schema is None:
            return super().get_table_description(cursor, table_name, identity_check)
        items = super().get_table_description(_SchemaCursor(cursor, schema), name, identity_check=False)
        if not identity_check:
            return items
        out = []
        for item in items:
            if self._is_auto_field(cursor, table_name, item.name):
                kind = {mssql_introspection.Database.SQL_BIGINT: mssql_introspection.SQL_BIGAUTOFIELD,
                        mssql_introspection.Database.SQL_SMALLINT: mssql_introspection.SQL_SMALLAUTOFIELD}.get(
                    item.type_code, mssql_introspection.SQL_AUTOFIELD)
                item = item._replace(type_code=kind)
            out.append(item)
        return out


class DatabaseWrapper(MssqlDatabaseWrapper):
    introspection_class = DatabaseIntrospection
