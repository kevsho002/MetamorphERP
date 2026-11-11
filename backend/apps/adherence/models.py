"""Fase 16 — Segmentos de actividad, validación de pago y adherencia (WFM).

    adh_activity_type        actividades PRECONFIGURADAS que WFM inserta en el turno (Producción / Calls, Break,
                             Almuerzo, Capacitación, Coaching, Back Office…): pagada, facturable (billing), color y la
                             actividad PREDETERMINADA que rellena el contenedor donde no hay segmentos (una sola)
    adh_activity_status      estados / auxiliares ACD que CUMPLEN cada actividad, con su rol: PRIMARIO (trabajo
                             principal: llamadas, chats, tickets, back office) o SECUNDARIO (auxiliar pagado según el
                             diseño del segmento, p. ej. ACW o coaching dentro de producción)
    adh_schedule_segment     segmento programado (inicio, fin, actividad) dentro del CONTENEDOR del turno: el bloque
                             entrada-salida del horario vigente que creó la AP (sch_schedule_assignment). Sin traslapes
                             por agente (50070); siempre dentro de un contenedor (lo valida el servicio)
    adh_exception            JUSTIFICACIÓN respaldada por una AP APROBADA del mismo empleado (50071): la ventana no se
                             marca como Out of Adherence ni Unpaid Excess Login; se paga si así se indica
    adh_adherence_day        resultado guardado del cálculo por agente y fecha de turno (para nómina y calidad)
    adh_deviation            desviaciones guardadas: OUT_OF_ADHERENCE y UNPAID_EXCESS_LOGIN

Las horas del plan son hora LOCAL de la operación (como los horarios y marcaciones). Las FKs a hcm.Employee
(SQL-first) se crean en la migración 0002.
"""

from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q

from apps.acd.models import AuxCode, PrimaryStatus
from apps.hcm.models import Employee
from apps.scheduling.fields import WallClockDateTimeField

UPPER_CODE = RegexValidator(r"^[A-Z][A-Z0-9_\-]*$", "Use MAYÚSCULAS, dígitos, guion o guion bajo; debe iniciar con letra.")
COLOR = RegexValidator(r"^#[0-9a-fA-F]{6}$", "Color hexadecimal (#RRGGBB).")


def _employee_fk(related_name: str):
    return models.ForeignKey(
        Employee, on_delete=models.DO_NOTHING, db_column="employee_id", db_constraint=False,
        related_name=related_name, verbose_name="agente",
    )


