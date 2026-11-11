"""/admin/ de plataforma: parámetros de sesión, control del cliente web (sesiones activas) y auditoría."""

import csv

from django.contrib import admin, messages
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from apps.system import sessions
from apps.system.audit import Category, record
from apps.system.models import AuditEvent, PlatformSettings, UserSession

_AUDITED_FIELDS = (
    "idle_timeout_minutes", "max_session_hours", "max_sessions_per_user", "idle_warning_seconds",
    "maintenance_mode", "maintenance_message", "announcement", "announcement_level", "max_document_mb",
)


@admin.register(PlatformSettings)
class PlatformSettingsAdmin(admin.ModelAdmin):
    """Fila única: la lista redirige directamente al formulario."""

    fieldsets = (
        (
            "Parámetros de sesión",
            {"fields": ("idle_timeout_minutes", "idle_warning_seconds", "max_session_hours", "max_sessions_per_user")},
        ),
        (
            "Control del cliente web",
            {"fields": ("maintenance_mode", "maintenance_message", "announcement", "announcement_level", "max_document_mb")},
        ),
        ("Registro", {"fields": ("updated_at", "updated_by")}),
    )
    readonly_fields = ("updated_at", "updated_by")

    def changelist_view(self, request, extra_context=None):
        obj, _ = PlatformSettings.objects.get_or_create(pk=1)
        return HttpResponseRedirect(reverse("admin:system_platformsettings_change", args=[obj.pk]))

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        before = PlatformSettings.objects.filter(pk=1).values(*_AUDITED_FIELDS).first() or {}
        obj.updated_by = request.user.username
        super().save_model(request, obj, form, change)
        diff = {f: {"antes": before.get(f), "despues": getattr(obj, f)} for f in _AUDITED_FIELDS if before.get(f) != getattr(obj, f)}
        if diff:
            record(
                "settings_changed",
                Category.SYSTEM,
                f"Parámetros de sesión/cliente web modificados: {', '.join(PlatformSettings._meta.get_field(f).verbose_name for f in diff)}.",
                request=request,
                target_type="platform_settings",
                target_id="1",
                details=diff,
            )


class ActiveFilter(admin.SimpleListFilter):
    title = "estado"
    parameter_name = "estado"

    def lookups(self, request, model_admin):
        return [("activa", "Activas"), ("cerrada", "Cerradas")]

    def queryset(self, request, queryset):
        if self.value() == "activa":
            return queryset.filter(ended_at__isnull=True)
        if self.value() == "cerrada":
            return queryset.filter(ended_at__isnull=False)
        return queryset


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "status", "ip_address", "short_agent", "started_at", "last_activity", "ended_at", "end_reason")
    list_filter = (ActiveFilter, "end_reason", "started_at")
    search_fields = ("user__username", "ip_address")
    list_select_related = ("user",)
    date_hierarchy = "started_at"
    actions = ["close_sessions"]
    fields = ("user", "session_key_hint", "ip_address", "user_agent", "started_at", "last_activity", "ended_at", "end_reason")
    readonly_fields = fields

    def changelist_view(self, request, extra_context=None):
        sessions.sweep_expired()  # refleja las sesiones vencidas antes de listar
        return super().changelist_view(request, extra_context)

    @admin.display(description="estado", boolean=True)
    def status(self, obj):
        return obj.is_active

    @admin.display(description="navegador")
    def short_agent(self, obj):
        return (obj.user_agent[:60] + "…") if len(obj.user_agent) > 60 else obj.user_agent

    @admin.display(description="clave de sesión")
    def session_key_hint(self, obj):
        return f"…{obj.session_key[-6:]}"  # nunca se muestra completa (permitiría suplantar la sesión)

    @admin.action(description="Cerrar las sesiones seleccionadas")
    def close_sessions(self, request, queryset):
        users = sorted({s.user.username for s in queryset.filter(ended_at__isnull=True).select_related("user")})
        closed = sessions.end_sessions(queryset, sessions.Reason.ADMIN)
        if closed:
            record(
                "sessions_closed",
                Category.AUTH,
                f"Se cerraron {closed} sesión(es) desde el panel de administración.",
                request=request,
                target_type="user_session",
                details={"usuarios": users, "cantidad": closed},
            )
        self.message_user(request, f"Sesiones cerradas: {closed}.", messages.SUCCESS if closed else messages.INFO)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    """Solo lectura para todos (incluido el superusuario): el registro de auditoría no se edita ni se borra."""

    list_display = ("occurred_at", "category", "action", "success", "actor_username", "target", "summary", "ip_address")
    list_filter = ("category", "success", "action", "occurred_at")
    search_fields = ("actor_username", "target_id", "summary", "action", "ip_address")
    date_hierarchy = "occurred_at"
    list_per_page = 50
    actions = ["export_csv"]
    fields = (
        "occurred_at", "category", "action", "success", "actor", "actor_username", "target_type", "target_id",
        "summary", "pretty_details", "ip_address", "user_agent",
    )
    readonly_fields = fields

    @admin.display(description="objeto")
    def target(self, obj):
        return f"{obj.target_type}:{obj.target_id}" if obj.target_type else "—"

    @admin.display(description="detalle")
    def pretty_details(self, obj):
        import json

        return format_html("<pre style='white-space:pre-wrap'>{}</pre>", json.dumps(obj.details, ensure_ascii=False, indent=2, default=str))

    @admin.action(description="Exportar a CSV")
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="auditoria_{timezone.localdate():%Y%m%d}.csv"'
        response.write("﻿")
        writer = csv.writer(response)
        writer.writerow(["fecha_utc", "categoria", "accion", "exitosa", "usuario", "objeto", "descripcion", "ip"])
        for e in queryset.order_by("occurred_at"):
            writer.writerow([
                e.occurred_at.isoformat(), e.category, e.action, e.success, e.actor_username,
                f"{e.target_type}:{e.target_id}" if e.target_type else "", e.summary, e.ip_address or "",
            ])
        return response

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
