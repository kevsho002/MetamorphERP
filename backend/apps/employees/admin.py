"""/admin/ de empleados: SOLO parametrización (plantillas JSON por país y catálogo de atributos EAV).

Fase 5: los empleados, sus valores EAV, expedientes, cargas masivas y cuentas de usuario se
gestionan en la aplicación (React + API), donde se aplican las reglas de negocio, el RBAC y la
auditoría. El admin no permite asignaciones manuales sobre personas.
"""

import json
from datetime import timedelta

from django import forms
from django.contrib import admin, messages
from django.db.models import Count
from django.forms.fields import InvalidJSONInput
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from apps.employees.models import AttributeDefinition, EmployeeTemplate
from apps.employees.schema import resolve_template


# --------------------------------------------------------------------- utilidades
class PrettyJSONField(forms.JSONField):
    """Muestra el JSON indentado y con tildes legibles (no \\u00e1)."""

    def prepare_value(self, value):
        if isinstance(value, InvalidJSONInput):
            return value
        return json.dumps(value, ensure_ascii=False, indent=2, cls=self.encoder)


JSON_TEXTAREA = forms.Textarea(attrs={"rows": 32, "style": "width: 95%; font-family: Consolas, monospace; font-size: 13px;"})


def _pre(value) -> str:
    return format_html(
        '<pre style="white-space: pre-wrap; margin: 0; font-size: 12px;">{}</pre>',
        json.dumps(value, ensure_ascii=False, indent=2) if not isinstance(value, str) else value,
    )


# --------------------------------------------------------------------- atributos dinámicos
@admin.register(AttributeDefinition)
class AttributeDefinitionAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "data_type", "is_sensitive", "is_active", "value_count", "used_in")
    list_filter = ("data_type", "is_active", "is_sensitive")
    search_fields = ("code", "name", "description")
    readonly_fields = ("created_at", "updated_at", "used_in")

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_values=Count("values"))

    @admin.display(description="valores", ordering="_values")
    def value_count(self, obj):
        return obj._values if hasattr(obj, "_values") else obj.values.count()

    @admin.display(description="usado en plantillas")
    def used_in(self, obj):
        names = [
            f"{t.country.country_code} {t.effective_date:%d/%m/%Y}"
            for t in EmployeeTemplate.objects.select_related("country")
            if obj.code in (t.schema or {}).get("attributes", {})
        ]
        return ", ".join(names) or "—"

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj is not None:
            fields.append("code")  # es el nombre de columna en los archivos y la clave en las plantillas
            if obj.values.exists():
                fields.append("data_type")  # cambiarlo invalidaría los valores ya guardados
        return fields

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (obj is None or not obj.values.exists())


# --------------------------------------------------------------------- plantillas por país
class EmployeeTemplateForm(forms.ModelForm):
    schema = PrettyJSONField(
        label="Definición JSON",
        widget=JSON_TEXTAREA,
        help_text=(
            "Claves: <code>core_fields</code> (campos de hcm.Employee), <code>attributes</code> (códigos del catálogo de "
            "atributos dinámicos) y <code>rules</code> (min_age, max_age, min_base_salary, max_base_salary, "
            "max_future_hire_days). Reglas por campo: label, required, recommended, default, pattern, example, "
            "pattern_message, patterns_by_type, choices, min, max, min_length, max_length, transform, help."
        ),
    )

    class Meta:
        model = EmployeeTemplate
        fields = ("country", "name", "effective_date", "is_active", "schema", "notes")


