"""Diagnóstico: liveness de la API y validación de la conexión a SQL Server."""

import time

from django.apps import apps
from django.conf import settings
from django.db import DatabaseError, connection
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.fields import split_sql_table


def expected_tables() -> list[str]:
    """Todas las tablas que el backend espera: SQL-first (managed=False) + migraciones de Django."""
    names = set()
    for model in apps.get_models(include_auto_created=True):
        if model._meta.proxy:
            continue
        schema, table = split_sql_table(model._meta.db_table)
        names.add(f"{schema}.{table}")
    return sorted(names)


class LivenessView(APIView):
    """La API responde (no toca la base de datos)."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok", "app": settings.APP_NAME, "environment": settings.APP_ENV})


class DatabaseHealthView(APIView):
    """Abre conexión, consulta SQL Server y verifica que existan todas las tablas del modelo.

    Responde 503 si la BD no es accesible ("error") o falta alguna tabla ("degraded").
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        expected = expected_tables()
        try:
            started = time.perf_counter()
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT DB_NAME(), CAST(SERVERPROPERTY('ProductVersion') AS NVARCHAR(128)), SYSUTCDATETIME()"
                )
                db_name, version, now_utc = cursor.fetchone()
                latency_ms = round((time.perf_counter() - started) * 1000, 2)
                cursor.execute(
                    "SELECT SCHEMA_NAME(schema_id) + '.' + name FROM sys.tables WHERE is_ms_shipped = 0"
                )
                existing = {row[0] for row in cursor.fetchall()}
        except DatabaseError as exc:
            cause = exc.__cause__ or exc
            # En producción no se exponen detalles del driver/servidor.
            detail = type(cause).__name__ if settings.IS_PRODUCTION else f"{type(cause).__name__}: {str(cause)[:300]}"
            return Response(
                {"status": "error", "expected_tables": len(expected), "missing_tables": [], "error": detail},
                status=503,
            )

        missing = [t for t in expected if t not in existing]
        return Response(
            {
                "status": "degraded" if missing else "ok",
                "database": db_name,
                "server_version": version,
                "server_time_utc": now_utc,
                "latency_ms": latency_ms,
                "expected_tables": len(expected),
                "missing_tables": missing,
            },
            status=503 if missing else 200,
        )
