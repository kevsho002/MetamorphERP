"""Fase 25 — Comunicados corporativos (periódico virtual) con acuse de recibo obligatorio y compliance.

    com_announcement           comunicado: categoría (noticias, blog, formularios, RRHH, planillas, cultura, operaciones,
                               seguridad, cambio organizacional), audiencia por rol, vigencia, fijado y acuse obligatorio
    com_announcement_ack       acuse de recibo de un usuario: fecha, IP y la huella SHA-256 del contenido que confirmó
    com_compliance_snapshot    foto del cumplimiento (audiencia, confirmados, pendientes, vencidos): diaria, al vencer el
                               plazo, al archivar o manual; base de los reportes automáticos de compliance

Comunicados CRÍTICOS (seguridad y cambios organizacionales): el acuse es obligatorio y, una vez publicados, su contenido
queda congelado (SQL Server: trigger 50122), de modo que cada acuse prueba exactamente qué texto se confirmó.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.common.fields import sql_table


class Category(models.TextChoices):
    NEWS = "NEWS", "Noticias"
    BLOG = "BLOG", "Blog"
    FORM = "FORM", "Formularios"
    HR = "HR", "Avisos de RRHH"
    PAYROLL = "PAYROLL", "Planillas"
    CULTURE = "CULTURE", "Cultura"
    OPS = "OPS", "Operaciones"
    SECURITY = "SECURITY", "Seguridad"
    ORG_CHANGE = "ORG_CHANGE", "Cambio organizacional"


# Categorías críticas: acuse de recibo obligatorio y contenido congelado al publicar.
CRITICAL_CATEGORIES = frozenset({Category.SECURITY, Category.ORG_CHANGE})


class Status(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    PUBLISHED = "PUBLISHED", "Publicado"
    ARCHIVED = "ARCHIVED", "Archivado"


class Announcement(models.Model):
    title = models.CharField("título", max_length=200)
    summary = models.CharField("resumen", max_length=400, blank=True)
    body = models.TextField("contenido", max_length=20000)
    category = models.CharField("categoría", max_length=12, choices=Category, default=Category.NEWS, db_index=True)
    requires_ack = models.BooleanField("requiere acuse de recibo", default=False,
                                       help_text="Obligatorio en comunicados de Seguridad y Cambio organizacional.")
    status = models.CharField("estado", max_length=10, choices=Status, default=Status.DRAFT, db_index=True)
    pinned = models.BooleanField("fijado", default=False)
    link_url = models.URLField("enlace (formulario o recurso)", max_length=500, blank=True)
    link_label = models.CharField("texto del enlace", max_length=80, blank=True)
    audience_roles = models.JSONField("audiencia (roles)", default=list, blank=True, help_text="Vacío = todos los usuarios.")
    ack_due_date = models.DateField("plazo del acuse", null=True, blank=True)
    expires_at = models.DateField("visible hasta", null=True, blank=True)
    content_hash = models.CharField("huella del contenido (SHA-256)", max_length=64, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="announcements_created",
                                   verbose_name="elaborado por")
    created_at = models.DateTimeField("creado", default=timezone.now)
    updated_at = models.DateTimeField("actualizado", auto_now=True)
    published_at = models.DateTimeField("publicado", null=True, blank=True, db_index=True)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                     related_name="announcements_published", verbose_name="publicado por")
    archived_at = models.DateTimeField("archivado", null=True, blank=True)
    archived_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name="announcements_archived", verbose_name="archivado por")

    class Meta:
        db_table = sql_table("com", "com_announcement")
        ordering = ["-pinned", "-published_at", "-id"]
        verbose_name = "comunicado"
        verbose_name_plural = "comunicados"
        constraints = [
            models.CheckConstraint(condition=Q(category__in=Category.values), name="ck_com_announcement_category"),
            models.CheckConstraint(condition=Q(status__in=Status.values), name="ck_com_announcement_status"),
            models.CheckConstraint(condition=~Q(category__in=sorted(CRITICAL_CATEGORIES)) | Q(requires_ack=True),
                                   name="ck_com_announcement_critical_ack"),
            models.CheckConstraint(condition=Q(status="DRAFT") | Q(published_at__isnull=False), name="ck_com_announcement_published"),
            models.CheckConstraint(condition=~Q(status="ARCHIVED") | Q(archived_at__isnull=False), name="ck_com_announcement_archived"),
        ]
        indexes = [models.Index(fields=["status", "category", "published_at"], name="ix_com_announcement_feed")]

    def __str__(self) -> str:
        return self.title

    @property
    def is_critical(self) -> bool:
        return self.category in CRITICAL_CATEGORIES


class AnnouncementAck(models.Model):
    announcement = models.ForeignKey(Announcement, on_delete=models.PROTECT, related_name="acks", verbose_name="comunicado")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="announcement_acks",
                             verbose_name="usuario")
    username = models.CharField("usuario (texto)", max_length=150)
    acknowledged_at = models.DateTimeField("confirmado", default=timezone.now)
    content_hash = models.CharField("huella confirmada", max_length=64)
    ip_address = models.GenericIPAddressField("IP", null=True, blank=True)
    user_agent = models.CharField("navegador", max_length=300, blank=True)

    class Meta:
        db_table = sql_table("com", "com_announcement_ack")
        ordering = ["-acknowledged_at"]
        verbose_name = "acuse de recibo"
        verbose_name_plural = "acuses de recibo"
        constraints = [models.UniqueConstraint(fields=["announcement", "user"], name="uq_com_ack_user")]

    def __str__(self) -> str:
        return f"{self.username} · {self.announcement_id}"


class ComplianceSnapshot(models.Model):
    class Trigger(models.TextChoices):
        DAILY = "DAILY", "Reporte diario automático"
        DEADLINE = "DEADLINE", "Vencimiento del plazo"
        ARCHIVE = "ARCHIVE", "Al archivar"
        MANUAL = "MANUAL", "Manual"

    announcement = models.ForeignKey(Announcement, on_delete=models.PROTECT, related_name="snapshots", verbose_name="comunicado")
    taken_at = models.DateTimeField("fecha", default=timezone.now)
    trigger = models.CharField("origen", max_length=8, choices=Trigger)
    audience = models.PositiveIntegerField("audiencia")
    acknowledged = models.PositiveIntegerField("confirmados")
    pending = models.PositiveIntegerField("pendientes")
    overdue = models.PositiveIntegerField("vencidos")
    compliance_pct = models.DecimalField("cumplimiento (%)", max_digits=5, decimal_places=2)
    pending_users = models.JSONField("pendientes (usuarios)", default=list, blank=True)

    class Meta:
        db_table = sql_table("com", "com_compliance_snapshot")
        ordering = ["-taken_at", "-id"]
        verbose_name = "reporte de cumplimiento"
        verbose_name_plural = "reportes de cumplimiento"
        constraints = [models.CheckConstraint(condition=Q(trigger__in=["DAILY", "DEADLINE", "ARCHIVE", "MANUAL"]),
                                              name="ck_com_snapshot_trigger")]

    def __str__(self) -> str:
        return f"{self.announcement_id} · {self.taken_at:%d/%m/%Y %H:%M} · {self.compliance_pct} %"
