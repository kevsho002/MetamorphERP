"""Esquema `fin`: Planillas y retenciones legales configurables (SQL-first, managed = False) y, desde la Fase 20,
cálculo automático de planilla y control de boletas físicas (tablas `fin.pay_*` administradas por Django)."""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q, Value
from django.db.models.functions import Now

from apps.common.fields import AuditColumns, RowVersionField, sql_table
from apps.common.models import CostCenter, Country
from apps.hcm.models import Employee

UPPER_CODE = RegexValidator(r"^[A-Z][A-Z0-9_]*$", "Use MAYÚSCULAS, dígitos y guion bajo; debe iniciar con letra.")


class DeductionType(models.Model):
    """fin.catDeductionType — regla de retención por país, con vigencia."""

    deduction_type_id = models.AutoField(db_column="DeductionTypeId", primary_key=True)
    country = models.ForeignKey(Country, models.DO_NOTHING, db_column="CountryId", related_name="deduction_types")
    code = models.CharField(db_column="Code", max_length=30)
    name = models.CharField(db_column="Name", max_length=150)
    category = models.CharField(db_column="Category", max_length=20)
    party = models.CharField(db_column="Party", max_length=10)
    calculation_method = models.CharField(db_column="CalculationMethod", max_length=12)
    rate = models.DecimalField(db_column="Rate", max_digits=9, decimal_places=6, null=True, blank=True)
    fixed_amount = models.DecimalField(db_column="FixedAmount", max_digits=18, decimal_places=2, null=True, blank=True)
    base_cap = models.DecimalField(db_column="BaseCap", max_digits=18, decimal_places=2, null=True, blank=True)
    reduces_taxable_base = models.BooleanField(db_column="ReducesTaxableBase", db_default=Value(False))
    calculation_order = models.SmallIntegerField(db_column="CalculationOrder", db_default=Value(100))
    effective_start_date = models.DateField(db_column="EffectiveStartDate")
    effective_end_date = models.DateField(db_column="EffectiveEndDate", null=True, blank=True)
    legal_reference = models.CharField(db_column="LegalReference", max_length=300, null=True, blank=True)
    is_active = models.BooleanField(db_column="IsActive", db_default=Value(True))
    created_at = models.DateTimeField(db_column="CreatedAt", db_default=Now(), editable=False)
    created_by = models.CharField(db_column="CreatedBy", max_length=100, db_default=Value(""), editable=False)

    class Meta:
        managed = False
        db_table = sql_table("fin", "catDeductionType")


class DeductionBracket(models.Model):
    """fin.DeductionBracket — Monto = FixedFee + (Base - ExcessOver) * Rate."""

    deduction_bracket_id = models.AutoField(db_column="DeductionBracketId", primary_key=True)
    deduction_type = models.ForeignKey(
        DeductionType, models.DO_NOTHING, db_column="DeductionTypeId", related_name="brackets"
    )
    pay_frequency = models.CharField(db_column="PayFrequency", max_length=15)
    lower_bound = models.DecimalField(db_column="LowerBound", max_digits=18, decimal_places=2)
    upper_bound = models.DecimalField(db_column="UpperBound", max_digits=18, decimal_places=2, null=True, blank=True)
    rate = models.DecimalField(db_column="Rate", max_digits=9, decimal_places=6)
    fixed_fee = models.DecimalField(db_column="FixedFee", max_digits=18, decimal_places=2, db_default=Value(0))
    excess_over = models.DecimalField(db_column="ExcessOver", max_digits=18, decimal_places=2, db_default=Value(0))

    class Meta:
        managed = False
        db_table = sql_table("fin", "DeductionBracket")
        ordering = ["lower_bound"]


class Payroll(AuditColumns):
    """fin.Payroll ("Planillas") — encabezado por país, frecuencia y periodo."""

    payroll_id = models.AutoField(db_column="PayrollId", primary_key=True)
    payroll_code = models.CharField(db_column="PayrollCode", max_length=40, unique=True)
    country = models.ForeignKey(Country, models.DO_NOTHING, db_column="CountryId", related_name="payrolls")
    pay_frequency = models.CharField(db_column="PayFrequency", max_length=15)
    period_start = models.DateField(db_column="PeriodStart")
    period_end = models.DateField(db_column="PeriodEnd")
    payment_date = models.DateField(db_column="PaymentDate")
    payroll_status = models.CharField(db_column="PayrollStatus", max_length=15, db_default=Value("DRAFT"))
    currency_code = models.CharField(db_column="CurrencyCode", max_length=3)
    total_gross = models.DecimalField(db_column="TotalGross", max_digits=18, decimal_places=2, db_default=Value(0))
    total_deductions = models.DecimalField(
        db_column="TotalDeductions", max_digits=18, decimal_places=2, db_default=Value(0)
    )
    total_net = models.DecimalField(db_column="TotalNet", max_digits=18, decimal_places=2, db_default=Value(0))
    total_employer_cost = models.DecimalField(
        db_column="TotalEmployerCost", max_digits=18, decimal_places=2, db_default=Value(0)
    )
    approved_at = models.DateTimeField(db_column="ApprovedAt", null=True, blank=True)
    approved_by = models.CharField(db_column="ApprovedBy", max_length=100, null=True, blank=True)
    row_ver = RowVersionField()

    class Meta:
        managed = False
        db_table = sql_table("fin", "Payroll")


