"""/admin/ del roster: SOLO parametrización (dimensiones, sus elementos y los atributos dinámicos).

Las asignaciones por empleado se registran en la aplicación (sección Roster del expediente),
con fecha efectiva, validaciones e historial; aquí no se editan.

Fase 7: los elementos de las dimensiones CLIENT, BRAND, LOB y SUB_LOB se administran en
«Catálogos operativos» (tablas ops_*), que los sincronizan; aquí se muestran solo como lectura.
"""

from django.contrib import admin
from django.db.models import Count

from apps.roster.models import CATALOG_DIMENSIONS, RosterAttribute, RosterDimension, RosterDimensionItem


class RosterDimensionItemInline(admin.TabularInline):
    model = RosterDimensionItem
    fk_name = "dimension"
    fields = ("code", "name", "parent", "country", "is_active")
    raw_id_fields = ("parent",)
    extra = 0
    show_change_link = True

    def has_delete_permission(self, request, obj=None):
        return False  # se desactivan; sus asignaciones históricas deben seguir legibles

    def has_add_permission(self, request, obj=None):
        return not (obj and obj.code in CATALOG_DIMENSIONS)

    def has_change_permission(self, request, obj=None):
        return not (obj and obj.code in CATALOG_DIMENSIONS)


@admin.register(RosterDimension)
class RosterDimensionAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "parent", "is_active", "item_count")
    list_filter = ("is_active",)
    search_fields = ("code", "name")
    inlines = [RosterDimensionItemInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n=Count("items"))

    @admin.display(description="elementos", ordering="n")
    def item_count(self, obj):
        return obj.n

    def get_readonly_fields(self, request, obj=None):
        return ("code", "parent") if obj else ()  # cambiarlos rompería la jerarquía existente

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RosterDimensionItem)
class RosterDimensionItemAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "dimension", "parent", "country", "is_active")
    list_filter = ("dimension", "is_active", "country")
    search_fields = ("code", "name", "parent__name")
    list_select_related = ("dimension", "parent", "country")
    autocomplete_fields = ("parent",)

    def get_readonly_fields(self, request, obj=None):
        return ("dimension", "code") if obj and obj.assignments.exists() else ()

    def get_queryset(self, request):
        # Clientes, marcas y líneas se administran en «Catálogos operativos».
        return super().get_queryset(request).exclude(dimension__code__in=CATALOG_DIMENSIONS)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "dimension":
            kwargs["queryset"] = RosterDimension.objects.exclude(code__in=CATALOG_DIMENSIONS)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RosterAttribute)
class RosterAttributeAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "group", "display_order", "data_type", "dimension", "depends_on", "is_active")
    list_filter = ("group", "data_type", "is_active")
    list_editable = ("display_order", "is_active")
    search_fields = ("code", "name")
    list_select_related = ("dimension", "depends_on")
    fieldsets = (
        (None, {"fields": ("code", "name", "group", "display_order", "help", "is_active")}),
        ("Tipo de dato", {"fields": ("data_type", "dimension", "depends_on", "choices", "rules")}),
    )

    def get_readonly_fields(self, request, obj=None):
        # Con asignaciones registradas, el código y el tipo no cambian (los valores históricos dependen de ellos).
        return ("code", "data_type", "dimension") if obj and obj.assignments.exists() else ()

    def has_delete_permission(self, request, obj=None):
        return False
