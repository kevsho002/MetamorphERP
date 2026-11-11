"""Fase 5 — Plataforma: parámetros de sesión, control del cliente web, sesiones activas y auditoría.

Es lo ÚNICO que se administra desde /admin/ además de la parametrización de
catálogos (plantillas, atributos, centros de costos). Las personas, cuentas y
expedientes se gestionan en la aplicación (React) con sus reglas de negocio.

Tablas administradas por migraciones de Django (esquema dbo, prefijo sys_).
"""

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class PlatformSettings(models.Model):
    """Fila única (pk=1) con la política de sesión y el estado del cliente web."""

    class Level(models.TextChoices):
        INFO = "info", "Información"
        WARNING = "warning", "Advertencia"
        DANGER = "danger", "Crítico"

    # ---------------------------------------------------------------- sesión
    idle_timeout_minutes = models.PositiveSmallIntegerField(
        "cierre por inactividad (minutos)",
        default=30,
        validators=[MinValueValidator(5), MaxValueValidator(480)],
        help_text="Sin actividad durante este tiempo, la sesión se cierra (5 a 480).",
    )
    max_session_hours = models.PositiveSmallIntegerField(
        "duración máxima de la sesión (horas)",
        default=8,
        validators=[MinValueValidator(1), MaxValueValidator(24)],
        help_text="Aunque haya actividad, se pide iniciar sesión de nuevo pasado este tiempo (1 a 24).",
    )
    max_sessions_per_user = models.PositiveSmallIntegerField(
        "sesiones simultáneas por usuario",
        default=0,
        validators=[MaxValueValidator(20)],
        help_text="0 = sin límite. Al superarlo, se cierra la sesión más antigua del usuario.",
    )
    idle_warning_seconds = models.PositiveSmallIntegerField(
        "aviso previo al cierre (segundos)",
        default=60,
        validators=[MinValueValidator(15), MaxValueValidator(600)],
        help_text="El navegador muestra una cuenta regresiva para «Seguir conectado» antes del cierre por inactividad.",
    )

    # ----------------------------------------------------------- cliente web
    maintenance_mode = models.BooleanField(
        "modo mantenimiento",
        default=False,
        help_text="Solo los administradores pueden ingresar y usar la API; el resto ve el mensaje de mantenimiento.",
    )
    maintenance_message = models.CharField(
        "mensaje de mantenimiento",
        max_length=300,
        default="Metamorph ERP está en mantenimiento programado. Intente de nuevo más tarde.",
    )
    announcement = models.CharField(
        "aviso general", max_length=300, blank=True, help_text="Banda visible para todos los usuarios (vacío = sin aviso)."
    )
    announcement_level = models.CharField("tipo de aviso", max_length=10, choices=Level, default=Level.INFO)
    max_document_mb = models.PositiveSmallIntegerField(
        "tamaño máximo de imágenes del expediente (MB)",
        default=5,
        validators=[MinValueValidator(1), MaxValueValidator(20)],
        help_text="Fotografías y documentos PNG/JPG/JPEG (1 a 20 MB).",
    )

    updated_at = models.DateTimeField("actualizado", auto_now=True)
    updated_by = models.CharField("actualizado por", max_length=150, blank=True, editable=False)

    class Meta:
        db_table = "sys_platform_settings"
        verbose_name = "parámetros de sesión y cliente web"
        verbose_name_plural = "parámetros de sesión y cliente web"
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="ck_platform_settings_singleton")]

    def __str__(self) -> str:
        return "Parámetros de sesión y cliente web"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        from apps.system.policy import invalidate

        invalidate()