class PayrollDetail(models.Model):
    """fin.PayrollDetail — una línea por empleado (snapshot de montos)."""

    payroll_detail_id = models.BigAutoField(db_column="PayrollDetailId", primary_key=True)
    payroll = models.ForeignKey(Payroll, models.DO_NOTHING, db_column="PayrollId", related_name="details")
    employee = models.ForeignKey(Employee, models.DO_NOTHING, db_column="EmployeeId")
    base_salary = models.DecimalField(db_column="BaseSalary", max_digits=18, decimal_places=2)
    paid_days = models.DecimalField(db_column="PaidDays", max_digits=5, decimal_places=2)
    worked_minutes = models.IntegerField(db_column="WorkedMinutes", db_default=Value(0))
    overtime_amount = models.DecimalField(db_column="OvertimeAmount", max_digits=18, decimal_places=2, db_default=Value(0))
    other_earnings = models.DecimalField(db_column="OtherEarnings", max_digits=18, decimal_places=2, db_default=Value(0))
    gross_pay = models.DecimalField(db_column="GrossPay", max_digits=18, decimal_places=2)
    taxable_base = models.DecimalField(db_column="TaxableBase", max_digits=18, decimal_places=2)
    total_deductions = models.DecimalField(db_column="TotalDeductions", max_digits=18, decimal_places=2)
    net_pay = models.DecimalField(db_column="NetPay", max_digits=18, decimal_places=2)
    employer_contributions = models.DecimalField(
        db_column="EmployerContributions", max_digits=18, decimal_places=2, db_default=Value(0)
    )

    class Meta:
        managed = False
        db_table = sql_table("fin", "PayrollDetail")


class PayrollDeduction(models.Model):
    """fin.PayrollDeduction — retención aplicada (base y tasa congeladas)."""

    payroll_deduction_id = models.BigAutoField(db_column="PayrollDeductionId", primary_key=True)
    payroll_detail = models.ForeignKey(
        PayrollDetail, models.DO_NOTHING, db_column="PayrollDetailId", related_name="deductions"
    )
    deduction_type = models.ForeignKey(DeductionType, models.DO_NOTHING, db_column="DeductionTypeId")
    party = models.CharField(db_column="Party", max_length=10)
    calculation_base = models.DecimalField(db_column="CalculationBase", max_digits=18, decimal_places=2)
    applied_rate = models.DecimalField(db_column="AppliedRate", max_digits=9, decimal_places=6, null=True, blank=True)
    amount = models.DecimalField(db_column="Amount", max_digits=18, decimal_places=2)

    class Meta:
        managed = False
        db_table = sql_table("fin", "PayrollDeduction")


# =====================================================================================================================
# Fase 20 — Cálculo automático de planilla y control de boletas físicas (tablas administradas por Django en `dbo`).
#
#   pay_setting          parámetros salariales por país con vigencia: días por mes, horas por día, recargo de horas
#                        extra, prima de vacaciones y qué penalizaciones de asistencia se descuentan (Lateness,
#                        Unjustified Absence + séptimo día, permisos sin goce, tiempo no laborado / Out of Adherence)
#   pay_concept          catálogo de conceptos de la boleta (devengos, descuentos de tiempo, descuentos por AP) con
#                        su afectación a ISSS / AFP y a Renta
#   pay_payroll_run      metadatos del cálculo de un fin.Payroll: periodo de pago (sch_pay_period), ventanas de
#                        asistencia usadas, parámetros, quién calculó / cerró / pagó y advertencias
#   pay_payroll_line     líneas de la boleta por empleado: devengos (+), descuentos de tiempo (−), retenciones de
#                        ley, aportes patronales e información (Web Timer, adherencia), con su origen y la AP
#   pay_payslip_batch    LOTE de boletas físicas por periodo y departamento (centro de costos): ubicación de archivo
#   pay_payslip          BOLETA individual (folio, contenido congelado con sello SHA-256) y su control físico:
#                        impresa / faltante, firmada / pendiente de firma, archivada
#
# Las retenciones de ley siguen en fin.catDeductionType / fin.DeductionBracket (SQL-first, con vigencia) y el
# resultado en fin.Payroll / fin.PayrollDetail / fin.PayrollDeduction. Las FKs, los triggers (50090–50093) y las
# vistas se crean en la migración 0002.
# =====================================================================================================================


def _country_fk(**kwargs):
    return models.ForeignKey(Country, on_delete=models.DO_NOTHING, db_column="country_id", db_constraint=False,
                             verbose_name="país", **kwargs)


def _employee_fk(related_name: str):
    return models.ForeignKey(Employee, on_delete=models.DO_NOTHING, db_column="employee_id", db_constraint=False,
                             related_name=related_name, verbose_name="empleado")


