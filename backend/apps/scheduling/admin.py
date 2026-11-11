"""/admin/ › Horarios, tiempo y cortes: parámetros (nocturnidad, ciclos de pago y sus cortes, turnos).

* Reglas de nocturnidad por país: ventana horaria y % de recargo con vigencia (nada fijo en el código).
* Ciclos de pago: regla del periodo y corte operativo interno; la acción «Generar periodos» crea los
  periodos del año (los existentes no se tocan) y en la ficha se ajustan fechas de corte o de pago.
* Reglas de almuerzo por país: desde cuántos minutos de jornada continua corresponde almuerzo (advertencia u
  obligatorio). El almuerzo no es fijo: un bloque corto o un turno partido puede no llevarlo.
* Fase 11: periodo de PAGO (1–15 / 16–fin) y CORTE interno de asistencia (p. ej. 25–9 / 10–24) son dimensiones
  independientes, cada una con su regla y sus propias validaciones de traslape. Cada corte se mapea al periodo de
  pago que contiene su fecha de cierre.
* No hay turnos predefinidos: el horario de cada empleado se define día por día en su Acción de Personal.
* Nada se borra (lo referencian asignaciones, registros y cortes): se desactiva. Todo cambio se audita.
"""

from django.contrib import admin, messages
from django.db.models import Count
from django.utils import timezone

from apps.scheduling import services
from apps.scheduling.models import AttendanceCutoff, LunchRule, NightRule, PayCycle, PayPeriod
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


def _recent(qs, field: str):
    year = timezone.localdate().year
    return qs.filter(**{f"{field}__year__gte": year - 1, f"{field}__year__lte": year + 1})


class PayPeriodInline(admin.TabularInline):
    """Periodos de PAGO: fechas oficiales de devengo y pago."""

    model = PayPeriod
    extra = 0
    fields = ("code", "period_start", "period_end", "payment_date")
    ordering = ("period_start",)
    show_change_link = True
    verbose_name_plural = "periodos de pago (año anterior, en curso y siguiente)"

    def get_queryset(self, request):
        return _recent(super().get_queryset(request), "period_start")

    def has_delete_permission(self, request, obj=None):
        return False


class AttendanceCutoffInline(admin.TabularInline):
    """Cortes internos de asistencia: ventanas propias, mapeadas al periodo de pago que contiene su cierre."""

    model = AttendanceCutoff
    extra = 0
    fields = ("code", "cutoff_start", "cutoff_end", "pay_period", "status")
    readonly_fields = ("status",)
    ordering = ("cutoff_start",)
    show_change_link = True
    verbose_name_plural = "cortes internos de asistencia (año anterior, en curso y siguiente)"

    def get_queryset(self, request):
        return _recent(super().get_queryset(request), "cutoff_start").select_related("pay_period")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "pay_period":
            cycle_id = request.resolver_match.kwargs.get("object_id") if request.resolver_match else None
            kwargs["queryset"] = PayPeriod.objects.filter(cycle_id=cycle_id).order_by("period_start") if cycle_id else PayPeriod.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PayCycle)
