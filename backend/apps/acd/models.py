"""Fase 11 — Estados y auxiliares ACD (estilo Genesys Cloud).

    acd_division            división organizacional (Division Id / Division Name del reporte)
    acd_primary_status      ESTADOS OPERATIVOS del sistema (presencias primarias): Offline, Available, On Queue, Busy,
                            Away, Break, Meal, Meeting, Training, Idle. Códigos fijos; se parametrizan etiquetas y banderas
    acd_aux_code            AUXILIARES (presencias secundarias, p. ej. «Coaching», «ACW», «Lunch») bajo un estado primario
                            y SUB-AUXILIARES (un nivel: «Coaching - Calidad»). Mismo estado primario que su padre (50062)
    acd_agent_group         grupo / perfil de agentes; define qué auxiliares ve y usa (acd_group_aux) y su división
    acd_group_aux           acceso de un grupo a un auxiliar (dar acceso al auxiliar padre incluye sus sub-auxiliares)
    acd_agent_member        pertenencia del agente a UN grupo activo (índice único filtrado)
    acd_agent_session       inicio / cierre de sesión ACD; al cerrar, el tiempo pagado se envía a sch_time_record
                            como WEB_TIMER (horas reales para el reporte teórico vs real y la planilla)
    acd_status_segment      segmento de estado con Start Time / End Time / Duration (ms), hora del SERVIDOR en UTC:
                            uno abierto por agente (índice único filtrado), sin traslapes (50060), auxiliar del mismo
                            estado primario (50061)

Las FKs a hcm.Employee (SQL-first) se crean en la migración 0002.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q

from apps.common.fields import sql_table
from apps.hcm.models import Employee

UPPER_CODE = RegexValidator(r"^[A-Z][A-Z0-9_\-]*$", "Use MAYÚSCULAS, dígitos, guion o guion bajo; debe iniciar con letra.")


def _employee_fk(related_name: str, **kwargs):
    return models.ForeignKey(
        Employee, on_delete=models.DO_NOTHING, db_column="employee_id", db_constraint=False,
        related_name=related_name, verbose_name="agente", **kwargs,
    )


class Division(models.Model):
    division_uid = models.UUIDField("Division Id", default=uuid.uuid4, unique=True, editable=False,
                                    help_text="Identificador estable que se exporta en «Division Id».")
    code = models.CharField("código", max_length=30, unique=True, validators=[UPPER_CODE])
    name = models.CharField("nombre (Division Name)", max_length=120)
    is_active = models.BooleanField("activa", default=True)
    created_at = models.DateTimeField("creada", auto_now_add=True)

    class Meta:
        db_table = sql_table("acd", "acd_division")
        ordering = ["name"]
        verbose_name = "división"
        verbose_name_plural = "divisiones"

    def __str__(self) -> str:
        return self.name


class PrimaryStatus(models.Model):
    """Estado operativo (presencia primaria). Los códigos son fijos: el flujo los usa por nombre."""

    OFFLINE, AVAILABLE, ON_QUEUE, IDLE = "OFFLINE", "AVAILABLE", "ON_QUEUE", "IDLE"

    code = models.CharField("código", max_length=20, unique=True, validators=[UPPER_CODE])
    label = models.CharField("etiqueta del reporte (Primary Status)", max_length=40,
                             help_text="Texto exacto que se exporta, como en Genesys Cloud (p. ej. «On Queue»).")
    name_es = models.CharField("nombre en pantalla", max_length=60)
    is_logged_in = models.BooleanField("cuenta como sesión iniciada", default=True)
    is_productive = models.BooleanField("tiempo productivo", default=False, help_text="On Queue: tiempo en colas.")
    is_paid = models.BooleanField("tiempo pagado", default=True,
                                  help_text="El tiempo pagado de la sesión se envía como horas reales (Web Timer).")
    agent_selectable = models.BooleanField("el agente lo puede elegir", default=True,
                                           help_text="Offline (cerrar sesión) e Idle (sistema) no se eligen directamente.")
    color = models.CharField("color", max_length=7, default="#64748b", validators=[RegexValidator(r"^#[0-9a-fA-F]{6}$")])
    sort_order = models.PositiveSmallIntegerField("orden", default=100)
    is_active = models.BooleanField("activo", default=True)

    class Meta:
        db_table = sql_table("acd", "acd_primary_status")
        ordering = ["sort_order", "code"]
        verbose_name = "estado operativo (primario)"
        verbose_name_plural = "estados operativos (primarios)"

    def __str__(self) -> str:
        return f"{self.label} — {self.name_es}"


class AuxCode(models.Model):
    """Auxiliar (presencia secundaria) bajo un estado primario; con `parent`, sub-auxiliar (un solo nivel)."""

    primary_status = models.ForeignKey(PrimaryStatus, on_delete=models.PROTECT, related_name="aux_codes", verbose_name="estado primario")
    parent = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="children",
                               verbose_name="auxiliar padre", help_text="Vacío = auxiliar; con padre = sub-auxiliar.")
    code = models.CharField("código", max_length=30, unique=True, validators=[UPPER_CODE])
    name = models.CharField("nombre (Secondary Status)", max_length=80,
                            help_text="Texto que se exporta en «Secondary Status». Un sub-auxiliar se exporta «Padre - Nombre».")
    is_paid = models.BooleanField("tiempo pagado", null=True, blank=True, help_text="Vacío = igual que el estado primario.")
    is_productive = models.BooleanField("tiempo productivo", default=False, help_text="P. ej. ACW o back office.")
    max_minutes = models.PositiveSmallIntegerField("máximo por uso (min)", null=True, blank=True,
                                                   validators=[MinValueValidator(1), MaxValueValidator(720)],
                                                   help_text="Alerta en el tablero si el agente lo excede.")
    is_restricted = models.BooleanField("restringido por grupo", default=True,
                                        help_text="Si no está restringido, todos los grupos lo ven.")
    sort_order = models.PositiveSmallIntegerField("orden", default=100)
    is_active = models.BooleanField("activo", default=True)
    created_at = models.DateTimeField("creado", auto_now_add=True)

    class Meta:
        db_table = sql_table("acd", "acd_aux_code")
        ordering = ["primary_status__sort_order", "sort_order", "name"]
        verbose_name = "auxiliar / sub-auxiliar"
        verbose_name_plural = "auxiliares y sub-auxiliares"
        constraints = [
            models.CheckConstraint(condition=~Q(parent=models.F("id")), name="ck_acd_aux_not_self"),
        ]

    def __str__(self) -> str:
        return self.full_name

    @property
    def full_name(self) -> str:
        return f"{self.parent.name} - {self.name}" if self.parent_id else self.name

    @property
    def paid(self) -> bool:
        return self.primary_status.is_paid if self.is_paid is None else self.is_paid

    def clean(self):
        errors = {}
        if self.parent_id:
            parent = self.parent
            if parent.parent_id:
                errors["parent"] = "Solo hay un nivel de sub-auxiliares: elija un auxiliar (sin padre)."
            elif self.primary_status_id and parent.primary_status_id != self.primary_status_id:
                errors["primary_status"] = f"Un sub-auxiliar usa el mismo estado primario que su padre ({parent.primary_status.label})."
            if self.pk and parent.pk == self.pk:
                errors["parent"] = "Un auxiliar no puede ser su propio padre."
        if self.pk and self.parent_id and self.children.exists():
            errors["parent"] = "Este auxiliar tiene sub-auxiliares: no puede ser sub-auxiliar de otro."
        if self.primary_status_id and self.primary_status.code in (PrimaryStatus.OFFLINE, PrimaryStatus.IDLE):
            errors["primary_status"] = "Offline e Idle no llevan auxiliares."
        if errors:
            raise ValidationError(errors)


class AgentGroup(models.Model):
    code = models.CharField("código", max_length=30, unique=True, validators=[UPPER_CODE])
    name = models.CharField("nombre", max_length=120)
    division = models.ForeignKey(Division, on_delete=models.PROTECT, related_name="groups", verbose_name="división")
    description = models.CharField("descripción", max_length=300, blank=True)
    aux_codes = models.ManyToManyField(AuxCode, through="GroupAuxAccess", related_name="groups", blank=True,
                                       verbose_name="auxiliares permitidos")
    is_active = models.BooleanField("activo", default=True)
    created_at = models.DateTimeField("creado", auto_now_add=True)

    class Meta:
        db_table = sql_table("acd", "acd_agent_group")
        ordering = ["name"]
        verbose_name = "grupo de agentes"
        verbose_name_plural = "grupos de agentes"

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class GroupAuxAccess(models.Model):
    group = models.ForeignKey(AgentGroup, on_delete=models.CASCADE, related_name="access", verbose_name="grupo")
    aux_code = models.ForeignKey(AuxCode, on_delete=models.PROTECT, related_name="access", verbose_name="auxiliar")
    created_at = models.DateTimeField("otorgado", auto_now_add=True)

    class Meta:
        db_table = sql_table("acd", "acd_group_aux")
        verbose_name = "acceso a auxiliar"
        verbose_name_plural = "accesos a auxiliares"
        constraints = [models.UniqueConstraint(fields=["group", "aux_code"], name="uq_acd_group_aux")]

    def __str__(self) -> str:
        return f"{self.group.code} → {self.aux_code}"


class AgentMembership(models.Model):
    group = models.ForeignKey(AgentGroup, on_delete=models.PROTECT, related_name="members", verbose_name="grupo")
    employee = _employee_fk("acd_memberships")
    is_active = models.BooleanField("activo", default=True)
    created_at = models.DateTimeField("asignado", auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+", verbose_name="asignado por")
    ended_at = models.DateTimeField("retirado", null=True, blank=True)

    class Meta:
        db_table = sql_table("acd", "acd_agent_member")
        ordering = ["group_id", "employee_id"]
        verbose_name = "agente del grupo"
        verbose_name_plural = "agentes por grupo"
        constraints = [
            models.UniqueConstraint(fields=["employee"], condition=Q(is_active=True), name="uq_acd_member_active"),
        ]

    def __str__(self) -> str:
        return f"{self.employee_id} → {self.group_id}"


class Source(models.TextChoices):
    AGENT = "AGENT", "Agente"
    SUPERVISOR = "SUPERVISOR", "Supervisor"
    SYSTEM = "SYSTEM", "Sistema"


class AgentSession(models.Model):
    class SyncStatus(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        SYNCED = "SYNCED", "Enviado a tiempo real"
        SKIPPED = "SKIPPED", "Sin tiempo pagado"
        ERROR = "ERROR", "Con error"

    employee = _employee_fk("acd_sessions")
    group = models.ForeignKey(AgentGroup, on_delete=models.PROTECT, related_name="sessions", verbose_name="grupo")
    login_at = models.DateTimeField("inicio de sesión")
    logout_at = models.DateTimeField("cierre de sesión", null=True, blank=True)
    logout_source = models.CharField("cerrada por", max_length=10, choices=Source, blank=True)
    sync_status = models.CharField("tiempo real", max_length=8, choices=SyncStatus, default=SyncStatus.PENDING)
    sync_message = models.CharField("detalle", max_length=500, blank=True)
    paid_minutes = models.PositiveIntegerField("minutos pagados enviados", default=0)

    class Meta:
        db_table = sql_table("acd", "acd_agent_session")
        ordering = ["-login_at"]
        verbose_name = "sesión ACD"
        verbose_name_plural = "sesiones ACD"
        indexes = [models.Index(fields=["employee", "login_at"], name="ix_acd_session_emp_login")]
        constraints = [
            models.UniqueConstraint(fields=["employee"], condition=Q(logout_at__isnull=True), name="uq_acd_session_open"),
            models.CheckConstraint(condition=Q(logout_at__isnull=True) | Q(logout_at__gte=models.F("login_at")), name="ck_acd_session_dates"),
        ]

    def __str__(self) -> str:
        return f"{self.employee_id} {self.login_at:%Y-%m-%d %H:%M}"


class StatusSegment(models.Model):
    """Un tramo continuo en un estado (y auxiliar): Start Time / End Time / Duration en milisegundos."""

    id = models.BigAutoField(primary_key=True)
    employee = _employee_fk("acd_segments")
    session = models.ForeignKey(AgentSession, on_delete=models.PROTECT, null=True, blank=True, related_name="segments",
                                verbose_name="sesión")
    primary_status = models.ForeignKey(PrimaryStatus, on_delete=models.PROTECT, related_name="+", verbose_name="estado primario")
    aux_code = models.ForeignKey(AuxCode, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name="auxiliar")
    group = models.ForeignKey(AgentGroup, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name="grupo")
    division = models.ForeignKey(Division, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name="división")
    start_at = models.DateTimeField("Start Time")
    end_at = models.DateTimeField("End Time", null=True, blank=True)
    duration_ms = models.BigIntegerField("Duration (ms)", null=True, blank=True)
    source = models.CharField("origen", max_length=10, choices=Source, default=Source.AGENT)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+", verbose_name="registrado por")
    notes = models.CharField("notas", max_length=300, blank=True)

    class Meta:
        db_table = sql_table("acd", "acd_status_segment")
        ordering = ["employee_id", "start_at"]
        verbose_name = "segmento de estado"
        verbose_name_plural = "segmentos de estado"
        indexes = [
            models.Index(fields=["employee", "start_at"], name="ix_acd_segment_emp_start"),
            models.Index(fields=["start_at"], name="ix_acd_segment_start"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["employee"], condition=Q(end_at__isnull=True), name="uq_acd_segment_open"),
            models.CheckConstraint(condition=Q(end_at__isnull=True) | Q(end_at__gte=models.F("start_at")), name="ck_acd_segment_dates"),
            models.CheckConstraint(
                condition=Q(end_at__isnull=True, duration_ms__isnull=True) | Q(end_at__isnull=False, duration_ms__gte=0),
                name="ck_acd_segment_duration",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.employee_id} {self.primary_status_id} {self.start_at:%Y-%m-%d %H:%M:%S}"