class PayrollSetting(models.Model):
    """Parámetros salariales por país y vigencia (un cambio de ley o de política = nueva vigencia)."""

    country = _country_fk(related_name="+")
    name = models.CharField("nombre", max_length=120)
    effective_start_date = models.DateField("vigente desde")
    effective_end_date = models.DateField("vigente hasta", null=True, blank=True)
    days_per_month = models.PositiveSmallIntegerField(
        "días por mes", default=30, validators=[MinValueValidator(28), MaxValueValidator(31)],
        help_text="Divisor del salario diario (mes comercial de 30 días).")
    hours_per_day = models.DecimalField(
        "horas por día", max_digits=4, decimal_places=2, default=8, validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text="Divisor del salario por hora (jornada ordinaria diurna).")
    overtime_surcharge_percent = models.DecimalField(
        "recargo de horas extra (%)", max_digits=6, decimal_places=2, default=100,
        validators=[MinValueValidator(0), MaxValueValidator(500)],
        help_text="Sobre el valor de la hora ordinaria (100 = se paga el doble). La nocturnidad usa la regla del país.")
    vacation_premium_percent = models.DecimalField(
        "prima de vacaciones (%)", max_digits=6, decimal_places=2, default=30,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Sobre el salario de los días de vacaciones de la AP (30 = 30 %).")
    # Fase 21: motor 100 % por horas (estándar BPO). Las horas no laboradas (ausencias, Lateness, permisos sin goce,
    # suspensiones) simplemente no se pagan; el séptimo día es OPCIONAL y cada cuenta puede activarlo (pay_account_rule).
    seventh_day_penalty = models.BooleanField(
        "pérdida del séptimo día (predeterminado)", default=False,
        help_text="Una semana con Unjustified Absence pierde además las horas de un día de descanso. Cada cuenta (cliente) "
                  "puede activarlo o desactivarlo con su propia regla.")
    holiday_premium_percent = models.DecimalField(
        "recargo por feriado laborado (%)", max_digits=6, decimal_places=2, default=100,
        validators=[MinValueValidator(0), MaxValueValidator(300)],
        help_text="Si el feriado del calendario no define el suyo. 100 = pago doble (horas regulares + 100 %).")
    preliminary_lead_days = models.PositiveSmallIntegerField(
        "corridas preliminares desde (días antes del fin del corte)", default=14,
        validators=[MinValueValidator(0), MaxValueValidator(31)],
        help_text="14 = la corrida diaria automática inicia el día 10 para el corte que termina el 24.")
    publish_preliminary = models.BooleanField(
        "publicar boletas preliminares", default=True,
        help_text="Cada cálculo previo al cierre publica la boleta preliminar en el portal del colaborador.")
    # Liquidaciones e indemnizaciones (Código de Trabajo y Ley de Renuncia Voluntaria; valores de referencia).
    minimum_wage_monthly = models.DecimalField(
        "salario mínimo mensual de referencia", max_digits=10, decimal_places=2, default=Decimal("408.80"),
        help_text="Comercio y servicios. Base de los topes de indemnización, renuncia voluntaria y aguinaldo exento.")
    indemnity_days_per_year = models.PositiveSmallIntegerField("indemnización: días por año", default=30)
    indemnity_cap_multiplier = models.DecimalField("indemnización: tope (× salario mínimo)", max_digits=5, decimal_places=2,
                                                   default=4)
    indemnity_min_days = models.PositiveSmallIntegerField("indemnización: mínimo (días)", default=15)
    resignation_days_per_year = models.PositiveSmallIntegerField("renuncia voluntaria: días por año", default=15)
    resignation_cap_multiplier = models.DecimalField("renuncia voluntaria: tope (× salario mínimo)", max_digits=5,
                                                     decimal_places=2, default=2)
    resignation_min_years = models.PositiveSmallIntegerField("renuncia voluntaria: años mínimos", default=2)
    vacation_days_per_year = models.PositiveSmallIntegerField("vacaciones: días por año", default=15)
    aguinaldo_tiers = models.JSONField(
        "aguinaldo: días por antigüedad", default=list, blank=True,
        help_text='[{"min_years": 0, "days": 15}, {"min_years": 3, "days": 19}, {"min_years": 10, "days": 21}]')
    aguinaldo_exempt_multiplier = models.DecimalField("aguinaldo exento de Renta (× salario mínimo)", max_digits=5,
                                                      decimal_places=2, default=2)
    require_closed_cutoffs = models.BooleanField(
        "exigir cortes cerrados para el cierre", default=True,
        help_text="El cierre de la planilla (y la generación de boletas) exige los cortes de asistencia del periodo cerrados.")
    legal_reference = models.CharField("base legal / política", max_length=300, blank=True)
    is_active = models.BooleanField("activa", default=True)
    created_at = models.DateTimeField("creada", auto_now_add=True)
    updated_at = models.DateTimeField("actualizada", auto_now=True)

    class Meta:
        db_table = sql_table("fin", "pay_setting")
        ordering = ["country_id", "-effective_start_date"]
        verbose_name = "parámetros salariales"
        verbose_name_plural = "parámetros salariales (por país y vigencia)"
        constraints = [
            models.UniqueConstraint(fields=["country", "effective_start_date"], name="uq_pay_setting_start"),
            models.CheckConstraint(
                condition=Q(effective_end_date__isnull=True) | Q(effective_end_date__gte=models.F("effective_start_date")),
                name="ck_pay_setting_dates"),
            models.CheckConstraint(condition=Q(days_per_month__gte=28, days_per_month__lte=31), name="ck_pay_setting_days"),
            models.CheckConstraint(condition=Q(hours_per_day__gte=1, hours_per_day__lte=12), name="ck_pay_setting_hours"),
            models.CheckConstraint(condition=Q(overtime_surcharge_percent__gte=0, overtime_surcharge_percent__lte=500,
                                               vacation_premium_percent__gte=0, vacation_premium_percent__lte=100),
                                   name="ck_pay_setting_percents"),
            models.CheckConstraint(condition=Q(holiday_premium_percent__gte=0, holiday_premium_percent__lte=300,
                                               minimum_wage_monthly__gt=0), name="ck_pay_setting_phase21"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.effective_start_date:%d/%m/%Y})"


class PayConcept(models.Model):
    """Concepto de la boleta. `kind` define en qué columna cae; las banderas, su afectación a las retenciones."""

    class Kind(models.TextChoices):
        EARNING = "EARNING", "Devengo"
        TIME_DISCOUNT = "TIME_DISCOUNT", "Descuento de tiempo (reduce el devengado)"
        DEDUCTION = "DEDUCTION", "Descuento autorizado (después de retenciones)"

    class Source(models.TextChoices):
        SALARY = "SALARY", "Salario base"
        WEB_TIMER = "WEB_TIMER", "Web Timer (tiempo real)"
        ADHERENCE = "ADHERENCE", "Segmentos y adherencia (WFM)"
        PERSONNEL_ACTION = "AP", "Acción de personal"

    class Calculation(models.TextChoices):
        ENGINE = "ENGINE", "Lo calcula el motor (salario, tiempo, nocturnidad)"
        AMOUNT = "AMOUNT", "Monto de la AP"
        OVERTIME_DAY = "OVERTIME_DAY", "Horas extra diurnas de la AP × hora ordinaria × (1 + recargo)"
        OVERTIME_NIGHT = "OVERTIME_NIGHT", "Horas extra nocturnas de la AP × hora ordinaria × (1 + nocturnidad) × (1 + recargo)"
        VACATION_PREMIUM = "VACATION", "Días de vacaciones de la AP × salario diario × prima"

    code = models.CharField("código", max_length=30, unique=True, validators=[UPPER_CODE])
    name = models.CharField("nombre", max_length=120)
    kind = models.CharField("tipo", max_length=13, choices=Kind)
    source = models.CharField("origen", max_length=10, choices=Source)
    calculation = models.CharField("cálculo", max_length=14, choices=Calculation, default=Calculation.ENGINE)
    action_type_code = models.CharField("tipo de AP que lo alimenta", max_length=40, blank=True,
                                        help_text="Código del tipo de AP con efecto «Concepto de planilla» (p. ej. AP_BONIFICACION).")
    action_attribute_key = models.CharField("campo de la AP", max_length=40, blank=True,
                                            help_text="Clave del campo de la AP con el monto, las horas o los días.")
    affects_social_security = models.BooleanField("cotiza ISSS / AFP", default=True)
    affects_income_tax = models.BooleanField("gravado (Renta)", default=True)
    display_order = models.PositiveSmallIntegerField("orden", default=100)
    is_active = models.BooleanField("activo", default=True)
    description = models.CharField("descripción", max_length=300, blank=True)

    class Meta:
        db_table = sql_table("fin", "pay_concept")
        ordering = ["display_order", "code"]
        verbose_name = "concepto de planilla"
        verbose_name_plural = "conceptos de planilla"
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=["EARNING", "TIME_DISCOUNT", "DEDUCTION"]), name="ck_pay_concept_kind"),
            models.CheckConstraint(condition=Q(source__in=["SALARY", "WEB_TIMER", "ADHERENCE", "AP"]), name="ck_pay_concept_source"),
            models.CheckConstraint(condition=Q(calculation="ENGINE") | ~Q(action_type_code="") & ~Q(action_attribute_key=""),
                                   name="ck_pay_concept_action"),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class PayrollRun(models.Model):
    """Metadatos del cálculo de una planilla (fin.Payroll ↔ periodo de pago del ciclo)."""

    payroll = models.OneToOneField(Payroll, on_delete=models.DO_NOTHING, db_column="payroll_id", db_constraint=False,
                                   related_name="run", verbose_name="planilla")
    pay_period = models.OneToOneField("scheduling.PayPeriod", on_delete=models.PROTECT, related_name="payroll_run",
                                      verbose_name="periodo de pago")
    setting = models.ForeignKey(PayrollSetting, on_delete=models.PROTECT, null=True, blank=True, related_name="runs",
                                verbose_name="parámetros usados")
    windows = models.JSONField("ventanas de asistencia usadas", default=list)
    employees = models.PositiveIntegerField("colaboradores", default=0)
    warnings = models.JSONField("advertencias", default=list)
    calculated_at = models.DateTimeField("calculada", null=True, blank=True)
    calculated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name="+", verbose_name="calculada por")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="cerrada por")
    paid_at = models.DateTimeField("pagada", null=True, blank=True)
    paid_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="+", verbose_name="pagada por")
    cancel_reason = models.CharField("motivo de anulación", max_length=500, blank=True)
    created_at = models.DateTimeField("creada", auto_now_add=True)
    # Fase 21: pre-cierre iterativo y boletas preliminares
    iterations = models.PositiveIntegerField("corridas", default=0)
    preliminary_published_at = models.DateTimeField("boletas preliminares publicadas", null=True, blank=True)

    class Meta:
        db_table = sql_table("fin", "pay_payroll_run")
        ordering = ["-id"]
        verbose_name = "cálculo de planilla"
        verbose_name_plural = "cálculos de planilla"

    def __str__(self) -> str:
        return f"Planilla {self.payroll_id} · periodo {self.pay_period_id}"


