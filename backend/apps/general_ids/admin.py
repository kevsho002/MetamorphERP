"""/admin/ › General IDs: SOLO parametrización (herramientas de origen y tipos de ID).

Los IDs de cada empleado se registran en la aplicación (pestaña «General IDs» del expediente),
con vigencias, validaciones, auditoría y RBAC; aquí no se editan. Las restricciones por cliente /
marca se configuran en la ficha del cliente y de la marca (Catálogos operativos); en el tipo se
muestran como resumen.
"""

from django.contrib import admin
from django.db.models import Count, Q
from django.utils.html import format_html_join

from apps.general_ids.models import GeneralIdType, SourceTool
from apps.system.audit import Category, record


class _AuditedAdmin(admin.ModelAdmin):
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if form.changed_data or not change:
            record(
                "gid_config_changed" if change else "gid_config_created", Category.GENERAL_IDS,
                f"{obj._meta.verbose_name.capitalize()} «{obj}» {'modificado' if change else 'creado'}"
                f"{': ' + ', '.join(form.changed_data) if change else ''}.",
                request=request, target=obj, details={"model": obj._meta.model_name, "fields": form.changed_data},
            )

    def has_delete_permission(self, request, obj=None):
        return False  # se desactivan: los IDs históricos los referencian


@admin.register(SourceTool)
class SourceToolAdmin(_AuditedAdmin):
    list_display = ("name", "code", "category", "vendor", "type_count", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("code", "name", "vendor")
    readonly_fields = ("created_at", "updated_at")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_types=Count("id_types"))

    @admin.display(description="tipos de ID", ordering="_types")
    def type_count(self, obj):
        return obj._types

    def get_readonly_fields(self, request, obj=None):
        return (*self.readonly_fields, "code") if obj else self.readonly_fields


@admin.register(GeneralIdType)
class GeneralIdTypeAdmin(_AuditedAdmin):
    list_display = ("name", "code", "tool", "scope_level", "allow_multiple_active", "unique_value", "applies_to", "active_ids", "is_active")
    list_filter = ("tool", "scope_level", "is_active")
    search_fields = ("code", "name", "tool__name")
    list_select_related = ("tool",)
    autocomplete_fields = ("tool",)
    readonly_fields = ("applies_to_detail", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("code", "name", "tool", "description", "display_order", "is_active")}),
        ("Registro y cardinalidad", {"fields": ("scope_level", "allow_multiple_active", "unique_value", "applies_to_detail")}),
        ("Formato del valor", {"fields": ("pattern", "pattern_message", "example", "max_length", "transform")}),
        (None, {"fields": ("created_at", "updated_at")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _active=Count("assignments", filter=Q(assignments__effective_end__isnull=True))
        )

    @admin.display(description="IDs «Now»", ordering="_active")
    def active_ids(self, obj):
        return obj._active

    @admin.display(description="aplica a")
    def applies_to(self, obj):
        clients = obj.client_scopes.count()
        brands = obj.brand_scopes.count()
        if not clients and not brands:
            return "Todos"
        return f"{clients} cliente(s), {brands} marca(s)"

    @admin.display(description="restricciones (se configuran en Clientes / Marcas)")
    def applies_to_detail(self, obj):
        if not obj.pk:
            return "—"
        rows = [(f"Cliente «{s.client.name}» y todas sus marcas",) for s in obj.client_scopes.select_related("client")]
        rows += [(f"Marca «{s.brand.name}» ({s.brand.client.name})",) for s in obj.brand_scopes.select_related("brand__client")]
        if not rows:
            return "Sin restricciones: aplica a todos los clientes y marcas."
        return format_html_join("", "<div>• {}</div>", rows)

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.assignments.exists():
            # Con IDs registrados: el código, la herramienta y el formato no cambian (rompería los JOINs históricos).
            return (*self.readonly_fields, "code", "tool", "transform")
        return (*self.readonly_fields, "code") if obj else self.readonly_fields
