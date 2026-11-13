"""/admin/ › Catálogos operativos: Clientes (con sus marcas), Marcas, Líneas de negocio y Sub-líneas.

* Los registros no se borran (las asignaciones históricas del roster y los General IDs los
  referencian): se desactivan. Desactivar un cliente desactiva sus marcas (cascada); igual LOB -> sub-líneas.
* El código no cambia después de creado.
* En la ficha del cliente y de la marca se configuran los General IDs que aplican (restricción en
  cascada: lo habilitado para un cliente aplica a todas sus marcas).
* Cada alta o cambio se registra en el audit trail (categoría «Catálogos operativos»).
"""

from django.contrib import admin
from django.db.models import Count

from apps.general_ids.models import GeneralIdTypeBrand, GeneralIdTypeClient, ScopeLevel
from apps.operations.models import Brand, Client, LineOfBusiness, OperationalLeader, SubLineOfBusiness
from apps.system.audit import Category, record


class _NoDeleteInline:
    """Filas existentes en solo lectura (se editan en su propia ficha, donde el código queda fijo);
    permite agregar nuevas desde el padre."""

    extra = 0
    show_change_link = True

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class BrandInline(_NoDeleteInline, admin.TabularInline):
    model = Brand
    fk_name = "client"
    fields = ("code", "name", "country", "is_active")


class _GeneralIdScopeInline(admin.TabularInline):
    extra = 0
    autocomplete_fields = ("id_type",)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "id_type":
            from apps.general_ids.models import GeneralIdType

            kwargs["queryset"] = GeneralIdType.objects.exclude(scope_level=ScopeLevel.GLOBAL)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class ClientGeneralIdInline(_GeneralIdScopeInline):
    model = GeneralIdTypeClient
    verbose_name = "General ID que aplica a este cliente"
    verbose_name_plural = "General IDs que aplican a este cliente (y, en cascada, a todas sus marcas)"


class BrandGeneralIdInline(_GeneralIdScopeInline):
    model = GeneralIdTypeBrand
    verbose_name = "General ID que aplica a esta marca"
    verbose_name_plural = "General IDs que aplican solo a esta marca"


class _CatalogAdmin(admin.ModelAdmin):
    search_fields = ("code", "name")
    readonly_fields = ("roster_item", "created_at", "updated_at")

    def get_readonly_fields(self, request, obj=None):
        # El código lo usan el roster y los reportes: no cambia una vez creado.
        return (*self.readonly_fields, "code") if obj else self.readonly_fields

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if form.changed_data or not change:
            label = obj._meta.verbose_name
            record(
                "catalog_changed" if change else "catalog_created", Category.CATALOGS,
                f"{label.capitalize()} «{obj.name}» ({obj.code}) {'modificado' if change else 'creado'}"
                f"{': ' + ', '.join(form.changed_data) if change else ''}.",
                request=request, target=obj, details={"model": obj._meta.model_name, "fields": form.changed_data},
            )

    def save_formset(self, request, form, formset, change):
        instances = formset.save()
        for item in instances:
            record(
                "catalog_changed", Category.CATALOGS, f"{item._meta.verbose_name.capitalize()}: «{item}» guardado desde «{form.instance}».",
                request=request, target=item, details={"model": item._meta.model_name},
            )
        for removed in formset.deleted_objects:
            record(
                "catalog_changed", Category.CATALOGS, f"{removed._meta.verbose_name.capitalize()}: «{removed}» quitado de «{form.instance}».",
                request=request, target=form.instance, details={"model": removed._meta.model_name, "removed": True},
            )


@admin.register(Client)
class ClientAdmin(_CatalogAdmin):
    list_display = ("name", "code", "legal_name", "country", "brand_count", "is_active")
    list_filter = ("is_active", "country")
    search_fields = ("code", "name", "legal_name")
    list_select_related = ("country",)
    fields = ("code", "name", "legal_name", "country", "description", "is_active", "roster_item", "created_at", "updated_at")
    inlines = [BrandInline, ClientGeneralIdInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_brands=Count("brands"))

    @admin.display(description="marcas", ordering="_brands")
    def brand_count(self, obj):
        return obj._brands


@admin.register(Brand)
class BrandAdmin(_CatalogAdmin):
    list_display = ("name", "code", "client", "country", "is_active")
    list_filter = ("is_active", "client", "country")
    search_fields = ("code", "name", "client__name")
    list_select_related = ("client", "country")
    autocomplete_fields = ("client",)
    fields = ("client", "code", "name", "country", "description", "is_active", "roster_item", "created_at", "updated_at")
    inlines = [BrandGeneralIdInline]


class SubLineInline(_NoDeleteInline, admin.TabularInline):
    model = SubLineOfBusiness
    fk_name = "line"
    fields = ("code", "name", "country", "is_active")


@admin.register(LineOfBusiness)
class LineOfBusinessAdmin(_CatalogAdmin):
    list_display = ("name", "code", "country", "sub_line_count", "is_active")
    list_filter = ("is_active", "country")
    list_select_related = ("country",)
    fields = ("code", "name", "country", "description", "is_active", "roster_item", "created_at", "updated_at")
    inlines = [SubLineInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_subs=Count("sub_lines"))

    @admin.display(description="sub-líneas", ordering="_subs")
    def sub_line_count(self, obj):
        return obj._subs


@admin.register(SubLineOfBusiness)
class SubLineOfBusinessAdmin(_CatalogAdmin):
    list_display = ("name", "code", "line", "country", "is_active")
    list_filter = ("is_active", "line", "country")
    search_fields = ("code", "name", "line__name")
    list_select_related = ("line", "country")
    autocomplete_fields = ("line",)
    fields = ("line", "code", "name", "country", "description", "is_active", "roster_item", "created_at", "updated_at")


@admin.register(OperationalLeader)
class OperationalLeaderAdmin(admin.ModelAdmin):
    """Jerarquía operativa (Fase 17). El alta habitual es desde WFM › Jerarquía operativa (busca por ID corporativo)."""

    list_display = ("employee", "level", "reports_to", "client", "is_active")
    list_filter = ("level", "is_active", "client")
    search_fields = ("employee__employee_code", "employee__first_name", "employee__last_name")
    list_select_related = ("employee", "reports_to__employee", "client")
    readonly_fields = ("roster_item", "created_at", "updated_at")
    raw_id_fields = ("employee",)
    autocomplete_fields = ("reports_to", "client")

    def get_readonly_fields(self, request, obj=None):
        return (*self.readonly_fields, "employee", "level") if obj else self.readonly_fields

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        record("ops_leader_updated" if change else "ops_leader_created", Category.CATALOGS,
               f"{obj.get_level_display()} {obj.employee.full_name} {'modificado' if change else 'registrado'} desde /admin/.",
               request=request, target=obj.employee, details={"fields": form.changed_data})