class PayrollLine(models.Model):
    """Línea de la boleta: `amount` con signo (los descuentos de tiempo son negativos dentro del devengado)."""

    class Kind(models.TextChoices):
        EARNING = "EARNING", "Devengo"
        TIME_DISCOUNT = "TIME_DISCOUNT", "Descuento de tiempo"
        LEGAL = "LEGAL", "Retención de ley"
        DEDUCTION = "DEDUCTION", "Descuento autorizado"
        EMPLOYER = "EMPLOYER", "Aporte patronal"
        INFO = "INFO", "Información (sin monto)"

    id = models.BigAutoField(primary_key=True)
    payroll = models.ForeignKey(Payroll, on_delete=models.DO_NOTHING, db_column="payroll_id", db_constraint=False,
                                related_name="lines", verbose_name="planilla")
    detail = models.ForeignKey(PayrollDetail, on_delete=models.DO_NOTHING, db_column="payroll_detail_id", db_constraint=False,
                               related_name="lines", verbose_name="línea de planilla")
    employee = _employee_fk("+")
    kind = models.CharField("tipo", max_length=13, choices=Kind)
    code = models.CharField("código", max_length=30)
    label = models.CharField("descripción", max_length=200)
    concept = models.ForeignKey(PayConcept, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                verbose_name="concepto")
    deduction_type = models.ForeignKey(DeductionType, on_delete=models.DO_NOTHING, db_column="deduction_type_id",
                                       db_constraint=False, null=True, blank=True, related_name="+", verbose_name="retención")
    quantity = models.DecimalField("cantidad", max_digits=12, decimal_places=4, null=True, blank=True)
    unit = models.CharField("unidad", max_length=10, blank=True)
    rate = models.DecimalField("valor unitario / tasa", max_digits=18, decimal_places=6, null=True, blank=True)
    base = models.DecimalField("base de cálculo", max_digits=18, decimal_places=2, null=True, blank=True)
    amount = models.DecimalField("monto", max_digits=18, decimal_places=2, default=0)
    source = models.CharField("origen", max_length=10, blank=True)
    personnel_action = models.ForeignKey("personnel_actions.PersonnelAction", on_delete=models.PROTECT, null=True, blank=True,
                                         related_name="payroll_lines", verbose_name="AP")
    notes = models.CharField("detalle", max_length=300, blank=True)
    sort = models.PositiveSmallIntegerField("orden", default=100)

    class Meta:
        db_table = sql_table("fin", "pay_payroll_line")
        ordering = ["detail_id", "sort", "id"]
        verbose_name = "línea de boleta"
        verbose_name_plural = "líneas de boleta"
        indexes = [models.Index(fields=["payroll", "employee"], name="ix_pay_line_payroll_emp")]
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=["EARNING", "TIME_DISCOUNT", "LEGAL", "DEDUCTION", "EMPLOYER", "INFO"]), name="ck_pay_line_kind"),
            models.CheckConstraint(
                condition=Q(kind="TIME_DISCOUNT", amount__lte=0) | Q(kind="INFO", amount=0)
                | Q(kind__in=["EARNING", "LEGAL", "DEDUCTION", "EMPLOYER"], amount__gte=0),
                name="ck_pay_line_sign"),
            # Una AP de pago se paga una sola vez (por concepto) entre todas las planillas vigentes.
            models.UniqueConstraint(fields=["personnel_action", "code"], condition=Q(personnel_action__isnull=False),
                                    name="uq_pay_line_action_code"),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.amount}"


