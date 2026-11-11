"""Esquema `fin`: Planillas y retenciones legales configurables (SQL-first, managed = False)."""

from django.db import models
from django.db.models import Value
from django.db.models.functions import Now

from apps.common.fields import AuditColumns, RowVersionField, sql_table
from apps.common.models import Country
from apps.hcm.models import Employee


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
