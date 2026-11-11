"""Catálogos core en /admin/: países (solo lectura, los gobierna database/scripts) y centros de costos."""

from django import forms
from django.contrib import admin

from apps.common.models import CostCenter, Country


class CostCenterInline(admin.TabularInline):
    model = CostCenter
    fk_name = "country"
    fields = ("code", "name", "is_active", "effective_start_date", "effective_end_date")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    """core.catCountry es SQL-first (script 001/090): aquí solo se consulta."""

    list_display = ("country_code", "country_name", "id_prefix", "currency_code", "is_active", "effective_start_date", "effective_end_date")
    list_filter = ("is_active",)
    search_fields = ("country_code", "country_name")
    inlines = [CostCenterInline]

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in Country._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class CostCenterForm(forms.ModelForm):
    class Meta:
        model = CostCenter
        fields = ("country", "code", "name", "parent", "effective_start_date", "effective_end_date", "is_active")

    def clean(self):
        cleaned = super().clean()
        parent, country = cleaned.get("parent"), cleaned.get("country") or getattr(self.instance, "country", None)
        if parent and country and parent.country_id != country.country_id:
            self.add_error("parent", "El centro de costos padre debe ser del mismo país.")
        if parent and self.instance.pk and parent.pk == self.instance.pk:
            self.add_error("parent", "Un centro de costos no puede ser su propio padre.")
        code = cleaned.get("code")
        if code:
            cleaned["code"] = code.strip().upper()
        return cleaned


@admin.register(CostCenter)
class CostCenterAdmin(admin.ModelAdmin):
    form = CostCenterForm
    list_display = ("code", "name", "country", "parent", "is_active", "effective_start_date", "effective_end_date")
    list_filter = ("country", "is_active")
    search_fields = ("code", "name")
    list_select_related = ("country", "parent")
    raw_id_fields = ("parent",)

    def get_readonly_fields(self, request, obj=None):
        # FK compuesta (CostCenterId, CountryId) desde hcm.Employee: el país no cambia una vez creado.
        return ("country", "created_at", "created_by") if obj else ("created_at", "created_by")

    def has_delete_permission(self, request, obj=None):
        return False  # se desactiva (is_active / fecha fin), no se elimina