class PayrollDay(models.Model):
    """Fase 25 — Boleta DIARIA: cada fecha de los cortes internos de asistencia con sus horas y su traducción exacta a
    dinero. Los montos del día se reparten de las líneas por tiempo de la boleta (salario por horas, vacaciones,
    nocturnidad, feriados y séptimo día) al centavo, de modo que la suma de los días es igual a esas líneas."""

    class DayType(models.TextChoices):
        WORKED = "WORKED", "Laborado"
        PARTIAL = "PARTIAL", "Laborado parcial"
        HOLIDAY = "HOLIDAY", "Feriado laborado"
        VACATION = "VACATION", "Vacaciones"
        ABSENCE = "ABSENCE", "Ausencia injustificada"
        UNPAID = "UNPAID", "Programado sin pago"
        REST = "REST", "Descanso"
        SUSPENDED = "SUSPENDED", "Suspensión"
        OUTSIDE = "OUTSIDE", "Fuera de la relación laboral"

    id = models.BigAutoField(primary_key=True)
    payroll = models.ForeignKey(Payroll, on_delete=models.DO_NOTHING, db_column="payroll_id", db_constraint=False,
                                related_name="days", verbose_name="planilla")
    detail = models.ForeignKey(PayrollDetail, on_delete=models.DO_NOTHING, db_column="payroll_detail_id", db_constraint=False,
                               related_name="days", verbose_name="línea de planilla")
    employee = _employee_fk("+")
    work_date = models.DateField("fecha")
    cutoff_code = models.CharField("corte de asistencia", max_length=40, blank=True)
    day_type = models.CharField("tipo de día", max_length=10, choices=DayType)
    holiday_name = models.CharField("feriado", max_length=120, blank=True)
    scheduled_seconds = models.PositiveIntegerField("programado (s)", default=0)
    worked_seconds = models.PositiveIntegerField("registrado (s)", default=0)
    paid_seconds = models.PositiveIntegerField("pagable (s)", default=0)
    night_seconds = models.PositiveIntegerField("nocturno (s)", default=0)
    vacation_seconds = models.PositiveIntegerField("vacaciones (s)", default=0)
    lateness_seconds = models.PositiveIntegerField("lateness (s)", default=0)
    regular_amount = models.DecimalField("salario por horas", max_digits=12, decimal_places=2, default=0)
    vacation_amount = models.DecimalField("vacaciones", max_digits=12, decimal_places=2, default=0)
    night_amount = models.DecimalField("nocturnidad", max_digits=12, decimal_places=2, default=0)
    holiday_amount = models.DecimalField("recargo de feriado", max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField("descuento (séptimo día)", max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField("total del día", max_digits=12, decimal_places=2, default=0)
    notes = models.CharField("detalle", max_length=300, blank=True)

    class Meta:
        db_table = sql_table("fin", "pay_payroll_day")
        ordering = ["detail_id", "work_date"]
        verbose_name = "día de la boleta"
        verbose_name_plural = "días de la boleta"
        indexes = [models.Index(fields=["employee", "work_date"], name="ix_pay_day_employee_date")]
        constraints = [
            models.UniqueConstraint(fields=["detail", "work_date"], name="uq_pay_day_detail_date"),
            models.CheckConstraint(condition=Q(day_type__in=["WORKED", "PARTIAL", "HOLIDAY", "VACATION", "ABSENCE", "UNPAID", "REST",
                                                              "SUSPENDED", "OUTSIDE"]), name="ck_pay_day_type"),
            models.CheckConstraint(condition=Q(discount_amount__lte=0) & Q(regular_amount__gte=0) & Q(vacation_amount__gte=0)
                                   & Q(night_amount__gte=0) & Q(holiday_amount__gte=0), name="ck_pay_day_sign"),
            models.CheckConstraint(
                condition=Q(total_amount=models.F("regular_amount") + models.F("vacation_amount") + models.F("night_amount")
                            + models.F("holiday_amount") + models.F("discount_amount")), name="ck_pay_day_total"),
        ]

    def __str__(self) -> str:
        return f"{self.employee_id} · {self.work_date} · {self.total_amount}"


class PayslipBatch(models.Model):
    """Lote físico de boletas de un periodo (quincena / mes) y departamento (centro de costos)."""

    payroll = models.ForeignKey(Payroll, on_delete=models.DO_NOTHING, db_column="payroll_id", db_constraint=False,
                                related_name="batches", verbose_name="planilla")
    cost_center = models.ForeignKey(CostCenter, on_delete=models.DO_NOTHING, db_column="cost_center_id", db_constraint=False,
                                    null=True, blank=True, related_name="+", verbose_name="departamento (centro de costos)")
    code = models.CharField("lote", max_length=60, unique=True)
    archive_location = models.CharField("ubicación de archivo", max_length=150, blank=True,
                                        help_text="Caja / ampo / estante donde se archivan las boletas firmadas.")
    notes = models.CharField("notas", max_length=300, blank=True)
    created_at = models.DateTimeField("generado", auto_now_add=True)

    class Meta:
        db_table = sql_table("fin", "pay_payslip_batch")
        ordering = ["payroll_id", "code"]
        verbose_name = "lote de boletas"
        verbose_name_plural = "lotes de boletas (por periodo y departamento)"
        constraints = [models.UniqueConstraint(fields=["payroll", "cost_center"], name="uq_pay_batch_payroll_cc")]

    def __str__(self) -> str:
        return self.code


class Payslip(models.Model):
    """Boleta de pago individual: contenido congelado al cierre y control físico (impresión, firma, archivo)."""

    id = models.BigAutoField(primary_key=True)
    folio = models.CharField("folio", max_length=60, unique=True)
    payroll = models.ForeignKey(Payroll, on_delete=models.DO_NOTHING, db_column="payroll_id", db_constraint=False,
                                related_name="payslips", verbose_name="planilla")
    detail = models.OneToOneField(PayrollDetail, on_delete=models.DO_NOTHING, db_column="payroll_detail_id",
                                  db_constraint=False, related_name="payslip", verbose_name="línea de planilla")
    batch = models.ForeignKey(PayslipBatch, on_delete=models.PROTECT, related_name="payslips", verbose_name="lote")
    employee = _employee_fk("payslips")
    cost_center = models.ForeignKey(CostCenter, on_delete=models.DO_NOTHING, db_column="cost_center_id", db_constraint=False,
                                    null=True, blank=True, related_name="+", verbose_name="departamento al cierre")
    period_start = models.DateField("inicio del periodo")
    period_end = models.DateField("fin del periodo")
    payment_date = models.DateField("fecha de pago")
    pay_frequency = models.CharField("frecuencia", max_length=15)
    gross_pay = models.DecimalField("devengado", max_digits=18, decimal_places=2)
    total_deductions = models.DecimalField("descuentos", max_digits=18, decimal_places=2)
    net_pay = models.DecimalField("líquido a recibir", max_digits=18, decimal_places=2)
    content = models.JSONField("contenido de la boleta (congelado)")
    content_hash = models.CharField("sello del contenido (SHA-256)", max_length=64)
    generated_at = models.DateTimeField("generada")
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+", verbose_name="generada por")
    # ---- control físico (inventario de RRHH)
    printed_at = models.DateTimeField("impresa", null=True, blank=True)
    printed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+", verbose_name="impresa por")
    print_count = models.PositiveSmallIntegerField("impresiones", default=0)
    signed_on = models.DateField("firmada por el colaborador el", null=True, blank=True)
    signed_recorded_at = models.DateTimeField("firma registrada", null=True, blank=True)
    signed_recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                           related_name="+", verbose_name="firma registrada por")
    archived_at = models.DateTimeField("archivada", null=True, blank=True)
    archived_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="archivada por")
    archive_location = models.CharField("ubicación de archivo", max_length=150, blank=True)
    notes = models.CharField("observaciones", max_length=300, blank=True)

    class Meta:
        db_table = sql_table("fin", "pay_payslip")
        ordering = ["payroll_id", "folio"]
        verbose_name = "boleta de pago"
        verbose_name_plural = "boletas de pago (inventario físico)"
        indexes = [
            models.Index(fields=["employee", "period_start"], name="ix_pay_slip_emp_period"),
            models.Index(fields=["period_end", "cost_center"], name="ix_pay_slip_period_cc"),
        ]
        constraints = [
            # Firma y archivo solo de boletas impresas; impresa ⇔ al menos una impresión.
            models.CheckConstraint(condition=Q(signed_on__isnull=True) | Q(printed_at__isnull=False), name="ck_pay_slip_sign_printed"),
            models.CheckConstraint(condition=Q(archived_at__isnull=True) | Q(printed_at__isnull=False), name="ck_pay_slip_archive_printed"),
            models.CheckConstraint(condition=Q(printed_at__isnull=True) | Q(print_count__gte=1), name="ck_pay_slip_print_count"),
            models.CheckConstraint(condition=Q(net_pay=models.F("gross_pay") - models.F("total_deductions")), name="ck_pay_slip_net"),
        ]

    def __str__(self) -> str:
        return self.folio


