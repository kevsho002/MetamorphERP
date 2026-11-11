"""Lectura (con caché corta) de los parámetros de sesión y del cliente web."""

from __future__ import annotations

from django.core.cache import cache
from django.db import DatabaseError

_CACHE_KEY = "system:platform_settings"
_TTL_SECONDS = 30


def current():
    """Parámetros vigentes. Sin fila guardada (o sin tabla aún), los valores por defecto del modelo."""
    from apps.system.models import PlatformSettings

    settings_obj = cache.get(_CACHE_KEY)
    if settings_obj is None:
        try:
            settings_obj = PlatformSettings.objects.filter(pk=1).first() or PlatformSettings(pk=1)
        except DatabaseError:  # p. ej. antes de aplicar las migraciones
            return PlatformSettings(pk=1)
        cache.set(_CACHE_KEY, settings_obj, _TTL_SECONDS)
    return settings_obj


def invalidate() -> None:
    cache.delete(_CACHE_KEY)
