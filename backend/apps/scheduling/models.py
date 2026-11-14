"""Fase 8 — Horarios, tiempo por fecha de ocurrencia y ciclos / cortes de nómina.

    sch_schedule_assignment    horario ATÓMICO por día vigente por fechas efectivas; lo crea una Acción de
                               Personal aprobada (apps.personnel_actions). Un solo horario PRINCIPAL por fecha
                               (50040); las asignaciones ADICIONALES (turno partido / doble) conviven con él
    sch_lunch_rule             reglas de almuerzo por país: desde N minutos de jornada continua, almuerzo mínimo
    sch_night_rule             nocturnidad por país: ventana horaria y % de recargo, con vigencia (50042)
    sch_pay_cycle              ciclo de pago (quincenal / mensual / N días): regla del PERIODO DE PAGO y,
                               por separado, regla del CORTE INTERNO de asistencia (Fase 11)
    sch_pay_period             PERIODOS DE PAGO: fechas oficiales de devengo y fecha de pago (1–15 / 16–fin);
                               contiguos por ciclo: sin colisión (50043) ni hueco (50045)
    sch_attendance_cutoff      CORTES INTERNOS de asistencia (Fase 11): ventanas en las que se cuentan las horas,
                               pueden cruzar de mes (25–9 / 10–24); contiguas entre sí (50044 / 50046) e
                               independientes de los periodos; cada una se mapea al periodo de pago que contiene
                               su fecha de cierre (50048)
    sch_time_record            registro de tiempo / marcación: intervalo entrada-salida (hora local) o
                               duración reportada para una fecha; sin traslapes por empleado (50041)
    sch_time_record_day        porción del registro en cada DÍA CALENDARIO DE OCURRENCIA (un turno de
                               22:00 a 06:00 produce dos filas con la misma `shift_date`)

Las FKs a hcm.Employee y core.catCountry (SQL-first) se crean en la migración 0002.
"""

from __future__ import annotations

from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q

from apps.common.fields import sql_table
from apps.common.models import Country
from apps.hcm.models import Employee
from apps.scheduling import engine
from apps.scheduling.fields import WallClockDateTimeField

UPPER_CODE = RegexValidator(r"^[A-Z][A-Z0-9_\-]*$", "Use MAYÚSCULAS, dígitos, guion o guion bajo; debe iniciar con letra.")
FAR_FUTURE = date(9999, 12, 31)


def _country_fk(**kwargs):
    return models.ForeignKey(
        Country, on_delete=models.DO_NOTHING, db_column="country_id", db_constraint=False,
        verbose_name="país", **kwargs,
    )


def _employee_fk(related_name: str):
    return models.ForeignKey(
        Employee, on_delete=models.DO_NOTHING, db_column="employee_id", db_constraint=False,
        related_name=related_name, verbose_name="empleado",
    )


