"""/admin/ › Horarios, tiempo y cortes: parámetros (nocturnidad, ciclos de pago y sus cortes, turnos).

* Reglas de nocturnidad por país: ventana horaria y % de recargo con vigencia (nada fijo en el código).
* Ciclos de pago: regla del periodo y corte operativo interno; la acción «Generar periodos» crea los
  periodos del año (los existentes no se tocan) y en la ficha se ajustan fechas de corte o de pago.
* Reglas de almuerzo por país: desde cuántos minutos de jornada continua corresponde almuerzo (advertencia u
  obligatorio). El almuerzo no es fijo: un bloque corto o un turno partido puede no llevarlo.
* Ciclos con cortes que cruzan de mes (10–24 / 25–9): «día de inicio del periodo» + «fin de la primera quincena».
* No hay turnos predefinidos: el horario de cada empleado se define día por día en su Acción de Personal.
* Nada se borra (lo referencian asignaciones, registros y cortes): se desactiva. Todo cambio se audita.
"""

from django.contrib import admin, messages
from django.db.models import Count
from django.utils import timezone

from apps.scheduling import services
from apps.scheduling.models import LunchRule, NightRule, PayCycle, PayPeriod
from apps.system.audit import Category, record


class _AuditedAdmin(admin.ModelAdmin):
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if form.changed_data or not change:
            record(
                "sched_config_changed" if change else "sched_config_created", Category.SCHEDULING,
                f"{obj._meta.verbose_name.capitalize()} «{obj}» {'modificado' if change else 'creado'} desde /admin/"
                + (f" (campos: {', '.join(form.changed_data)})" if change else "") + ".",
                request=request, target_type=obj.__class__.__name__, target_id=str(obj.pk),
            )

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(NightRule)
class NightRuleAdmin(_AuditedAdmin):
    list_display = ("name", "country", "start_time", "end_time", "surcharge_percent", "effective_start_date", "effective_end_date", "is_active")
    list_filter = ("country", "is_active")
    search_fields = ("name", "legal_reference")
    fieldsets = (
        (None, {"fields": ("country", "name", "is_active")}),
        ("Jornada nocturna", {"fields": ("start_time", "end_time", "surcharge_percent"),
                              "description": "Si el fin es menor que el inicio (19:00–06:00), la ventana cruza la medianoche."}),
        ("Vigencia", {"fields": ("effective_start_date", "effective_end_date", "legal_reference")}),
    )


@admin.register(LunchRule)
class LunchRuleAdmin(_AuditedAdmin):
    list_display = ("name", "country", "min_block_minutes", "lunch_minutes", "enforcement", "effective_start_date", "effective_end_date", "is_active")
    list_filter = ("country", "enforcement", "is_active")
    search_fields = ("name", "legal_reference")
    fieldsets = (
        (None, {"fields": ("country", "name", "is_active")}),
        ("Regla", {"fields": ("min_block_minutes", "lunch_minutes", "enforcement"),
                   "description": "Se evalúa por bloque continuo (entrada a salida). Con varios tramos por país aplica el de "
                                  "umbral más alto que el bloque alcanza. «Advertencia» no bloquea la AP; «Obligatorio» sí."}),
        ("Vigencia", {"fields": ("effective_start_date", "effective_end_date", "legal_reference")}),
    )


class PayPeriodInline(admin.TabularInline):
    model = PayPeriod
    extra = 0
    fields = ("code", "period_start", "period_end", "cutoff_start", "cutoff_end", "payment_date", "status")
    readonly_fields = ("status",)
    ordering = ("period_start",)
    show_change_link = True

    def get_queryset(self, request):
        year = timezone.localdate().year
        return super().get_queryset(request).filter(period_start__year__gte=year - 1, period_start__year__lte=year + 1)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PayCycle)
class PayCycleAdmin(_AuditedAdmin):
    list_display = ("code", "name", "country", "pay_frequency", "period_rule", "rule_text", "cutoff_lag_days", "payment_lag_days", "is_default", "is_active", "period_count")
    list_filter = ("country", "pay_frequency", "is_active")
    search_fields = ("code", "name")
    inlines = [PayPeriodInline]
    actions = ["generate_this_year", "generate_next_year"]
    fieldsets = (
        (None, {"fields": ("code", "name", "country", "pay_frequency", "is_default", "is_active", "notes")}),
        ("Periodo", {"fields": ("period_rule", "period_start_day", "first_half_end_day", "length_days", "anchor_date"),
                     "description": "Cortes BPO que cruzan de mes: día de inicio 10 y fin de la primera quincena 24 → "
                                    "del 10 al 24 y del 25 al 9 del mes siguiente. Calendario: 1 y 15."}),
        ("Corte operativo interno y pago", {"fields": ("cutoff_lag_days", "payment_lag_days"),
                                             "description": "Con corte N días antes del fin, la asistencia de cada periodo va del día "
                                                            "siguiente al corte anterior hasta el corte actual (ventanas contiguas)."}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_periods=Count("periods"))

    @admin.display(description="regla")
    def rule_text(self, obj):
        return obj.rule_description

    @admin.display(description="periodos", ordering="_periods")
    def period_count(self, obj):
        return obj._periods

    def get_readonly_fields(self, request, obj=None):
        return ("code",) if obj else ()

    def save_formset(self, request, form, formset, change):
        """Las fechas de periodos editadas en línea también quedan en la auditoría (antes solo el ciclo)."""
        super().save_formset(request, form, formset, change)
        for period_form in formset.forms:
            if period_form.instance.pk and period_form.has_changed() and not period_form.cleaned_data.get("DELETE"):
                p = period_form.instance
                record(
                    "pay_period_edited", Category.SCHEDULING,
                    f"Periodo {p.code} del ciclo {form.instance.code} modificado desde /admin/ (campos: {', '.join(period_form.changed_data)}): "
                    f"periodo {services.fmt(p.period_start)}–{services.fmt(p.period_end)}, asistencia {services.fmt(p.cutoff_start)}–{services.fmt(p.cutoff_end)}.",
                    request=request, target_type="PayPeriod", target_id=str(p.pk),
                )

    def _generate(self, request, queryset, year):
        for cycle in queryset.filter(is_active=True):
            try:
                result = services.generate_periods(cycle, year, user=request.user, request=request)
            except services.PeriodGenerationError as exc:
                self.message_user(request, f"{cycle.code}: {exc}", messages.ERROR)
                continue
            self.message_user(request, f"{cycle.code}: {result['created']} periodos {year} generados ({result['skipped']} ya existían).", messages.SUCCESS)

    @admin.action(description="Generar periodos del año en curso")
    def generate_this_year(self, request, queryset):
        self._generate(request, queryset, timezone.localdate().year)

    @admin.action(description="Generar periodos del próximo año")
    def generate_next_year(self, request, queryset):
        self._generate(request, queryset, timezone.localdate().year + 1)


@admin.register(PayPeriod)
class PayPeriodAdmin(_AuditedAdmin):
    list_display = ("code", "cycle", "period_start", "period_end", "cutoff_start", "cutoff_end", "payment_date", "status")
    list_filter = ("cycle", "status")
    date_hierarchy = "period_start"
    readonly_fields = ("status", "closed_at", "closed_by", "created_at")

    def has_add_permission(self, request):
        return False  # se generan desde el ciclo

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status == PayPeriod.Status.CLOSED:
            return [f.name for f in PayPeriod._meta.fields]
        return self.readonly_fields