# ============================================================== Fase 21: reglas por cuenta, pre-cierre y excepciones
class PayrollAccountRule(models.Model):
    """Reglas de planilla de una cuenta (cliente del roster): por ahora, si aplica la pérdida del séptimo día."""

    client = models.OneToOneField("operations.Client", on_delete=models.PROTECT, related_name="payroll_rule",
                                  verbose_name="cuenta (cliente)")
    seventh_day_penalty = models.BooleanField("pérdida del séptimo día", default=False)
    notes = models.CharField("observaciones", max_length=300, blank=True)
    is_active = models.BooleanField("activa", default=True)
    updated_at = models.DateTimeField("actualizada", auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        db_table = sql_table("fin", "pay_account_rule")
        verbose_name = "regla de planilla por cuenta"
        verbose_name_plural = "reglas de planilla por cuenta"

    def __str__(self) -> str:
        return f"Regla de planilla de la cuenta {self.client_id}"


class PayrollIteration(models.Model):
    """Cada corrida del motor antes del cierre (manual o diaria automática): totales para comparar la evolución."""

    class Trigger(models.TextChoices):
        MANUAL = "MANUAL", "Manual"
        SCHEDULED = "SCHEDULED", "Corrida diaria automática"

    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="iteration_log", verbose_name="planilla")
    number = models.PositiveIntegerField("corrida")
    trigger = models.CharField("origen", max_length=10, choices=Trigger, default=Trigger.MANUAL)
    calculated_at = models.DateTimeField("calculada")
    calculated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    employees = models.PositiveIntegerField(default=0)
    scheduled_seconds = models.BigIntegerField("horas programadas (s)", default=0)
    paid_seconds = models.BigIntegerField("horas pagadas (s)", default=0)
    gross = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    deductions = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    net = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    warnings = models.PositiveIntegerField(default=0)
    open_exceptions = models.PositiveIntegerField("excepciones abiertas", default=0)

    class Meta:
        db_table = sql_table("fin", "pay_payroll_iteration")
        ordering = ["run_id", "-number"]
        verbose_name = "corrida preliminar"
        verbose_name_plural = "corridas preliminares"
        constraints = [models.UniqueConstraint(fields=["run", "number"], name="uq_pay_iteration_number")]