@admin.register(EmployeeTemplate)
class EmployeeTemplateAdmin(admin.ModelAdmin):
    form = EmployeeTemplateForm
    list_display = ("name", "country", "effective_date", "is_active", "field_count", "status_label")
    list_filter = ("is_active", "country")
    search_fields = ("name", "country__country_code", "country__country_name")
    date_hierarchy = "effective_date"
    ordering = ("country_id", "-effective_date")
    actions = ["clone_as_new_version"]

    @admin.display(description="atributos dinámicos")
    def field_count(self, obj):
        return len((obj.schema or {}).get("attributes", {}))

    @admin.display(description="vigencia")
    def status_label(self, obj):
        current = EmployeeTemplate.objects.effective_for(obj.country, timezone.localdate())
        if not obj.is_active:
            return "inactiva"
        if current and current.pk == obj.pk:
            return "vigente hoy"
        return "futura" if obj.effective_date > timezone.localdate() else "histórica"

    @admin.display(description="vista previa del formulario")
    def preview(self, obj):
        if not obj or not obj.pk:
            return "Guarde la plantilla para ver la vista previa."
        try:
            spec = resolve_template(obj)
        except Exception as exc:  # plantilla guardada antes de un cambio en el catálogo
            return f"No se pudo resolver la plantilla: {exc}"
        rows = []
        for f in spec.fields.values():
            rules = []
            if f.pattern is not None:
                rules.append(f"patrón {f.pattern.pattern}")
            for id_type, rule in (f.patterns_by_type or {}).items():
                rules.append(f"{id_type}: {rule['pattern']}")
            if f.choices:
                rules.append("opciones: " + ", ".join(f.choices))
            if f.example:
                rules.append(f"ej. {f.example}")
            if f.default:
                rules.append(f"por defecto {f.default}")
            need = "Obligatorio" if f.required else ("Recomendado" if f.recommended else "Opcional")
            rows.append((f.key, f.label, "base" if f.kind == "core" else "dinámico", f.data_type, need, " · ".join(rules)))
        try:
            csv_url = reverse("employee-template-csv", args=[obj.pk])
            link = format_html('<p><a href="{}">Descargar CSV de ejemplo para carga masiva</a></p>', csv_url)
        except NoReverseMatch:
            link = ""
        rules_text = ", ".join(f"{k} = {v}" for k, v in spec.rules.items()) or "sin reglas adicionales"
        return format_html(
            '{}<p><strong>Reglas del país:</strong> {}</p><table><thead><tr><th>Campo</th><th>Etiqueta</th><th>Tipo</th>'
            "<th>Dato</th><th>Exigencia</th><th>Validación</th></tr></thead><tbody>{}</tbody></table>",
            link,
            rules_text,
            format_html_join("", "<tr><td><code>{}</code></td><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>", rows),
        )

    @admin.display(description="definición JSON")
    def schema_readonly(self, obj):
        return _pre(obj.schema)

    def get_fieldsets(self, request, obj=None):
        locked = obj is not None and obj.in_use
        main = ["country", "name", "effective_date", "is_active", "notes"]
        definition = ["schema_readonly"] if locked else ["schema"]
        description = (
            "Esta plantilla ya validó empleados reales: su país, fecha y definición quedan bloqueados para conservar el "
            "historial. Use la acción «Clonar como nueva versión» para cambiar las reglas a partir de una nueva fecha."
            if locked
            else None
        )
        return (
            ("Plantilla", {"fields": main}),
            ("Definición", {"fields": definition, "description": description}),
            ("Vista previa", {"fields": ["preview"], "classes": ["collapse"] if obj is None else []}),
            ("Auditoría", {"fields": ["created_by", "created_at", "updated_at"], "classes": ["collapse"]}),
        )

    def get_readonly_fields(self, request, obj=None):
        fields = ["preview", "schema_readonly", "created_by", "created_at", "updated_at"]
        if obj is not None and obj.in_use:
            fields += ["country", "effective_date"]
        return fields

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user.get_username()
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (obj is None or not obj.in_use)

    @admin.action(description="Clonar como nueva versión (inactiva, vigente desde mañana)")
    def clone_as_new_version(self, request, queryset):
        created = []
        for template in queryset.select_related("country"):
            effective = max(
                timezone.localdate() + timedelta(days=1),
                EmployeeTemplate.objects.filter(country=template.country).order_by("-effective_date").first().effective_date
                + timedelta(days=1),
            )
            clone = EmployeeTemplate.objects.create(
                country=template.country,
                name=f"{template.name} (nueva versión)",
                effective_date=effective,
                is_active=False,
                schema=template.schema,
                notes=f"Clonada de la plantilla #{template.pk}.",
                created_by=request.user.get_username(),
            )
            created.append(f"{clone.country.country_code} desde {effective:%d/%m/%Y}")
        self.message_user(
            request,
            f"Se crearon {len(created)} versiones inactivas ({', '.join(created)}). Revíselas y actívelas cuando estén listas.",
            messages.SUCCESS,
        )