class PayCycleAdmin(_AuditedAdmin):
    list_display = ("code", "name", "country", "pay_frequency", "rule_text", "cutoff_text", "payment_lag_days", "is_default", "is_active", "period_count")
    list_filter = ("country", "pay_frequency", "is_active")
    search_fields = ("code", "name")
    inlines = [PayPeriodInline, AttendanceCutoffInline]
    actions = ["generate_this_year", "generate_next_year"]
    fieldsets = (
        (None, {"fields": ("code", "name", "country", "pay_frequency", "is_default", "is_active", "notes")}),
        ("Periodo de pago", {"fields": ("period_rule", "period_start_day", "first_half_end_day", "length_days", "anchor_date", "payment_lag_days"),
                             "description": "Fechas OFICIALES de devengo y pago. Quincena calendario: día de inicio 1 y fin de la "
                                            "primera quincena 15 (1–15 y 16–fin, pago el 15 y el último día)."}),
        ("Corte interno de asistencia", {"fields": ("cutoff_start_day", "cutoff_first_end_day", "cutoff_lag_days"),
                                         "description": "Ventana en la que se cuentan las horas, independiente del periodo de pago. "
                                                        "Corte BPO: inicio 10 y fin de la primera ventana 24 → del 25 al 9 (se paga el 15) "
                                                        "y del 10 al 24 (se paga a fin de mes). Sin día propio, el corte se deriva del "
                                                        "periodo: cierra N días antes de su fin (0 = igual al periodo)."}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_periods=Count("periods"))

    @admin.display(description="periodo de pago")
    def rule_text(self, obj):
        return obj.rule_description

    @admin.display(description="corte de asistencia")
    def cutoff_text(self, obj):
        return obj.cutoff_rule_description

    @admin.display(description="periodos", ordering="_periods")
    def period_count(self, obj):
        return obj._periods

    def get_readonly_fields(self, request, obj=None):
        return ("code",) if obj else ()

    def save_formset(self, request, form, formset, change):
        """Las fechas de periodos y cortes editadas en línea también quedan en la auditoría."""
        super().save_formset(request, form, formset, change)
        for row in formset.forms:
            if row.instance.pk and row.has_changed() and not row.cleaned_data.get("DELETE"):
                x = row.instance
                if isinstance(x, AttendanceCutoff):
                    action, what = "cutoff_edited", (f"Corte {x.code}: asistencia {services.fmt(x.cutoff_start)}–{services.fmt(x.cutoff_end)}, "
                                                     f"se paga en {x.pay_period.code}")
                else:
                    action, what = "pay_period_edited", (f"Periodo de pago {x.code}: {services.fmt(x.period_start)}–{services.fmt(x.period_end)}, "
                                                         f"pago el {services.fmt(x.payment_date)}")
                record(
                    action, Category.SCHEDULING,
                    f"{what} (ciclo {form.instance.code}) modificado desde /admin/ (campos: {', '.join(row.changed_data)}).",
                    request=request, target_type=x.__class__.__name__, target_id=str(x.pk),
                )

    def _generate(self, request, queryset, year):
        for cycle in queryset.filter(is_active=True):
            try:
                result = services.generate_periods(cycle, year, user=request.user, request=request)
            except services.PeriodGenerationError as exc:
                self.message_user(request, f"{cycle.code}: {exc}", messages.ERROR)
                continue
            self.message_user(request, f"{cycle.code}: {result['created']} periodos de pago y {result['cutoffs_created']} cortes {year} generados "
                                       f"({result['skipped']} periodos y {result['cutoffs_skipped']} cortes ya existían).", messages.SUCCESS)

    @admin.action(description="Generar periodos del año en curso")
    def generate_this_year(self, request, queryset):
        self._generate(request, queryset, timezone.localdate().year)

    @admin.action(description="Generar periodos del próximo año")
    def generate_next_year(self, request, queryset):
        self._generate(request, queryset, timezone.localdate().year + 1)


@admin.register(PayPeriod)
class PayPeriodAdmin(_AuditedAdmin):
    list_display = ("code", "cycle", "period_start", "period_end", "payment_date", "cutoff_codes")
    list_filter = ("cycle",)
    date_hierarchy = "period_start"
    readonly_fields = ("created_at",)

    def has_add_permission(self, request):
        return False  # se generan desde el ciclo

    @admin.display(description="cortes que se pagan en él")
    def cutoff_codes(self, obj):
        return ", ".join(c.code for c in obj.cutoffs.order_by("cutoff_start")) or "—"


@admin.register(AttendanceCutoff)
class AttendanceCutoffAdmin(_AuditedAdmin):
    list_display = ("code", "cycle", "cutoff_start", "cutoff_end", "pay_period", "status", "closed_by")
    list_filter = ("cycle", "status")
    date_hierarchy = "cutoff_start"
    readonly_fields = ("status", "closed_at", "closed_by", "created_at")
    raw_id_fields = ("pay_period",)

    def has_add_permission(self, request):
        return False  # se generan desde el ciclo

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.status == AttendanceCutoff.Status.CLOSED:
            return [f.name for f in AttendanceCutoff._meta.fields]
        return self.readonly_fields
