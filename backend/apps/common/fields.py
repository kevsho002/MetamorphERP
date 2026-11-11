"""Campos y utilidades compartidas por los modelos SQL-first (managed = False).

Convención para columnas con DEFAULT en la BD: se declaran con `db_default`.
Así Django envía la palabra clave DEFAULT en el INSERT (SQL Server aplica su
propio DEFAULT, p.ej. SUSER_SNAME()) y lee el valor final vía OUTPUT. La
expresión indicada en `db_default` es solo un marcador: el DDL real vive en
database/scripts.
"""

from django.db import models
from django.db.models import Value
from django.db.models.expressions import RawSQL
from django.db.models.functions import Now


def sql_table(schema: str, table: str) -> str:
    """Nombre calificado ya entrecomillado: mssql-django lo usa tal cual (`[hcm].[Employee]`)."""
    return f"[{schema}].[{table}]"


def split_sql_table(db_table: str) -> tuple[str, str]:
    """`[hcm].[Employee]` -> ("hcm", "Employee"); `accounts_customuser` -> ("dbo", ...)."""
    if db_table.startswith("[") and "].[" in db_table:
        schema, table = db_table[1:-1].split("].[", 1)
        return schema, table
    return "dbo", db_table


class RowVersionField(models.GeneratedField):
    """Columna ROWVERSION de SQL Server.

    Se modela como columna generada: Django NUNCA la incluye en INSERT/UPDATE
    (la asigna SQL Server). No se devuelve vía OUTPUT porque mssql-django usa una
    tabla temporal `SELECT TOP 0 ... INTO` que hereda el tipo timestamp y
    rechaza el valor; tras guardar use refresh_from_db(fields=["row_ver"]).
    """

    db_returning = False

    def __init__(self, **kwargs):
        kwargs.setdefault("db_column", "RowVer")
        super().__init__(
            expression=RawSQL("CAST(NULL AS BINARY(8))", []),
            output_field=models.BinaryField(),
            db_persist=True,
            **kwargs,
        )

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        for key in ("expression", "output_field", "db_persist"):
            kwargs.pop(key, None)
        return name, path, args, kwargs


class AuditColumns(models.Model):
    """CreatedAt/CreatedBy (DEFAULT SYSUTCDATETIME()/SUSER_SNAME() en BD) + UpdatedAt/UpdatedBy."""

    created_at = models.DateTimeField(db_column="CreatedAt", db_default=Now(), editable=False)
    created_by = models.CharField(db_column="CreatedBy", max_length=100, db_default=Value(""), editable=False)
    updated_at = models.DateTimeField(db_column="UpdatedAt", null=True, blank=True)
    updated_by = models.CharField(db_column="UpdatedBy", max_length=100, null=True, blank=True)

    class Meta:
        abstract = True