class UserSession(models.Model):
    """Sesión iniciada por un usuario (control del cliente web: quién está conectado y desde dónde)."""

    class EndReason(models.TextChoices):
        LOGOUT = "LOGOUT", "Cierre por el usuario"
        IDLE = "IDLE", "Inactividad"
        MAX_AGE = "MAX_AGE", "Duración máxima"
        ADMIN = "ADMIN", "Cerrada por un administrador"
        REPLACED = "REPLACED", "Límite de sesiones simultáneas"
        PASSWORD = "PASSWORD", "Cambio o reseteo de contraseña"
        DEACTIVATED = "DEACTIVATED", "Cuenta desactivada"
        EXPIRED = "EXPIRED", "Vencida (navegador cerrado o cookie expirada)"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sessions", verbose_name="usuario"
    )
    session_key = models.CharField("clave de sesión", max_length=40, db_index=True)
    ip_address = models.GenericIPAddressField("IP", null=True, blank=True)
    user_agent = models.CharField("navegador", max_length=300, blank=True)
    started_at = models.DateTimeField("inicio", default=timezone.now)
    last_activity = models.DateTimeField("última actividad", default=timezone.now)
    ended_at = models.DateTimeField("fin", null=True, blank=True)
    end_reason = models.CharField("motivo de cierre", max_length=12, choices=EndReason, blank=True)

    class Meta:
        db_table = "sys_user_session"
        ordering = ["-started_at"]
        verbose_name = "sesión de usuario"
        verbose_name_plural = "sesiones de usuario"
        indexes = [models.Index(fields=["user", "ended_at"], name="ix_user_session_active")]

    def __str__(self) -> str:
        return f"{self.user} · {self.started_at:%d/%m/%Y %H:%M}"

    @property
    def is_active(self) -> bool:
        return self.ended_at is None


class AuditEvent(models.Model):
    """Registro de auditoría (audit trail): inmutable desde la aplicación y el admin."""

    class Category(models.TextChoices):
        AUTH = "AUTH", "Autenticación y sesiones"
        USERS = "USERS", "Cuentas de usuario"
        EMPLOYEES = "EMPLOYEES", "Empleados"
        DOCUMENTS = "DOCUMENTS", "Expediente digital"
        IMPORTS = "IMPORTS", "Cargas masivas"
        ROSTER = "ROSTER", "Roster operativo"
        CATALOGS = "CATALOGS", "Catálogos operativos"
        GENERAL_IDS = "GIDS", "General IDs"
        SCHEDULING = "SCHED", "Horarios, tiempo y cortes"
        PERSONNEL_ACTIONS = "PA", "Acciones de personal"
        ACD = "ACD", "Estados y auxiliares ACD"
        WFM = "WFM", "Segmentos y adherencia (WFM)"
        SYSTEM = "SYSTEM", "Parámetros del sistema"

    occurred_at = models.DateTimeField("fecha y hora", default=timezone.now, db_index=True)
    category = models.CharField("categoría", max_length=10, choices=Category)
    action = models.CharField("acción", max_length=50, db_index=True)
    success = models.BooleanField("exitosa", default=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
        verbose_name="usuario",
    )
    actor_username = models.CharField("usuario (texto)", max_length=150, blank=True)
    target_type = models.CharField("tipo de objeto", max_length=40, blank=True)
    target_id = models.CharField("objeto", max_length=64, blank=True, db_index=True)
    summary = models.CharField("descripción", max_length=500)
    details = models.JSONField("detalle", default=dict, blank=True, encoder=DjangoJSONEncoder)
    ip_address = models.GenericIPAddressField("IP", null=True, blank=True)
    user_agent = models.CharField("navegador", max_length=300, blank=True)

    class Meta:
        db_table = "sys_audit_event"
        ordering = ["-occurred_at", "-id"]
        verbose_name = "evento de auditoría"
        verbose_name_plural = "registro de auditoría"
        indexes = [models.Index(fields=["target_type", "target_id", "occurred_at"], name="ix_audit_event_target")]

    def __str__(self) -> str:
        return f"{self.occurred_at:%d/%m/%Y %H:%M} · {self.action} · {self.actor_username or '—'}"