class ActivityType(models.Model):
    class Category(models.TextChoices):
        PRODUCTION = "PRODUCTION", "Producción (calls / chats / tickets)"
        BACK_OFFICE = "BACK_OFFICE", "Back Office"
        BREAK = "BREAK", "Break programado"
        MEAL = "MEAL", "Almuerzo"
        TRAINING = "TRAINING", "Capacitación"
        COACHING = "COACHING", "Coaching"
        MEETING = "MEETING", "Reunión"
        OTHER = "OTHER", "Otra"

    code = models.CharField("código", max_length=30, unique=True, validators=[UPPER_CODE])
    name = models.CharField("nombre", max_length=80)
    category = models.CharField("categoría", max_length=12, choices=Category, default=Category.OTHER)
    description = models.CharField("descripción", max_length=300, blank=True)
    color = models.CharField("color", max_length=7, default="#64748b", validators=[COLOR])
    is_paid = models.BooleanField("tiempo pagado", default=True, help_text="Almuerzo: no pagado.")
    is_billable = models.BooleanField("facturable (billing)", default=False,
                                      help_text="El tiempo en adherencia se factura al cliente (producción, back office).")
    is_default = models.BooleanField(
        "actividad predeterminada del contenedor", default=False,
        help_text="Rellena el tiempo del turno que no cubre ningún segmento (normalmente Producción). Solo una.",
    )
    default_minutes = models.PositiveSmallIntegerField("duración sugerida (min)", null=True, blank=True,
                                                       validators=[MinValueValidator(1), MaxValueValidator(720)])
    sort_order = models.PositiveSmallIntegerField("orden", default=100)
    is_active = models.BooleanField("activa", default=True)
    created_at = models.DateTimeField("creada", auto_now_add=True)
    updated_at = models.DateTimeField("actualizada", auto_now=True)

    class Meta:
        db_table = "adh_activity_type"
        ordering = ["sort_order", "name"]
        verbose_name = "tipo de actividad"
        verbose_name_plural = "tipos de actividad (segmentos)"
        constraints = [
            models.UniqueConstraint(fields=["is_default"], condition=Q(is_default=True), name="uq_adh_activity_default"),
            models.CheckConstraint(condition=~Q(is_default=True) | Q(is_active=True), name="ck_adh_activity_default_active"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class ActivityStatusRule(models.Model):
    class Role(models.TextChoices):
        PRIMARY = "PRIMARY", "Auxiliar primario (trabajo principal)"
        SECONDARY = "SECONDARY", "Auxiliar secundario pagado (según diseño del segmento)"

    activity = models.ForeignKey(ActivityType, on_delete=models.CASCADE, related_name="status_rules", verbose_name="actividad")
    primary_status = models.ForeignKey(PrimaryStatus, on_delete=models.PROTECT, related_name="+", verbose_name="estado primario")
    aux_code = models.ForeignKey(AuxCode, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name="auxiliar",
                                 help_text="Vacío = cualquier auxiliar del estado (o sin auxiliar). Un auxiliar padre incluye sus sub-auxiliares.")
    role = models.CharField("rol", max_length=9, choices=Role, default=Role.PRIMARY)

    class Meta:
        db_table = "adh_activity_status"
        ordering = ["activity_id", "role", "primary_status__sort_order"]
        verbose_name = "estado que cumple la actividad"
        verbose_name_plural = "estados que cumplen la actividad"
        constraints = [
            models.UniqueConstraint(fields=["activity", "primary_status", "aux_code"], name="uq_adh_activity_status"),
            models.CheckConstraint(condition=Q(role__in=["PRIMARY", "SECONDARY"]), name="ck_adh_activity_status_role"),
        ]

    def __str__(self) -> str:
        aux = f" · {self.aux_code.full_name}" if self.aux_code_id else ""
        return f"{self.activity.code}: {self.primary_status.label}{aux} ({self.get_role_display()})"


class ScheduleSegment(models.Model):
    employee = _employee_fk("activity_segments")
    shift_date = models.DateField("fecha del turno")
    assignment = models.ForeignKey(
        "scheduling.ScheduleAssignment", on_delete=models.SET_NULL, null=True, blank=True, related_name="activity_segments",
        verbose_name="horario (contenedor)", help_text="Horario vigente (de la AP) cuyo bloque contiene al segmento.",
    )
    activity = models.ForeignKey(ActivityType, on_delete=models.PROTECT, related_name="segments", verbose_name="actividad")
    start_at = WallClockDateTimeField("inicio (hora local)")
    end_at = WallClockDateTimeField("fin (hora local)")
    notes = models.CharField("notas", max_length=200, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+", verbose_name="programado por")
    created_at = models.DateTimeField("programado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        db_table = "adh_schedule_segment"
        ordering = ["employee_id", "start_at"]
        verbose_name = "segmento de actividad"
        verbose_name_plural = "segmentos de actividad"
        indexes = [
            models.Index(fields=["employee", "shift_date"], name="ix_adh_segment_emp_date"),
            models.Index(fields=["shift_date"], name="ix_adh_segment_date"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(end_at__gt=models.F("start_at")), name="ck_adh_segment_dates"),
        ]

    def __str__(self) -> str:
        return f"{self.employee_id} {self.start_at:%Y-%m-%d %H:%M}–{self.end_at:%H:%M} {self.activity_id}"

    @property
    def minutes(self) -> int:
        return int((self.end_at - self.start_at).total_seconds() // 60)


class AdherenceException(models.Model):
    employee = _employee_fk("adherence_exceptions")
    personnel_action = models.ForeignKey("personnel_actions.PersonnelAction", on_delete=models.PROTECT, related_name="adherence_exceptions",
                                         verbose_name="acción de personal", help_text="AP aprobada del mismo empleado que justifica la ventana.")
    start_at = WallClockDateTimeField("desde (hora local)")
    end_at = WallClockDateTimeField("hasta (hora local)")
    is_paid = models.BooleanField("tiempo pagado", default=True)
    reason = models.CharField("motivo", max_length=200)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+", verbose_name="registrado por")
    created_at = models.DateTimeField("registrado", auto_now_add=True)

    class Meta:
        db_table = "adh_exception"
        ordering = ["employee_id", "start_at"]
        verbose_name = "justificación por AP"
        verbose_name_plural = "justificaciones por AP"
        indexes = [models.Index(fields=["employee", "start_at"], name="ix_adh_exception_emp_start")]
        constraints = [
            models.CheckConstraint(condition=Q(end_at__gt=models.F("start_at")), name="ck_adh_exception_dates"),
        ]

    def __str__(self) -> str:
        return f"{self.employee_id} {self.start_at:%Y-%m-%d %H:%M}–{self.end_at:%Y-%m-%d %H:%M}"


class AdherenceDay(models.Model):
    """Totales (segundos) del cálculo guardado de un agente en una fecha de turno."""

    employee = _employee_fk("adherence_days")
    shift_date = models.DateField("fecha del turno")
    scheduled_seconds = models.IntegerField("programado", default=0)
    scheduled_paid_seconds = models.IntegerField("programado pagado", default=0)
    in_adherence_seconds = models.IntegerField("en adherencia", default=0)
    out_of_adherence_seconds = models.IntegerField("out of adherence", default=0)
    justified_seconds = models.IntegerField("justificado por AP", default=0)
    logged_seconds = models.IntegerField("con sesión", default=0)
    logged_in_container_seconds = models.IntegerField("con sesión dentro del contenedor", default=0)
    paid_valid_seconds = models.IntegerField("válido para pago", default=0)
    billable_seconds = models.IntegerField("facturable", default=0)
    primary_work_seconds = models.IntegerField("trabajo principal (auxiliar primario)", default=0)
    secondary_paid_seconds = models.IntegerField("auxiliares secundarios pagados", default=0)
    unpaid_excess_seconds = models.IntegerField("unpaid excess login", default=0)
    adherence_pct = models.DecimalField("adherencia (%)", max_digits=6, decimal_places=2, null=True, blank=True)
    conformance_pct = models.DecimalField("conformidad (%)", max_digits=6, decimal_places=2, null=True, blank=True)
    computed_at = models.DateTimeField("calculado")
    computed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="calculado por")

    class Meta:
        db_table = "adh_adherence_day"
        ordering = ["shift_date", "employee_id"]
        verbose_name = "adherencia diaria (guardada)"
        verbose_name_plural = "adherencia diaria (guardada)"
        constraints = [
            models.UniqueConstraint(fields=["employee", "shift_date"], name="uq_adh_day_emp_date"),
            models.CheckConstraint(condition=Q(scheduled_seconds__gte=0, unpaid_excess_seconds__gte=0), name="ck_adh_day_seconds"),
        ]

    def __str__(self) -> str:
        return f"{self.employee_id} {self.shift_date} {self.adherence_pct}%"


class Deviation(models.Model):
    class Kind(models.TextChoices):
        OUT_OF_ADHERENCE = "OUT_OF_ADHERENCE", "Out of Adherence"
        UNPAID_EXCESS_LOGIN = "UNPAID_EXCESS_LOGIN", "Unpaid Excess Login"

    id = models.BigAutoField(primary_key=True)
    day = models.ForeignKey(AdherenceDay, on_delete=models.CASCADE, related_name="deviations", verbose_name="día")
    employee = _employee_fk("+")
    shift_date = models.DateField("fecha")
    kind = models.CharField("tipo", max_length=20, choices=Kind)
    start_at = WallClockDateTimeField("desde (hora local)")
    end_at = WallClockDateTimeField("hasta (hora local)")
    seconds = models.IntegerField("duración (s)")
    expected_activity = models.ForeignKey(ActivityType, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                          verbose_name="actividad programada")
    actual_status = models.ForeignKey(PrimaryStatus, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                      verbose_name="estado real")
    actual_aux = models.ForeignKey(AuxCode, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                   verbose_name="auxiliar real")

    class Meta:
        db_table = "adh_deviation"
        ordering = ["employee_id", "start_at"]
        verbose_name = "desviación"
        verbose_name_plural = "desviaciones (Out of Adherence / Unpaid Excess Login)"
        indexes = [models.Index(fields=["employee", "shift_date"], name="ix_adh_deviation_emp_date")]
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=["OUT_OF_ADHERENCE", "UNPAID_EXCESS_LOGIN"]), name="ck_adh_deviation_kind"),
            models.CheckConstraint(condition=Q(end_at__gt=models.F("start_at")), name="ck_adh_deviation_dates"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.employee_id} {self.start_at:%Y-%m-%d %H:%M}"