# ---------------------------------------------------------------- horario vigente por fechas efectivas
class ScheduleAssignment(models.Model):
    """Horario atómico por día vigente para un empleado entre dos fechas.

    Lo crea SOLO una Acción de Personal de horario al aprobarse (no se elige un turno de una lista): guarda el
    horario de cada día de la semana tal como quedó en la AP (entrada, salida, almuerzo, horas diurnas y
    nocturnas). La AP siguiente cierra esta vigencia el día anterior a su fecha efectiva.
    """

    class Mode(models.TextChoices):
        PRIMARY = "PRIMARY", "Horario principal"
        ADDITIONAL = "ADDITIONAL", "Asignación adicional (turno partido / doble)"

    employee = _employee_fk("schedule_assignments")
    mode = models.CharField(
        "tipo de asignación", max_length=10, choices=Mode, default=Mode.PRIMARY,
        help_text="Principal: uno por fecha (una AP de cambio lo reemplaza). Adicional: convive con el principal hasta su fecha de fin.",
    )
    personnel_action = models.OneToOneField(
        "personnel_actions.PersonnelAction", on_delete=models.PROTECT, null=True, blank=True,
        related_name="schedule_assignment", verbose_name="acción de personal",
    )
    definition = models.JSONField("horario por día (JSON)")
    weekly_minutes = models.PositiveIntegerField("minutos programados por semana", default=0)
    effective_start_date = models.DateField("vigente desde")
    effective_end_date = models.DateField("vigente hasta", null=True, blank=True, help_text="Vacío = «Now» (sin fecha de fin).")
    notes = models.CharField("notas", max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+", verbose_name="registrado por")
    created_at = models.DateTimeField("registrado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        db_table = sql_table("wfm", "sch_schedule_assignment")
        ordering = ["employee_id", "-effective_start_date"]
        verbose_name = "horario vigente"
        verbose_name_plural = "horarios vigentes (por AP)"
        indexes = [models.Index(fields=["employee", "effective_start_date"], name="ix_sch_assign_emp_start")]
        constraints = [
            models.CheckConstraint(
                condition=Q(effective_end_date__isnull=True) | Q(effective_end_date__gte=models.F("effective_start_date")),
                name="ck_sch_assign_dates",
            ),
            models.CheckConstraint(condition=Q(mode__in=["PRIMARY", "ADDITIONAL"]), name="ck_sch_assign_mode"),
            # Una asignación adicional siempre tiene fecha de fin (no queda «Now» para siempre).
            models.CheckConstraint(condition=Q(mode="PRIMARY") | Q(effective_end_date__isnull=False), name="ck_sch_assign_additional_end"),
        ]

    def __str__(self) -> str:
        label = self.personnel_action.folio if self.personnel_action_id else "sin AP"
        return f"{label} {self.effective_start_date:%d/%m/%Y} → {self.effective_end_date or 'Now'}"

    @property
    def label(self) -> str:
        return self.personnel_action.folio if self.personnel_action_id else f"Horario #{self.pk}"

    def covers(self, d: date) -> bool:
        return self.effective_start_date <= d <= (self.effective_end_date or FAR_FUTURE)

    def save(self, *args, **kwargs):
        parsed = engine.parse_definition(self.definition)  # nunca se guarda un horario inválido
        self.weekly_minutes = parsed.weekly_net_minutes
        super().save(*args, **kwargs)


# ---------------------------------------------------------------- nocturnidad
class NightRule(models.Model):
    country = _country_fk(related_name="+")
    name = models.CharField("nombre", max_length=120)
    start_time = models.TimeField("inicio de la jornada nocturna", help_text="Ej.: 19:00")
    end_time = models.TimeField("fin de la jornada nocturna", help_text="Ej.: 06:00 (si es menor que el inicio, cruza la medianoche)")
    surcharge_percent = models.DecimalField(
        "recargo (%)", max_digits=6, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(500)],
        help_text="Porcentaje sobre el salario de la hora diurna (25 = 25 %).",
    )
    effective_start_date = models.DateField("vigente desde")
    effective_end_date = models.DateField("vigente hasta", null=True, blank=True)
    legal_reference = models.CharField("base legal", max_length=300, blank=True)
    is_active = models.BooleanField("activa", default=True)
    created_at = models.DateTimeField("creada", auto_now_add=True)
    updated_at = models.DateTimeField("actualizada", auto_now=True)

    class Meta:
        db_table = sql_table("wfm", "sch_night_rule")
        ordering = ["country_id", "-effective_start_date"]
        verbose_name = "regla de nocturnidad"
        verbose_name_plural = "reglas de nocturnidad"
        constraints = [
            models.CheckConstraint(
                condition=Q(effective_end_date__isnull=True) | Q(effective_end_date__gte=models.F("effective_start_date")),
                name="ck_sch_night_dates",
            ),
            models.CheckConstraint(condition=~Q(start_time=models.F("end_time")), name="ck_sch_night_window"),
            models.CheckConstraint(condition=Q(surcharge_percent__gte=0, surcharge_percent__lte=500), name="ck_sch_night_surcharge"),
        ]

    def __str__(self) -> str:
        return f"{self.name}: {self.start_time:%H:%M}–{self.end_time:%H:%M} (+{self.surcharge_percent} %)"

    def window(self) -> engine.NightWindow:
        return engine.NightWindow(self.start_time, self.end_time, float(self.surcharge_percent), self.pk, self.name)

    def clean(self):
        errors = {}
        if self.start_time and self.end_time and self.start_time.replace(second=0) == self.end_time.replace(second=0):
            errors["end_time"] = "El inicio y el fin de la jornada nocturna no pueden ser la misma hora."
        if self.effective_end_date and self.effective_start_date and self.effective_end_date < self.effective_start_date:
            errors["effective_end_date"] = "«Vigente hasta» no puede ser anterior a «vigente desde»."
        if not errors and self.is_active and self.country_id and self.effective_start_date:
            clash = NightRule.objects.filter(country_id=self.country_id, is_active=True).exclude(pk=self.pk).filter(
                Q(effective_end_date__isnull=True) | Q(effective_end_date__gte=self.effective_start_date),
            )
            if self.effective_end_date:
                clash = clash.filter(effective_start_date__lte=self.effective_end_date)
            other = clash.first()
            if other:
                errors["effective_start_date"] = (
                    f"Ya hay una regla de nocturnidad activa para el país en esas fechas: «{other.name}» "
                    f"({other.effective_start_date:%d/%m/%Y} → {other.effective_end_date or 'Now'}). Cierre su vigencia primero."
                )
        if errors:
            raise ValidationError(errors)


# ---------------------------------------------------------------- almuerzo
class LunchRule(models.Model):
    """Desde cuántos minutos de jornada CONTINUA corresponde almuerzo y de cuántos minutos, por país.

    El almuerzo no es fijo en el horario: un bloque corto (o un turno partido) puede no llevarlo. Varios tramos
    por país (p. ej. ≥ 5 h → 30 min, ≥ 9 h → 60 min): aplica el de umbral más alto que el bloque alcanza.
    """

    class Enforcement(models.TextChoices):
        WARN = "WARN", "Advertencia (no bloquea)"
        REQUIRE = "REQUIRE", "Obligatorio (bloquea la AP)"

    country = _country_fk(related_name="+")
    name = models.CharField("nombre", max_length=120)
    min_block_minutes = models.PositiveSmallIntegerField(
        "jornada continua mínima (min)", validators=[MinValueValidator(30), MaxValueValidator(1440)],
        help_text="Desde cuántos minutos de jornada continua (un bloque, entrada a salida) aplica. 360 = 6 h.",
    )
    lunch_minutes = models.PositiveSmallIntegerField(
        "almuerzo mínimo (min)", validators=[MinValueValidator(5), MaxValueValidator(engine.MAX_LUNCH_MINUTES)],
    )
    enforcement = models.CharField("aplicación", max_length=7, choices=Enforcement, default=Enforcement.WARN)
    effective_start_date = models.DateField("vigente desde")
    effective_end_date = models.DateField("vigente hasta", null=True, blank=True)
    legal_reference = models.CharField("base legal / política", max_length=300, blank=True)
    is_active = models.BooleanField("activa", default=True)
    created_at = models.DateTimeField("creada", auto_now_add=True)
    updated_at = models.DateTimeField("actualizada", auto_now=True)

    class Meta:
        db_table = sql_table("wfm", "sch_lunch_rule")
        ordering = ["country_id", "min_block_minutes", "-effective_start_date"]
        verbose_name = "regla de almuerzo"
        verbose_name_plural = "reglas de almuerzo (horas mínimas por país)"
        constraints = [
            models.CheckConstraint(
                condition=Q(effective_end_date__isnull=True) | Q(effective_end_date__gte=models.F("effective_start_date")),
                name="ck_sch_lunch_dates",
            ),
            models.CheckConstraint(condition=Q(lunch_minutes__lt=models.F("min_block_minutes")), name="ck_sch_lunch_minutes"),
            models.CheckConstraint(condition=Q(enforcement__in=["WARN", "REQUIRE"]), name="ck_sch_lunch_enforcement"),
        ]

    def __str__(self) -> str:
        return f"{self.name}: ≥ {engine.fmt_minutes(self.min_block_minutes)} h → {self.lunch_minutes} min"

    def rule(self) -> engine.LunchRule:
        return engine.LunchRule(self.min_block_minutes, self.lunch_minutes, self.enforcement, self.name, self.pk)

    def clean(self):
        errors = {}
        if self.lunch_minutes and self.min_block_minutes and self.lunch_minutes >= self.min_block_minutes:
            errors["lunch_minutes"] = "El almuerzo debe ser menor que la jornada mínima."
        if self.effective_end_date and self.effective_start_date and self.effective_end_date < self.effective_start_date:
            errors["effective_end_date"] = "«Vigente hasta» no puede ser anterior a «vigente desde»."
        if not errors and self.is_active and self.country_id and self.effective_start_date and self.min_block_minutes:
            clash = LunchRule.objects.filter(country_id=self.country_id, is_active=True, min_block_minutes=self.min_block_minutes).exclude(pk=self.pk).filter(
                Q(effective_end_date__isnull=True) | Q(effective_end_date__gte=self.effective_start_date),
            )
            if self.effective_end_date:
                clash = clash.filter(effective_start_date__lte=self.effective_end_date)
            other = clash.first()
            if other:
                errors["min_block_minutes"] = (
                    f"Ya hay una regla activa del país con el mismo umbral en esas fechas: «{other.name}». Cierre su vigencia primero."
                )
        if errors:
            raise ValidationError(errors)


# ---------------------------------------------------------------- ciclos y cortes
class PayCycle(models.Model):
    class PeriodRule(models.TextChoices):
        HALF_MONTH = "HALF_MONTH", "Quincenal (dos periodos por mes)"
        MONTH = "MONTH", "Mensual"
        FIXED_DAYS = "FIXED_DAYS", "Bloques de N días (semanal, catorcenal)"

    code = models.CharField("código", max_length=30, unique=True, validators=[UPPER_CODE])
    name = models.CharField("nombre", max_length=120)
    country = _country_fk(related_name="+")
    pay_frequency = models.CharField(
        "frecuencia de pago", max_length=15, choices=Employee.PayFrequency,
        help_text="Aplica a los empleados del país con esta frecuencia de pago.",
    )
    period_rule = models.CharField("regla del periodo", max_length=12, choices=PeriodRule)
    period_start_day = models.PositiveSmallIntegerField(
        "día de inicio del periodo", default=1, validators=[MinValueValidator(1), MaxValueValidator(28)],
        help_text="Quincenal / mensual: día del mes en que inicia el primer periodo. 1 = calendario (1–15 y 16–fin); "
                  "10 = cortes BPO que cruzan de mes (10–24 y 25–9 del mes siguiente).",
    )
    first_half_end_day = models.PositiveSmallIntegerField(
        "fin de la primera quincena", default=15, validators=[MinValueValidator(5), MaxValueValidator(27)],
        help_text="Último día del primer periodo del mes (p. ej. 15, o 24 en un corte 10–24 / 25–9).",
    )
    length_days = models.PositiveSmallIntegerField(
        "días por periodo", null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(31)],
        help_text="Solo para «Bloques de N días» (7 = semanal, 14 = catorcenal).",
    )
    anchor_date = models.DateField("fecha ancla", null=True, blank=True,
                                   help_text="Solo para «Bloques de N días»: inicio de un periodo cualquiera.")
    cutoff_start_day = models.PositiveSmallIntegerField(
        "corte interno: día de inicio de la ventana", null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(28)],
        help_text="Ventanas de asistencia PROPIAS, independientes del periodo de pago. Quincenal 10 + fin 24 = del 10 al 24 "
                  "y del 25 al 9 del mes siguiente; mensual 26 = del 26 al 25. Vacío = derivadas del periodo de pago.",
    )
    cutoff_first_end_day = models.PositiveSmallIntegerField(
        "corte interno: fin de la primera ventana", null=True, blank=True, validators=[MinValueValidator(5), MaxValueValidator(27)],
        help_text="Solo quincenal con ventanas propias: último día de la primera ventana del mes (24 en un corte 10–24 / 25–9).",
    )
    cutoff_lag_days = models.PositiveSmallIntegerField(
        "corte interno: días antes del fin", default=0, validators=[MaxValueValidator(15)],
        help_text="Solo si NO hay ventanas propias: la asistencia se cierra N días antes del fin del periodo de pago.",
    )
    payment_lag_days = models.PositiveSmallIntegerField(
        "días de pago después del fin", default=0, validators=[MaxValueValidator(31)],
    )
    is_default = models.BooleanField("predeterminado", default=True,
                                     help_text="Ciclo que se usa para los empleados del país con esa frecuencia.")
    is_active = models.BooleanField("activo", default=True)
    notes = models.CharField("notas", max_length=300, blank=True)
    created_at = models.DateTimeField("creado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        db_table = sql_table("wfm", "sch_pay_cycle")
        ordering = ["country_id", "code"]
        verbose_name = "ciclo de pago"
        verbose_name_plural = "ciclos de pago"
        constraints = [
            models.UniqueConstraint(
                fields=["country", "pay_frequency"], condition=Q(is_default=True, is_active=True),
                name="uq_sch_pay_cycle_default",
            ),
            models.CheckConstraint(
                condition=~Q(period_rule="FIXED_DAYS") | Q(length_days__isnull=False, anchor_date__isnull=False),
                name="ck_sch_pay_cycle_fixed",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"

    def rule(self) -> engine.CycleRule:
        return engine.CycleRule(
            period_rule=self.period_rule, first_half_end_day=self.first_half_end_day, length_days=self.length_days,
            anchor_date=self.anchor_date, cutoff_lag_days=self.cutoff_lag_days, payment_lag_days=self.payment_lag_days,
            period_start_day=self.period_start_day or 1, cutoff_start_day=self.cutoff_start_day,
            cutoff_first_end_day=self.cutoff_first_end_day,
        )

    @property
    def rule_description(self) -> str:
        return engine.describe_rule(self.rule())

    @property
    def cutoff_rule_description(self) -> str:
        return engine.describe_cutoff_rule(self.rule())

    @property
    def has_own_cutoffs(self) -> bool:
        return engine.cutoff_window_rule(self.rule()) is not None

    def clean(self):
        errors = {}
        F = Employee.PayFrequency
        allowed = {
            F.MONTHLY: {self.PeriodRule.MONTH},
            F.BIWEEKLY: {self.PeriodRule.HALF_MONTH, self.PeriodRule.FIXED_DAYS},
            F.WEEKLY: {self.PeriodRule.FIXED_DAYS},
        }.get(self.pay_frequency, set())
        if self.period_rule and self.pay_frequency and self.period_rule not in allowed:
            errors["period_rule"] = f"La regla «{self.get_period_rule_display()}» no corresponde a la frecuencia {self.get_pay_frequency_display().lower()}."
        if self.period_rule == self.PeriodRule.FIXED_DAYS:
            if not self.length_days:
                errors["length_days"] = "Indique cuántos días dura cada periodo."
            elif self.pay_frequency == F.WEEKLY and self.length_days != 7:
                errors["length_days"] = "Un ciclo semanal dura 7 días."
            elif self.pay_frequency == F.BIWEEKLY and self.length_days != 14:
                errors["length_days"] = "Un ciclo catorcenal dura 14 días."
            if not self.anchor_date:
                errors["anchor_date"] = "Indique la fecha en que inicia un periodo (ancla)."
        start_day = self.period_start_day or 1
        shortest = None
        if self.period_rule == self.PeriodRule.HALF_MONTH and self.first_half_end_day:
            message, shortest = _half_month_errors(start_day, self.first_half_end_day, "quincena")
            if message:
                errors["first_half_end_day"] = message
        if self.period_rule == self.PeriodRule.FIXED_DAYS and start_day != 1:
            errors["period_start_day"] = "En «Bloques de N días» el inicio lo marca la fecha ancla (deje 1)."
        # Corte interno: ventanas propias (independientes del periodo de pago) o derivadas con N días de anticipación.
        if self.cutoff_start_day:
            if self.period_rule == self.PeriodRule.FIXED_DAYS:
                errors["cutoff_start_day"] = ("En «Bloques de N días» el corte se deriva del periodo: deje vacío el día de "
                                              "inicio y use los días de anticipación.")
            elif self.cutoff_lag_days:
                errors["cutoff_lag_days"] = "Con ventanas de asistencia propias no se usan días de anticipación (deje 0)."
            elif self.period_rule == self.PeriodRule.HALF_MONTH:
                if not self.cutoff_first_end_day:
                    errors["cutoff_first_end_day"] = "Indique el último día de la primera ventana (p. ej. 24 en un corte 10–24 / 25–9)."
                else:
                    message, _ = _half_month_errors(self.cutoff_start_day, self.cutoff_first_end_day, "ventana de asistencia")
                    if message:
                        errors["cutoff_first_end_day"] = message
        elif self.cutoff_first_end_day:
            errors["cutoff_start_day"] = "Indique también el día de inicio de la ventana (o deje ambos vacíos)."
        if self.length_days and self.cutoff_lag_days >= self.length_days:
            errors["cutoff_lag_days"] = "El corte interno debe ocurrir dentro del periodo."
        if self.period_rule == self.PeriodRule.HALF_MONTH and self.cutoff_lag_days > 10:
            errors["cutoff_lag_days"] = "En un ciclo quincenal el corte no puede ser más de 10 días antes del fin."
        elif shortest and self.cutoff_lag_days >= shortest:
            errors["cutoff_lag_days"] = f"El corte debe cerrar dentro de cada periodo (el más corto dura {shortest} días)."
        if errors:
            raise ValidationError(errors)


def _half_month_errors(start_day: int, first_end: int, what: str) -> tuple[str | None, int]:
    """Las dos mitades del mes (también en febrero) deben durar al menos 7 días. Devuelve (error, días de la más corta)."""
    first_len = first_end - start_day + 1
    second_len = 28 - first_end + start_day - 1  # en el mes más corto (febrero)
    if first_len < 7:
        return f"La primera {what} (del {start_day} al {first_end}) debe durar al menos 7 días.", first_len
    if second_len < 7:
        return f"La segunda {what} quedaría con menos de 7 días en febrero: adelante el fin de la primera.", second_len
    return None, min(first_len, second_len)


class PayPeriod(models.Model):
    """Periodo de PAGO (Fase 11): fechas oficiales de devengo y fecha de pago (quincena 1–15 / 16–fin, mes).

    Ya no guarda la ventana de asistencia: los cortes internos son otra tabla (`AttendanceCutoff`) con sus propias
    reglas de traslape. Las horas de un periodo de pago son las de los cortes que se mapean a él.
    """

    cycle = models.ForeignKey(PayCycle, on_delete=models.PROTECT, related_name="periods", verbose_name="ciclo")
    code = models.CharField("código", max_length=40)
    period_start = models.DateField("inicio del periodo")
    period_end = models.DateField("fin del periodo")
    payment_date = models.DateField("fecha de pago")
    created_at = models.DateTimeField("creado", auto_now_add=True)

    class Meta:
        db_table = sql_table("wfm", "sch_pay_period")
        ordering = ["cycle_id", "period_start"]
        verbose_name = "periodo de pago"
        verbose_name_plural = "periodos de pago"
        constraints = [
            models.UniqueConstraint(fields=["cycle", "period_start"], name="uq_sch_pay_period_start"),
            models.UniqueConstraint(fields=["cycle", "code"], name="uq_sch_pay_period_code"),
            models.CheckConstraint(condition=Q(period_end__gte=models.F("period_start")), name="ck_sch_pay_period_dates"),
        ]

    def __str__(self) -> str:
        return f"{self.cycle.code} {self.code}"

    @property
    def crosses_month(self) -> bool:
        return (self.period_start.year, self.period_start.month) != (self.period_end.year, self.period_end.month)

    def clean(self):
        errors = {}
        if self.period_start and self.period_end and self.period_end < self.period_start:
            errors["period_end"] = "El fin del periodo no puede ser anterior a su inicio."
        if self.payment_date and self.period_start and self.payment_date < self.period_start:
            errors["payment_date"] = "La fecha de pago no puede ser anterior al inicio del periodo."
        if not errors and self.cycle_id and self.period_start:
            errors.update(self.continuity_errors())
        if not errors and self.pk and self.period_start and self.period_end:
            outside = self.cutoffs.exclude(cutoff_end__range=(self.period_start, self.period_end)).first()
            if outside:
                errors["period_end"] = (
                    f"El corte {outside.code} (cierra el {outside.cutoff_end:%d/%m/%Y}) está mapeado a este periodo: "
                    "el periodo debe contener esa fecha."
                )
        if errors:
            raise ValidationError(errors)

    def continuity_errors(self) -> dict:
        """Mismas reglas que SQL Server (50043 / 50045): el periodo continúa exactamente el día siguiente al fin del
        periodo de pago anterior del ciclo (sin hueco ni colisión) y no pisa al siguiente. Los cortes de asistencia
        tienen su propia validación (son otra dimensión)."""
        from datetime import timedelta

        errors = {}
        siblings = PayPeriod.objects.filter(cycle_id=self.cycle_id).exclude(pk=self.pk)
        prev = siblings.filter(period_start__lt=self.period_start).order_by("-period_start").first()
        nxt = siblings.filter(period_start__gt=self.period_start).order_by("period_start").first()
        if prev and self.period_start != prev.period_end + timedelta(days=1):
            kind = "se cruza con" if self.period_start <= prev.period_end else "deja un hueco después de"
            errors["period_start"] = (
                f"El periodo {kind} {prev.code} (termina el {prev.period_end:%d/%m/%Y}): debe iniciar el "
                f"{prev.period_end + timedelta(days=1):%d/%m/%Y}."
            )
        if nxt and self.period_end and self.period_end >= nxt.period_start:
            errors["period_end"] = f"El periodo se cruza con {nxt.code} (inicia el {nxt.period_start:%d/%m/%Y})."
        return errors


class AttendanceCutoff(models.Model):
    """Corte interno de asistencia (Fase 11): ventana operativa en la que se cuentan las horas trabajadas.

    Es INDEPENDIENTE del periodo de pago: puede cruzar de mes (del 25 al 9 y del 10 al 24) aunque la quincena sea
    del 1 al 15 y del 16 a fin de mes. Las ventanas de un ciclo no se traslapan ni dejan huecos entre sí, y cada una
    se mapea al periodo de pago más próximo: el que contiene su fecha de cierre (el corte 25/12–09/01 se paga en la
    quincena 1–15 de enero). Cerrar el corte bloquea cambios de tiempo y horarios en sus fechas.
    """

    class Status(models.TextChoices):
        OPEN = "OPEN", "Abierto"
        CLOSED = "CLOSED", "Cerrado"

    cycle = models.ForeignKey(PayCycle, on_delete=models.PROTECT, related_name="cutoffs", verbose_name="ciclo")
    pay_period = models.ForeignKey(PayPeriod, on_delete=models.PROTECT, related_name="cutoffs",
                                   verbose_name="periodo de pago", help_text="El que contiene la fecha de cierre del corte.")
    code = models.CharField("código", max_length=40)
    cutoff_start = models.DateField("asistencia desde")
    cutoff_end = models.DateField("asistencia hasta (cierre)")
    status = models.CharField("estado", max_length=6, choices=Status, default=Status.OPEN)
    closed_at = models.DateTimeField("cerrado", null=True, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="+", verbose_name="cerrado por")
    notes = models.CharField("notas", max_length=300, blank=True)
    created_at = models.DateTimeField("creado", auto_now_add=True)

    class Meta:
        db_table = sql_table("wfm", "sch_attendance_cutoff")
        ordering = ["cycle_id", "cutoff_start"]
        verbose_name = "corte interno de asistencia"
        verbose_name_plural = "cortes internos de asistencia"
        indexes = [models.Index(fields=["cycle", "cutoff_end"], name="ix_sch_cutoff_cycle_end")]
        constraints = [
            models.UniqueConstraint(fields=["cycle", "cutoff_start"], name="uq_sch_cutoff_start"),
            models.UniqueConstraint(fields=["cycle", "code"], name="uq_sch_cutoff_code"),
            models.CheckConstraint(condition=Q(cutoff_end__gte=models.F("cutoff_start")), name="ck_sch_cutoff_dates"),
            models.CheckConstraint(condition=Q(status__in=["OPEN", "CLOSED"]), name="ck_sch_cutoff_status"),
        ]

    def __str__(self) -> str:
        return f"{self.cycle.code} {self.code}"

    @property
    def crosses_month(self) -> bool:
        return (self.cutoff_start.year, self.cutoff_start.month) != (self.cutoff_end.year, self.cutoff_end.month)

    def clean(self):
        errors = {}
        if self.cutoff_start and self.cutoff_end and self.cutoff_end < self.cutoff_start:
            errors["cutoff_end"] = "El cierre no puede ser anterior al inicio de la ventana de asistencia."
        if not errors and self.cycle_id and self.cutoff_start:
            errors.update(self.continuity_errors())
            errors.update(self.mapping_errors())
        if errors:
            raise ValidationError(errors)

    def mapping_errors(self) -> dict:
        """Mismo criterio que SQL Server (50048): mismo ciclo y el periodo de pago contiene la fecha de cierre."""
        if not self.pay_period_id or not self.cutoff_end:
            return {}
        p = self.pay_period
        if p.cycle_id != self.cycle_id:
            return {"pay_period": f"El periodo {p.code} es de otro ciclo."}
        if not p.period_start <= self.cutoff_end <= p.period_end:
            target = PayPeriod.objects.filter(cycle_id=self.cycle_id, period_start__lte=self.cutoff_end,
                                              period_end__gte=self.cutoff_end).first()
            hint = f" Corresponde a {target.code}." if target else " Genere primero el periodo de pago que contiene esa fecha."
            return {"pay_period": (
                f"El corte cierra el {self.cutoff_end:%d/%m/%Y}: se mapea al periodo de pago que contiene esa fecha, no a "
                f"{p.code} ({p.period_start:%d/%m/%Y}–{p.period_end:%d/%m/%Y}).{hint}"
            )}
        return {}

    def continuity_errors(self) -> dict:
        """Mismas reglas que SQL Server (50044 / 50046): la ventana inicia el día siguiente al cierre de la ventana
        anterior del ciclo (sin hueco ni colisión) y no pisa a la siguiente. No depende de los periodos de pago."""
        from datetime import timedelta

        errors = {}
        siblings = AttendanceCutoff.objects.filter(cycle_id=self.cycle_id).exclude(pk=self.pk)
        prev = siblings.filter(cutoff_start__lt=self.cutoff_start).order_by("-cutoff_start").first()
        nxt = siblings.filter(cutoff_start__gt=self.cutoff_start).order_by("cutoff_start").first()
        if prev and self.cutoff_start != prev.cutoff_end + timedelta(days=1):
            kind = "se cruza con" if self.cutoff_start <= prev.cutoff_end else "deja un hueco después de"
            errors["cutoff_start"] = (
                f"La ventana {kind} el corte {prev.code} (cierra el {prev.cutoff_end:%d/%m/%Y}): debe iniciar el "
                f"{prev.cutoff_end + timedelta(days=1):%d/%m/%Y}."
            )
        if nxt and self.cutoff_end and self.cutoff_end >= nxt.cutoff_start:
            errors["cutoff_end"] = f"La ventana se cruza con el corte {nxt.code} (inicia el {nxt.cutoff_start:%d/%m/%Y})."
        return errors


# ---------------------------------------------------------------- registros de tiempo
class TimeRecord(models.Model):
    class Kind(models.TextChoices):
        INTERVAL = "INTERVAL", "Entrada y salida"
        DURATION = "DURATION", "Horas reportadas para una fecha"

    class Source(models.TextChoices):
        MANUAL = "MANUAL", "Registro manual"
        IMPORT = "IMPORT", "Carga de archivo"
        WFM = "WFM", "WFM externo"
        BIOMETRIC = "BIOMETRIC", "Biométrico / reloj"
        API = "API", "Integración (API)"
        WEB_TIMER = "WEB_TIMER", "Web Timer interno"  # Fase 10: futuro módulo de marcación (la carga manual está retirada)

    employee = _employee_fk("time_records")
    kind = models.CharField("tipo", max_length=8, choices=Kind)
    start_at = WallClockDateTimeField("entrada (hora local)", null=True, blank=True)
    end_at = WallClockDateTimeField("salida (hora local)", null=True, blank=True)
    occurrence_date = models.DateField("fecha de ocurrencia (inicio)",
                                       help_text="Intervalos: fecha de la entrada. Duraciones: fecha en que se laboró.")
    minutes = models.PositiveIntegerField("minutos")
    shift_date = models.DateField("fecha del turno", null=True, blank=True,
                                  help_text="Jornada programada a la que pertenece (trazabilidad); vacío = sin turno programado.")
    source = models.CharField("origen", max_length=10, choices=Source, default=Source.MANUAL)
    external_ref = models.CharField("referencia externa", max_length=100, blank=True)
    upload_ref = models.CharField("lote", max_length=64, blank=True, db_index=True)
    notes = models.CharField("notas", max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+", verbose_name="registrado por")
    created_at = models.DateTimeField("registrado", auto_now_add=True)

    class Meta:
        db_table = sql_table("wfm", "sch_time_record")
        ordering = ["employee_id", "occurrence_date", "start_at"]
        verbose_name = "registro de tiempo"
        verbose_name_plural = "registros de tiempo"
        indexes = [models.Index(fields=["employee", "occurrence_date"], name="ix_sch_time_emp_date")]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(kind="INTERVAL", start_at__isnull=False, end_at__isnull=False, end_at__gt=models.F("start_at"))
                    | Q(kind="DURATION", start_at__isnull=True, end_at__isnull=True)
                ),
                name="ck_sch_time_record_kind",
            ),
            models.CheckConstraint(condition=Q(minutes__gt=0, minutes__lte=1440), name="ck_sch_time_record_minutes"),
            # Horas reportadas: una sola fila por empleado, fecha y origen (evita contarlas dos veces).
            models.UniqueConstraint(
                fields=["employee", "occurrence_date", "source"], condition=Q(kind="DURATION"),
                name="uq_sch_time_record_duration",
            ),
        ]

    def __str__(self) -> str:
        if self.kind == self.Kind.INTERVAL:
            return f"{self.start_at:%d/%m/%Y %H:%M} → {self.end_at:%d/%m/%Y %H:%M}"
        return f"{self.occurrence_date:%d/%m/%Y} · {engine.fmt_minutes(self.minutes)} h"


class TimeRecordDay(models.Model):
    """Porción de un registro en un día calendario de ocurrencia (para reportes y JOINs)."""

    record = models.ForeignKey(TimeRecord, on_delete=models.CASCADE, related_name="days", verbose_name="registro")
    employee = _employee_fk("+")
    occurrence_date = models.DateField("fecha de ocurrencia")
    start_at = WallClockDateTimeField("desde", null=True, blank=True)
    end_at = WallClockDateTimeField("hasta", null=True, blank=True)
    minutes = models.PositiveIntegerField("minutos")
    night_minutes = models.PositiveIntegerField("minutos nocturnos", default=0)
    night_rule = models.ForeignKey(NightRule, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                   verbose_name="regla de nocturnidad aplicada")
    shift_date = models.DateField("fecha del turno", null=True, blank=True)

    class Meta:
        db_table = sql_table("wfm", "sch_time_record_day")
        ordering = ["occurrence_date", "start_at"]
        verbose_name = "tiempo por fecha de ocurrencia"
        verbose_name_plural = "tiempo por fecha de ocurrencia"
        indexes = [models.Index(fields=["employee", "occurrence_date"], name="ix_sch_time_day_emp_date")]
        constraints = [
            models.UniqueConstraint(fields=["record", "occurrence_date"], name="uq_sch_time_day_record_date"),
            models.CheckConstraint(condition=Q(minutes__lte=1440), name="ck_sch_time_day_minutes"),
            models.CheckConstraint(condition=Q(night_minutes__lte=models.F("minutes")), name="ck_sch_time_day_night"),
        ]