class PayrollException(models.Model):
    """Excepción que el agente reporta sobre su boleta preliminar; la resuelve su supervisor o planillas antes del freeze."""

    class Category(models.TextChoices):
        HOURS = "HOURS", "Horas trabajadas no reflejadas"
        NIGHT = "NIGHT", "Nocturnidad"
        OVERTIME = "OVERTIME", "Horas extra"
        HOLIDAY = "HOLIDAY", "Feriado laborado"
        ABSENCE = "ABSENCE", "Ausencia / Lateness mal marcado"
        DEDUCTION = "DEDUCTION", "Descuentos"
        OTHER = "OTHER", "Otra"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Abierta"
        RESOLVED = "RESOLVED", "Resuelta"
        REJECTED = "REJECTED", "Rechazada"

    payroll = models.ForeignKey(Payroll, on_delete=models.DO_NOTHING, db_column="payroll_id", db_constraint=False,
                                related_name="exceptions", verbose_name="planilla")
    employee = _employee_fk("payroll_exceptions")
    work_date = models.DateField("fecha", null=True, blank=True)
    category = models.CharField("tipo", max_length=10, choices=Category, default=Category.HOURS)
    description = models.TextField("descripción", max_length=1000)
    status = models.CharField("estado", max_length=8, choices=Status, default=Status.OPEN)
    supervisor_code = models.CharField("supervisor (Team Manager)", max_length=40, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField("reportada", auto_now_add=True)
    response = models.CharField("respuesta", max_length=1000, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    resolved_at = models.DateTimeField("resuelta", null=True, blank=True)

    class Meta:
        db_table = sql_table("fin", "pay_payroll_exception")
        ordering = ["-created_at", "-id"]
        verbose_name = "excepción de planilla"
        verbose_name_plural = "excepciones de planilla (reportadas por los agentes)"
        indexes = [models.Index(fields=["payroll", "status"], name="ix_pay_exception_status"),
                   models.Index(fields=["supervisor_code", "status"], name="ix_pay_exception_sup")]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=["OPEN", "RESOLVED", "REJECTED"]), name="ck_pay_exception_status"),
            models.CheckConstraint(condition=Q(status="OPEN") | Q(resolved_at__isnull=False), name="ck_pay_exception_resolved"),
        ]


