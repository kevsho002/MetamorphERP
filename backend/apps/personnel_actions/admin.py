"""/admin/ › Acciones de personal: parametrización de TIPOS de AP (campos EAV, cadena de firmas y efecto).

Las AP se elaboran, firman y consultan en React (menú «Acciones de personal» y pestaña del expediente). Aquí
solo se consultan, en modo lectura: el folio, el contenido sellado y las firmas no se editan.
"""

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms.models import BaseInlineFormSet

from apps.personnel_actions.models import (
    ActionAttribute, ActionSignature, ActionType, ApprovalStep, DataType, Effect, PersonnelAction, ScheduleMode,
)
from apps.system.audit import Category, record


class AttributeFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        kept = [f.cleaned_data for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")]
        effect = self.instance.effect
        schedules = [d for d in kept if d.get("data_type") == DataType.SCHEDULE and d.get("is_active", True)]
        if effect == Effect.SCHEDULE and len(schedules) != 1:
            raise ValidationError("Un tipo que asigna horario necesita exactamente UN campo «Horario semanal» activo y obligatorio.")
        if effect == Effect.SCHEDULE and schedules and not schedules[0].get("required"):
            raise ValidationError("El campo «Horario semanal» debe ser obligatorio.")
        if effect == Effect.SCHEDULE and self.instance.schedule_mode == ScheduleMode.ADDITIONAL and not any(
            d.get("key") == "vigente_hasta" and d.get("data_type") == DataType.DATE and d.get("required") and d.get("is_active", True) for d in kept
        ):
            raise ValidationError("Una asignación ADICIONAL de horario necesita el campo de fecha obligatorio «vigente_hasta» (fin de la asignación).")
        if effect == Effect.SALARY and not any(d.get("key") == "new_base_salary" and d.get("data_type") == DataType.DECIMAL for d in kept):
            raise ValidationError("Un tipo que ajusta el salario necesita el campo decimal «new_base_salary».")


class AttributeInline(admin.TabularInline):
    model = ActionAttribute
    formset = AttributeFormSet
    extra = 0
    fields = ("display_order", "key", "label", "data_type", "required", "choices", "min_value", "max_value", "max_length", "help_text", "is_active")

    def has_delete_permission(self, request, obj=None):
        return False  # los valores guardados lo referencian: se desactiva


class StepInline(admin.TabularInline):
    model = ApprovalStep
    extra = 0
    fields = ("order", "label", "role")


@admin.register(ActionType)
class ActionTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "category", "effect", "schedule_mode", "folio_prefix", "is_initial_schedule", "steps_label", "is_active")
    list_filter = ("category", "effect", "is_active")
    search_fields = ("code", "name")
    inlines = [AttributeInline, StepInline]
    fieldsets = (
        (None, {"fields": ("code", "name", "description", "category", "effect", "schedule_mode", "folio_prefix", "is_initial_schedule", "display_order", "is_active")}),
        ("Permisos y firmas", {"fields": ("view_permission", "create_permission", "creator_signs_first_step", "require_distinct_signers")}),
    )

    @admin.display(description="cadena de firmas")
    def steps_label(self, obj):
        return " → ".join(f"{s.label} ({s.get_role_display()})" for s in obj.steps.all()) or "Sin firmas (se aprueba al enviarse)"

    def get_readonly_fields(self, request, obj=None):
        return ("code", "folio_prefix") if obj and obj.actions.exists() else ()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        record("pa_type_changed" if change else "pa_type_created", Category.PERSONNEL_ACTIONS,
               f"Tipo de AP «{obj.name}» ({obj.code}) {'modificado' if change else 'creado'} desde /admin/.",
               request=request, target_type="ActionType", target_id=obj.code)


class SignatureInline(admin.TabularInline):
    model = ActionSignature
    extra = 0
    fields = ("step_order", "step_label", "signer_username", "signer_role", "decision", "comment", "signed_at", "signature")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(PersonnelAction)
class PersonnelActionAdmin(admin.ModelAdmin):
    """Solo lectura: las AP se gestionan en React."""

    list_display = ("folio", "action_type", "employee", "effective_date", "status", "created_by", "created_at")
    list_filter = ("status", "action_type")
    search_fields = ("folio", "employee__employee_code", "justification")
    date_hierarchy = "effective_date"
    inlines = [SignatureInline]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in PersonnelAction._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD")

    def has_delete_permission(self, request, obj=None):
        return False
