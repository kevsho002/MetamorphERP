"""Fase 21 — Calendario de feriados legales y contenedores «Holiday Segment».

    hol_holiday           feriado por país y fecha (nacional, local o de la empresa) con su recargo (pago doble)
    hol_holiday_segment   contenedor generado AUTOMÁTICAMENTE cuando un colaborador labora en un feriado: el bloque del
                          turno (o el tramo trabajado) con las horas laboradas; la planilla paga esas horas como salario
                          regular + el recargo del feriado. Vive aparte de los segmentos de actividad de WFM: no cambia la
                          adherencia ni la asistencia, y en un feriado la conciliación no marca Unjustified Absence ni
                          Lateness.

SQL Server (migración 0002): FKs a core.catCountry y hcm.Employee; TR_hol_holiday_locked (50097) impide cambiar la fecha
o el país de un feriado (o borrarlo) cuando ya generó Holiday Segments; vista dbo.vw_HolidaySegment.
"""

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.common.models import Country
from apps.hcm.models import Employee
from apps.scheduling.fields import WallClockDateTimeField


class Holiday(models.Model):
    class Kind(models.TextChoices):
        NATIONAL = "NATIONAL", "Feriado nacional (Código de Trabajo)"
        LOCAL = "LOCAL", "Feriado local (fiestas patronales)"
        COMPANY = "COMPANY", "Asueto de la empresa"

    country = models.ForeignKey(Country, models.DO_NOTHING, db_column="country_id", db_constraint=False, related_name="+",
                                verbose_name="país")
    date = models.DateField("fecha")
    name = models.CharField("nombre", max_length=120)
    kind = models.CharField("tipo", max_length=10, choices=Kind, default=Kind.NATIONAL)
    premium_percent = models.DecimalField(
        "recargo por laborarlo (%)", max_digits=6, decimal_places=2, default=100,
        help_text="100 % = pago doble: salario regular de las horas + otro 100 % por laborar el feriado.",
    )
    legal_reference = models.CharField("referencia legal", max_length=200, blank=True)
    is_active = models.BooleanField("activo", default=True)
    created_at = models.DateTimeField("creado", auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        db_table = "hol_holiday"
        ordering = ["date"]
        verbose_name = "feriado"
        verbose_name_plural = "calendario de feriados"
        constraints = [
            models.UniqueConstraint(fields=["country", "date"], name="uq_hol_holiday_country_date"),
            models.CheckConstraint(condition=Q(premium_percent__gte=0, premium_percent__lte=300), name="ck_hol_holiday_premium"),
            models.CheckConstraint(condition=Q(kind__in=["NATIONAL", "LOCAL", "COMPANY"]), name="ck_hol_holiday_kind"),
        ]

    def __str__(self) -> str:
        return f"{self.date:%d/%m/%Y} {self.name}"


class HolidaySegment(models.Model):
    holiday = models.ForeignKey(Holiday, on_delete=models.PROTECT, related_name="segments", verbose_name="feriado")
    employee = models.ForeignKey(Employee, models.DO_NOTHING, db_column="employee_id", db_constraint=False,
                                 related_name="holiday_segments", verbose_name="empleado")
    shift_date = models.DateField("fecha")
    start_at = WallClockDateTimeField("inicio del contenedor")
    end_at = WallClockDateTimeField("fin del contenedor")
    scheduled_seconds = models.IntegerField("programado", default=0)
    worked_seconds = models.IntegerField("laborado (Web Timer)", default=0)
    night_seconds = models.IntegerField("laborado nocturno", default=0)
    premium_percent = models.DecimalField("recargo aplicado (%)", max_digits=6, decimal_places=2)
    generated_at = models.DateTimeField("generado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        db_table = "hol_holiday_segment"
        ordering = ["shift_date", "employee_id"]
        verbose_name = "Holiday Segment"
        verbose_name_plural = "Holiday Segments (feriados laborados)"
        constraints = [
            models.UniqueConstraint(fields=["holiday", "employee"], name="uq_hol_segment_holiday_employee"),
            models.CheckConstraint(condition=Q(end_at__gt=models.F("start_at")), name="ck_hol_segment_span"),
            models.CheckConstraint(condition=Q(worked_seconds__gt=0, scheduled_seconds__gte=0, night_seconds__gte=0),
                                   name="ck_hol_segment_seconds"),
        ]

    def __str__(self) -> str:
        return f"Holiday {self.shift_date} {self.employee_id}"