# ============================================================== Fase 21: liquidaciones e indemnizaciones
class SettlementBatch(models.Model):
    """Lote de pago de liquidaciones, separado de la planilla ordinaria (cheques o transferencias)."""

    class Method(models.TextChoices):
        CHECK = "CHECK", "Cheque"
        TRANSFER = "TRANSFER", "Transferencia bancaria"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Abierto"
        CLOSED = "CLOSED", "Cerrado (listo para pago)"
        PAID = "PAID", "Pagado"

    code = models.CharField("código", max_length=30, unique=True)
    country = _country_fk(related_name="+")
    payment_date = models.DateField("fecha de pago")
    method = models.CharField("forma de pago", max_length=8, choices=Method, default=Method.CHECK)
    bank_account = models.CharField("cuenta de la empresa", max_length=60, blank=True)
    status = models.CharField("estado", max_length=6, choices=Status, default=Status.OPEN)
    notes = models.CharField("observaciones", max_length=300, blank=True)
    created_at = models.DateTimeField("creado", auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    closed_at = models.DateTimeField("cerrado", null=True, blank=True)
    paid_at = models.DateTimeField("pagado", null=True, blank=True)

    class Meta:
        db_table = sql_table("fin", "pay_settlement_batch")
        ordering = ["-payment_date", "-id"]
        verbose_name = "lote de pago de liquidaciones"
        verbose_name_plural = "lotes de pago de liquidaciones"
        constraints = [
            models.CheckConstraint(condition=Q(status__in=["OPEN", "CLOSED", "PAID"]), name="ck_pay_settle_batch_status"),
            models.CheckConstraint(condition=Q(method__in=["CHECK", "TRANSFER"]), name="ck_pay_settle_batch_method"),
        ]

    def __str__(self) -> str:
        return self.code


class Settlement(models.Model):
    """Liquidación / indemnización de un colaborador terminado: se calcula, se aprueba (contenido sellado) y se paga en
    un lote propio, independiente de la planilla ordinaria."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Borrador"
        CALCULATED = "CALCULATED", "Calculada"
        APPROVED = "APPROVED", "Aprobada (sellada)"
        PAID = "PAID", "Pagada"
        CANCELLED = "CANCELLED", "Anulada"

    folio = models.CharField("folio", max_length=30, unique=True)
    employee = _employee_fk("settlements")
    termination_action = models.ForeignKey("personnel_actions.PersonnelAction", on_delete=models.PROTECT, null=True, blank=True,
                                           related_name="settlements", verbose_name="AP de terminación")
    reason = models.CharField("motivo de terminación", max_length=20)
    hire_date = models.DateField("ingreso")
    termination_date = models.DateField("terminación")
    base_salary = models.DecimalField("salario base mensual", max_digits=18, decimal_places=2)
    service_days = models.PositiveIntegerField("días de servicio (sin suspensiones)", default=0)
    currency = models.CharField("moneda", max_length=3, default="USD")
    status = models.CharField("estado", max_length=10, choices=Status, default=Status.DRAFT)
    gross = models.DecimalField("total devengado", max_digits=18, decimal_places=2, default=0)
    deductions = models.DecimalField("total descuentos", max_digits=18, decimal_places=2, default=0)
    net = models.DecimalField("líquido a pagar", max_digits=18, decimal_places=2, default=0)
    batch = models.ForeignKey(SettlementBatch, on_delete=models.PROTECT, null=True, blank=True, related_name="settlements",
                              verbose_name="lote de pago")
    check_number = models.CharField("número de cheque / referencia", max_length=30, blank=True)
    content = models.JSONField("contenido sellado", null=True, blank=True)
    content_hash = models.CharField("sello SHA-256", max_length=64, blank=True)
    notes = models.CharField("observaciones", max_length=500, blank=True)
    cancel_reason = models.CharField("motivo de anulación", max_length=500, blank=True)
    created_at = models.DateTimeField("creada", auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    calculated_at = models.DateTimeField("calculada", null=True, blank=True)
    calculated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    approved_at = models.DateTimeField("aprobada", null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    paid_at = models.DateTimeField("pagada", null=True, blank=True)

    class Meta:
        db_table = sql_table("fin", "pay_settlement")
        ordering = ["-created_at", "-id"]
        verbose_name = "liquidación"
        verbose_name_plural = "liquidaciones e indemnizaciones"
        constraints = [
            models.CheckConstraint(condition=Q(status__in=["DRAFT", "CALCULATED", "APPROVED", "PAID", "CANCELLED"]),
                                   name="ck_pay_settlement_status"),
            models.CheckConstraint(condition=Q(net=models.F("gross") - models.F("deductions")), name="ck_pay_settlement_net"),
            models.CheckConstraint(condition=Q(termination_date__gte=models.F("hire_date")), name="ck_pay_settlement_dates"),
            models.UniqueConstraint(fields=["employee", "termination_date"], condition=Q(status__in=["DRAFT", "CALCULATED", "APPROVED", "PAID"]),
                                    name="uq_pay_settlement_employee_date"),
            models.UniqueConstraint(fields=["batch", "check_number"], condition=Q(check_number__gt=""), name="uq_pay_settlement_check"),
        ]

    def __str__(self) -> str:
        return self.folio


class SettlementLine(models.Model):
    class Kind(models.TextChoices):
        EARNING = "EARNING", "Devengo"
        LEGAL = "LEGAL", "Retención de ley"
        DEDUCTION = "DEDUCTION", "Descuento"
        INFO = "INFO", "Información"

    settlement = models.ForeignKey(Settlement, on_delete=models.CASCADE, related_name="lines", verbose_name="liquidación")
    kind = models.CharField("tipo", max_length=9, choices=Kind)
    code = models.CharField("código", max_length=30)
    label = models.CharField("descripción", max_length=200)
    quantity = models.DecimalField("cantidad", max_digits=12, decimal_places=4, null=True, blank=True)
    unit = models.CharField("unidad", max_length=10, blank=True)
    rate = models.DecimalField("valor unitario / tasa", max_digits=18, decimal_places=6, null=True, blank=True)
    base = models.DecimalField("base", max_digits=18, decimal_places=2, null=True, blank=True)
    amount = models.DecimalField("monto", max_digits=18, decimal_places=2, default=0)
    affects_social_security = models.BooleanField("cotiza ISSS / AFP", default=False)
    affects_income_tax = models.BooleanField("gravado (Renta)", default=False)
    is_manual = models.BooleanField("ajuste manual", default=False)
    notes = models.CharField("detalle", max_length=300, blank=True)
    sort = models.PositiveSmallIntegerField("orden", default=100)

    class Meta:
        db_table = sql_table("fin", "pay_settlement_line")
        ordering = ["settlement_id", "sort", "id"]
        verbose_name = "línea de liquidación"
        verbose_name_plural = "líneas de liquidación"
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=["EARNING", "LEGAL", "DEDUCTION", "INFO"]), name="ck_pay_settle_line_kind"),
            models.CheckConstraint(condition=Q(amount__gte=0), name="ck_pay_settle_line_amount"),
        ]
