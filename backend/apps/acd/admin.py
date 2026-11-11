"""/admin/ › Estados y auxiliares ACD: divisiones, estados operativos, auxiliares / sub-auxiliares y grupos.

* Los estados operativos (presencias primarias) tienen códigos fijos: se ajustan etiquetas, colores y banderas.
* Auxiliares y sub-auxiliares (un nivel) bajo un estado primario; «restringido» = solo los grupos con acceso lo ven.
* Grupos / perfiles: división y auxiliares permitidos (también desde la pantalla «Grupos y auxiliares» de WFM).
* Los segmentos de estado y las sesiones son de solo lectura (los genera el flujo del agente). Nada se borra.
"""

from django.contrib import admin

from apps.acd.models import (
    AgentGroup, AgentMembership, AgentSession, AuxCode, Division, GroupAuxAccess, PrimaryStatus, StatusSegment,
)
from apps.system.audit import Category, record


class _AuditedAdmin(admin.ModelAdmin):
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if form.changed_data or not change:
            record(
                "acd_config_changed" if change else "acd_config_created", Category.ACD,
                f"{obj._meta.verbose_name.capitalize()} «{obj}» {'modificado' if change else 'creado'} desde /admin/"
                + (f" (campos: {', '.join(form.changed_data)})" if change else "") + ".",
                request=request, target_type=obj.__class__.__name__, target_id=str(obj.pk),
            )

    def has_delete_permission(self, request, obj=None):
        return False


class _ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Division)
class DivisionAdmin(_AuditedAdmin):
    list_display = ("code", "name", "division_uid", "is_active")
    readonly_fields = ("division_uid", "created_at")
    search_fields = ("code", "name")


@admin.register(PrimaryStatus)
class PrimaryStatusAdmin(_AuditedAdmin):
    list_display = ("code", "label", "name_es", "is_logged_in", "is_productive", "is_paid", "agent_selectable", "sort_order", "is_active")
    list_editable = ("sort_order",)

    def get_readonly_fields(self, request, obj=None):
        return ("code",) if obj else ()

    def has_add_permission(self, request):
        return False  # códigos fijos (los usa el flujo del agente)


class AuxChildInline(admin.TabularInline):
    model = AuxCode
    fk_name = "parent"
    extra = 0
    fields = ("code", "name", "primary_status", "is_paid", "is_productive", "max_minutes", "is_restricted", "sort_order", "is_active")
    verbose_name = "sub-auxiliar"
    verbose_name_plural = "sub-auxiliares"

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuxCode)
class AuxCodeAdmin(_AuditedAdmin):
    list_display = ("code", "__str__", "primary_status", "parent", "is_paid", "is_productive", "max_minutes", "is_restricted", "is_active")
    list_filter = ("primary_status", "is_restricted", "is_active")
    search_fields = ("code", "name")
    inlines = [AuxChildInline]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "parent":
            kwargs["queryset"] = AuxCode.objects.filter(parent__isnull=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class GroupAuxInline(admin.TabularInline):
    model = GroupAuxAccess
    extra = 0
    autocomplete_fields = ("aux_code",)
    verbose_name_plural = "auxiliares permitidos (el padre incluye sus sub-auxiliares)"


class MemberInline(admin.TabularInline):
    model = AgentMembership
    extra = 0
    fields = ("employee", "is_active", "created_at", "ended_at")
    readonly_fields = ("employee", "created_at", "ended_at")

    def get_queryset(self, request):
        return super().get_queryset(request).filter(is_active=True)

    def has_add_permission(self, request, obj=None):
        return False  # se asignan desde la pantalla de WFM (valida sesiones abiertas)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AgentGroup)
class AgentGroupAdmin(_AuditedAdmin):
    list_display = ("code", "name", "division", "is_active")
    list_filter = ("division", "is_active")
    search_fields = ("code", "name")
    inlines = [GroupAuxInline, MemberInline]


@admin.register(AgentSession)
class AgentSessionAdmin(_ReadOnlyAdmin):
    list_display = ("employee_id", "group", "login_at", "logout_at", "logout_source", "sync_status", "paid_minutes")
    list_filter = ("group", "sync_status", "logout_source")
    date_hierarchy = "login_at"


@admin.register(StatusSegment)
class StatusSegmentAdmin(_ReadOnlyAdmin):
    list_display = ("employee_id", "primary_status", "aux_code", "start_at", "end_at", "duration_ms", "source")
    list_filter = ("primary_status", "source", "group")
    date_hierarchy = "start_at"
