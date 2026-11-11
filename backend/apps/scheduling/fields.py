"""Campo de fecha y hora LOCAL («de pared») de la operación, sin zona horaria.

El proyecto usa USE_TZ=True (la BD guarda UTC). Una marcación de turno, en cambio, se evalúa por el
DÍA CALENDARIO en que ocurrió en el sitio de operación: 22:00 del lunes en San Salvador es lunes, no
martes 04:00 UTC. Por eso estas columnas guardan la hora local tal cual (datetime2 sin conversión) y
Django la devuelve sin tzinfo; ningún cálculo depende de la zona horaria del servidor.
"""

from datetime import datetime

from django.db import models
from django.utils import timezone
from django.utils.dateparse import parse_datetime


def to_wall_clock(value):
    """datetime aware -> hora local (zona activa) sin tzinfo; naive se respeta."""
    if isinstance(value, datetime) and timezone.is_aware(value):
        return timezone.make_naive(value)
    return value


class WallClockDateTimeField(models.DateTimeField):
    def to_python(self, value):
        if isinstance(value, str):
            parsed = parse_datetime(value.strip())
            if parsed is None:
                return super().to_python(value)
            value = parsed
        return to_wall_clock(super().to_python(value) if not isinstance(value, datetime) else value)

    def get_prep_value(self, value):
        # Se omite DateTimeField.get_prep_value: no se convierte a la zona del servidor ni se advierte «naive».
        value = models.Field.get_prep_value(self, value)
        if isinstance(value, str):
            value = self.to_python(value)
        return to_wall_clock(value)

    def get_db_prep_value(self, value, connection, prepared=False):
        if not prepared:
            value = self.get_prep_value(value)
        return connection.ops.adapt_datetimefield_value(value)

    def from_db_value(self, value, expression, connection):
        # El backend la marca como UTC (USE_TZ); el valor guardado ES la hora local: se quita tzinfo.
        if isinstance(value, datetime) and value.tzinfo is not None:
            return value.replace(tzinfo=None)
        return value

    def pre_save(self, model_instance, add):
        return to_wall_clock(super().pre_save(model_instance, add))
