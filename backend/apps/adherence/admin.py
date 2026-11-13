"""/admin/ › Segmentos de actividad y adherencia (WFM).

* Tipos de actividad con sus estados ACD (rol primario / secundario): también desde la pantalla «Actividades».
* Segmentos, justificaciones y resultados se consultan aquí en solo lectura: se gestionan desde las pantallas de WFM
  (que validan contenedor, traslapes, AP aprobada y cortes cerrados).
"""

from django.contrib import admin

from apps.adherence.models import (
    ActivityClient, ActivityStatusRule, ActivityType, AdherenceDay, AdherenceException, ChangeRequest, Deviation, GridSetting,
    ScheduleSegment, UtilizationCategory,
)
from apps.system.audit import Category, record


class _ReadOnly(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class RuleInline(admin.TabularInline):
    model = ActivityStatusRule
    extra = 0
    autocomplete_fields = ()


class ClientInline(admin.TabularInline):
    model = ActivityClient
    extra = 0
    verbose_name_plural = "cuentas donde se ofrece (vacío = todas)"


@admin.register(GridSetting)
class GridSettingAdmin(admin.ModelAdmin):
    list_display = ("__str__", "group", "interval_minutes", "snap_seconds", "margin_hours", "lateness_grace_seconds",
                    "ap_required_seconds", "updated_at")
    readonly_fields = ("updated_at", "updated_by")


@admin.register(ActivityType)
class ActivityTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "utilization_category", "category", "icon", "is_paid", "is_billable", "requires_acd_login",
                    "requires_ap", "system_role", "is_default", "is_active", "sort_order")
    list_filter = ("utilization_category", "category", "is_paid", "is_billable", "requires_ap", "requires_acd_login", "is_active")
    search_fields = ("code", "name")
    inlines = [RuleInline, ClientInline]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        record("adh_activity_updated" if change else "adh_activity_created", Category.WFM,
               f"Actividad «{obj}» {'modificada' if change else 'creada'} desde /admin/.", request=request,
               target_type="ActivityType", target_id=obj.code)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ScheduleSegment)
class ScheduleSegmentAdmin(_ReadOnly):
    list_display = ("employee", "shift_date", "start_at", "end_at", "activity", "origin", "is_locked", "personnel_action")
    list_filter = ("origin", "is_locked", "activity", "shift_date")
    search_fields = ("employee__employee_code",)


@admin.register(AdherenceException)
class AdherenceExceptionAdmin(_ReadOnly):
    list_display = ("employee", "start_at", "end_at", "personnel_action", "is_paid", "reason")
    search_fields = ("employee__employee_code", "personnel_action__folio")


@admin.register(AdherenceDay)
class AdherenceDayAdmin(_ReadOnly):
    list_display = ("employee", "shift_date", "adherence_pct", "conformance_pct", "paid_valid_seconds", "unpaid_excess_seconds", "computed_at")
    list_filter = ("shift_date",)
    search_fields = ("employee__employee_code",)


@admin.register(Deviation)
class DeviationAdmin(_ReadOnly):
    list_display = ("employee", "shift_date", "kind", "start_at", "end_at", "seconds", "expected_activity", "actual_status")
    list_filter = ("kind", "shift_date")
    search_fields = ("employee__employee_code",)


@admin.register(UtilizationCategory)
class UtilizationCategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "department", "sort_order", "is_active")
    list_filter = ("department", "is_active")
    search_fields = ("code", "name")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ChangeRequest)
class ChangeRequestAdmin(_ReadOnly):
    list_display = ("id", "employee", "shift_date", "kind", "status", "requester_role", "requested_by", "requested_at", "decided_by")
    list_filter = ("status", "kind", "requester_role")
    search_fields = ("employee__employee_code",)
