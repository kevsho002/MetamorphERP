"""Administración de la Fase 20 (consulta y parámetros). El cálculo, el cierre y el inventario se operan desde la API /
React; las boletas y las líneas son de solo lectura (su contenido lo protege SQL Server)."""

from django.contrib import admin

from apps.payroll.models import PayConcept, PayrollLine, PayrollRun, PayrollSetting, Payslip, PayslipBatch


@admin.register(PayrollSetting)
class PayrollSettingAdmin(admin.ModelAdmin):
    list_display = ("name", "country_id", "effective_start_date", "effective_end_date", "days_per_month", "hours_per_day",
                    "overtime_surcharge_percent", "vacation_premium_percent", "is_active")
    list_filter = ("is_active",)


@admin.register(PayConcept)
class PayConceptAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "kind", "source", "calculation", "action_type_code", "action_attribute_key",
                    "affects_social_security", "affects_income_tax", "is_active")
    list_filter = ("kind", "source", "is_active")


class _ReadOnly(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PayrollRun)
class PayrollRunAdmin(_ReadOnly):
    list_display = ("payroll_id", "pay_period", "employees", "calculated_at", "calculated_by", "paid_at")


@admin.register(PayrollLine)
class PayrollLineAdmin(_ReadOnly):
    list_display = ("payroll_id", "employee_id", "kind", "code", "label", "quantity", "amount", "personnel_action")
    list_filter = ("kind", "code")


@admin.register(PayslipBatch)
class PayslipBatchAdmin(_ReadOnly):
    list_display = ("code", "payroll_id", "cost_center_id", "archive_location", "created_at")


@admin.register(Payslip)
class PayslipAdmin(_ReadOnly):
    list_display = ("folio", "employee_id", "period_start", "period_end", "net_pay", "printed_at", "print_count", "signed_on",
                    "archived_at", "archive_location")
    list_filter = ("pay_frequency", "period_end")
    search_fields = ("folio",)
