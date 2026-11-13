"""Fase 20: integridad en SQL Server, vistas de planilla / inventario de boletas y datos de referencia.

* FKs de las tablas dbo.pay_* a fin.Payroll, fin.PayrollDetail, fin.catDeductionType, hcm.Employee, core.catCostCenter
  y core.catCountry (SQL-first).
* TR_fin_payroll_locked (50090): una planilla CERRADA o PAGADA no cambia: ni su detalle, ni sus retenciones, ni las
  líneas de la boleta.
* TR_fin_payroll_status (50091): el estado de la planilla solo avanza (cerrada → pagada); una planilla cerrada no se
  borra ni cambia sus totales.
* TR_pay_payslip_rules (50092): las boletas solo se generan de una planilla cerrada, coinciden con su línea de
  planilla, no se eliminan y su contenido congelado (folio, montos, sello) no cambia; solo cambia el control físico.
* TR_pay_payroll_line_action (50093): una línea que paga / descuenta una AP exige una AP APROBADA del mismo empleado
  con efecto «Concepto de planilla».
* Vistas: vw_PayPayrollDetail (planilla por colaborador con ISSS, AFP, Renta y aportes) y vw_PayPayslipInventory
  (inventario físico de boletas por periodo, mes, departamento y estado).
* Referencia (El Salvador, a validar contra la normativa vigente): parámetros del Código de Trabajo, conceptos de la
  boleta, tipos de AP de pago (horas extra, bonificación, vacaciones, descuento), INSAFORP patronal y la tabla de
  Renta quincenal (la mensual dividida entre dos).
"""

from datetime import date
from decimal import Decimal

from django.db import migrations

_REQUIRE = """
IF OBJECT_ID(N'fin.PayrollDetail', N'U') IS NULL
    THROW 50010, N'Falta fin.PayrollDetail. Ejecute database/deploy.ps1 antes de migrate.', 1;
"""

# (tabla, columna, tabla referida, columna referida, ON DELETE)
_FKS = [
    ("pay_setting", "country_id", "core.catCountry", "CountryId", ""),
    ("pay_payroll_run", "payroll_id", "fin.Payroll", "PayrollId", ""),
    ("pay_payroll_line", "payroll_id", "fin.Payroll", "PayrollId", ""),
    ("pay_payroll_line", "payroll_detail_id", "fin.PayrollDetail", "PayrollDetailId", " ON DELETE CASCADE"),
    ("pay_payroll_line", "employee_id", "hcm.Employee", "EmployeeId", ""),
    ("pay_payroll_line", "deduction_type_id", "fin.catDeductionType", "DeductionTypeId", ""),
    ("pay_payslip_batch", "payroll_id", "fin.Payroll", "PayrollId", ""),
    ("pay_payslip_batch", "cost_center_id", "core.catCostCenter", "CostCenterId", ""),
    ("pay_payslip", "payroll_id", "fin.Payroll", "PayrollId", ""),
    ("pay_payslip", "payroll_detail_id", "fin.PayrollDetail", "PayrollDetailId", ""),
    ("pay_payslip", "employee_id", "hcm.Employee", "EmployeeId", ""),
    ("pay_payslip", "cost_center_id", "core.catCostCenter", "CostCenterId", ""),
]


def _fk_name(table, column):
    return f"FK_{table}_{column}"[:128]


def _fk_sql():
    out = []
    for table, column, ref, ref_col, on_delete in _FKS:
        name = _fk_name(table, column)
        out.append(f"""
IF OBJECT_ID(N'dbo.{name}', N'F') IS NULL
    ALTER TABLE dbo.{table} WITH CHECK ADD CONSTRAINT {name} FOREIGN KEY ({column}) REFERENCES {ref} ({ref_col}){on_delete};
""")
    return "".join(out)


def _fk_drop():
    return "".join(f"""
IF OBJECT_ID(N'dbo.{_fk_name(t, c)}', N'F') IS NOT NULL ALTER TABLE dbo.{t} DROP CONSTRAINT {_fk_name(t, c)};
""" for t, c, *_ in _FKS)


LOCK_DETAIL = """
CREATE OR ALTER TRIGGER fin.TR_fin_PayrollDetail_locked
ON fin.PayrollDetail
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1 FROM (SELECT PayrollId FROM inserted UNION SELECT PayrollId FROM deleted) AS x
        JOIN fin.Payroll AS p ON p.PayrollId = x.PayrollId
        WHERE p.PayrollStatus IN (N'APPROVED', N'PAID')
    )
        THROW 50090, N'Planilla: una planilla cerrada o pagada no cambia (detalle por colaborador).', 1;
END
"""

LOCK_DEDUCTION = """
CREATE OR ALTER TRIGGER fin.TR_fin_PayrollDeduction_locked
ON fin.PayrollDeduction
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1 FROM (SELECT PayrollDetailId FROM inserted UNION SELECT PayrollDetailId FROM deleted) AS x
        JOIN fin.PayrollDetail AS d ON d.PayrollDetailId = x.PayrollDetailId
        JOIN fin.Payroll AS p ON p.PayrollId = d.PayrollId
        WHERE p.PayrollStatus IN (N'APPROVED', N'PAID')
    )
        THROW 50090, N'Planilla: una planilla cerrada o pagada no cambia (retenciones).', 1;
END
"""

LOCK_LINE = """
CREATE OR ALTER TRIGGER dbo.TR_pay_payroll_line_rules
ON dbo.pay_payroll_line
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1 FROM (SELECT payroll_id FROM inserted UNION SELECT payroll_id FROM deleted) AS x
        JOIN fin.Payroll AS p ON p.PayrollId = x.payroll_id
        WHERE p.PayrollStatus IN (N'APPROVED', N'PAID')
    )
        THROW 50090, N'Planilla: una planilla cerrada o pagada no cambia (líneas de la boleta).', 1;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.pa_action AS a ON a.id = i.personnel_action_id
        JOIN dbo.pa_action_type AS t ON t.id = a.action_type_id
        WHERE a.status <> N'APPROVED' OR a.employee_id <> i.employee_id OR t.effect <> N'PAYROLL'
    )
        THROW 50093, N'Planilla: la AP pagada o descontada debe estar aprobada, ser del mismo empleado y ser un concepto de planilla.', 1;
END
"""

PAYROLL_STATUS = """
CREATE OR ALTER TRIGGER fin.TR_fin_Payroll_status
ON fin.Payroll
AFTER UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted WHERE PayrollStatus IN (N'APPROVED', N'PAID'))
        THROW 50091, N'Planilla: una planilla cerrada o pagada no se elimina.', 1;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN deleted AS d ON d.PayrollId = i.PayrollId
        WHERE (d.PayrollStatus = N'APPROVED' AND i.PayrollStatus NOT IN (N'APPROVED', N'PAID'))
           OR (d.PayrollStatus = N'PAID' AND i.PayrollStatus <> N'PAID')
           OR (d.PayrollStatus IN (N'APPROVED', N'PAID')
               AND (i.TotalGross <> d.TotalGross OR i.TotalDeductions <> d.TotalDeductions OR i.TotalNet <> d.TotalNet
                    OR i.TotalEmployerCost <> d.TotalEmployerCost OR i.PeriodStart <> d.PeriodStart OR i.PeriodEnd <> d.PeriodEnd))
    )
        THROW 50091, N'Planilla: el estado solo avanza (cerrada → pagada) y una planilla cerrada no cambia sus totales.', 1;
END
"""

PAYSLIP_RULES = """
CREATE OR ALTER TRIGGER dbo.TR_pay_payslip_rules
ON dbo.pay_payslip
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted)
        THROW 50092, N'Boletas: una boleta generada no se elimina.', 1;
    IF NOT EXISTS (SELECT 1 FROM deleted) AND EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN fin.Payroll AS p ON p.PayrollId = i.payroll_id
        LEFT JOIN fin.PayrollDetail AS d ON d.PayrollDetailId = i.payroll_detail_id
        WHERE p.PayrollStatus NOT IN (N'APPROVED', N'PAID')
           OR d.PayrollDetailId IS NULL OR d.PayrollId <> i.payroll_id OR d.EmployeeId <> i.employee_id
           OR d.NetPay <> i.net_pay OR d.GrossPay <> i.gross_pay OR d.TotalDeductions <> i.total_deductions
    )
        THROW 50092, N'Boletas: solo se generan de una planilla cerrada y deben coincidir con su línea de planilla.', 1;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN deleted AS d ON d.id = i.id
        WHERE i.folio <> d.folio OR i.payroll_id <> d.payroll_id OR i.payroll_detail_id <> d.payroll_detail_id
           OR i.employee_id <> d.employee_id OR i.net_pay <> d.net_pay OR i.gross_pay <> d.gross_pay
           OR i.total_deductions <> d.total_deductions OR i.content_hash <> d.content_hash OR i.content <> d.content
           OR i.period_start <> d.period_start OR i.period_end <> d.period_end OR i.generated_at <> d.generated_at
    )
        THROW 50092, N'Boletas: el contenido de una boleta generada no cambia; solo su control físico (impresión, firma y archivo).', 1;
END
"""

DETAIL_VIEW = """
CREATE OR ALTER VIEW dbo.vw_PayPayrollDetail
AS
SELECT
    p.PayrollId, p.PayrollCode, p.PayrollStatus, p.PayFrequency, p.PeriodStart, p.PeriodEnd, p.PaymentDate, p.CurrencyCode,
    e.EmployeeCode      AS EmployeeId,
    CONCAT_WS(N' ', e.FirstName, e.MiddleName, e.LastName, e.SecondLastName) AS EmployeeName,
    cc.Code             AS CostCenter,
    cc.Name             AS Department,
    d.BaseSalary, d.PaidDays, d.WorkedMinutes, d.OvertimeAmount, d.OtherEarnings, d.GrossPay, d.TaxableBase,
    ISNULL(x.Isss, 0)   AS IsssEmployee,
    ISNULL(x.Afp, 0)    AS AfpEmployee,
    ISNULL(x.Renta, 0)  AS IncomeTax,
    d.TotalDeductions, d.NetPay, d.EmployerContributions,
    s.folio             AS PayslipFolio
FROM fin.PayrollDetail AS d
JOIN fin.Payroll AS p ON p.PayrollId = d.PayrollId
JOIN hcm.Employee AS e ON e.EmployeeId = d.EmployeeId
LEFT JOIN core.catCostCenter AS cc ON cc.CostCenterId = e.CostCenterId
LEFT JOIN dbo.pay_payslip AS s ON s.payroll_detail_id = d.PayrollDetailId
OUTER APPLY (
    SELECT
        SUM(CASE WHEN t.Category = N'SOCIAL_SECURITY' AND pd.Party = N'EMPLOYEE' THEN pd.Amount END) AS Isss,
        SUM(CASE WHEN t.Category = N'PENSION' AND pd.Party = N'EMPLOYEE' THEN pd.Amount END) AS Afp,
        SUM(CASE WHEN t.Category = N'INCOME_TAX' THEN pd.Amount END) AS Renta
    FROM fin.PayrollDeduction AS pd
    JOIN fin.catDeductionType AS t ON t.DeductionTypeId = pd.DeductionTypeId
    WHERE pd.PayrollDetailId = d.PayrollDetailId
) AS x;
"""

INVENTORY_VIEW = """
CREATE OR ALTER VIEW dbo.vw_PayPayslipInventory
AS
SELECT
    s.id                AS PayslipId,
    s.folio             AS Folio,
    p.PayrollCode,
    b.code              AS BatchCode,
    b.archive_location  AS BatchArchiveLocation,
    e.EmployeeCode      AS EmployeeId,
    CONCAT_WS(N' ', e.FirstName, e.MiddleName, e.LastName, e.SecondLastName) AS EmployeeName,
    cc.Code             AS CostCenter,
    cc.Name             AS Department,
    s.pay_frequency     AS PayFrequency,
    s.period_start      AS PeriodStart,
    s.period_end        AS PeriodEnd,
    YEAR(s.period_end)  AS PeriodYear,
    MONTH(s.period_end) AS PeriodMonth,
    s.payment_date      AS PaymentDate,
    s.net_pay           AS NetPay,
    CAST(CASE WHEN s.printed_at IS NULL THEN 0 ELSE 1 END AS BIT) AS IsPrinted,
    CASE WHEN s.printed_at IS NULL THEN N'Faltante por imprimir' ELSE N'Impresa' END AS PrintStatus,
    s.print_count       AS PrintCount,
    s.printed_at        AS PrintedAtUtc,
    CAST(CASE WHEN s.signed_on IS NULL THEN 0 ELSE 1 END AS BIT) AS IsSigned,
    CASE WHEN s.signed_on IS NULL THEN N'Pendiente de firma' ELSE N'Firmada en físico' END AS SignatureStatus,
    s.signed_on         AS SignedOn,
    CAST(CASE WHEN s.archived_at IS NULL THEN 0 ELSE 1 END AS BIT) AS IsArchived,
    s.archived_at       AS ArchivedAtUtc,
    s.archive_location  AS ArchiveLocation,
    s.generated_at      AS GeneratedAtUtc,
    s.content_hash      AS ContentHash
FROM dbo.pay_payslip AS s
JOIN fin.Payroll AS p ON p.PayrollId = s.payroll_id
JOIN dbo.pay_payslip_batch AS b ON b.id = s.batch_id
JOIN hcm.Employee AS e ON e.EmployeeId = s.employee_id
LEFT JOIN core.catCostCenter AS cc ON cc.CostCenterId = s.cost_center_id;
"""

# --------------------------------------------------------------------------------------------------- referencia
SV_SETTING = {
    "name": "El Salvador — Código de Trabajo", "effective_start_date": date(2026, 1, 1), "days_per_month": 30,
    "hours_per_day": Decimal(8), "overtime_surcharge_percent": Decimal(100), "vacation_premium_percent": Decimal(30),
    "legal_reference": "Código de Trabajo: salario diario = mensual / 30; horas extra con 100 % de recargo (art. 169); "
                       "nocturnidad según la regla del país (art. 168); 15 días de vacaciones con 30 % de prima (art. 177); "
                       "pérdida del día de descanso por inasistencia injustificada en la semana (art. 174).",
}

# code, name, kind, source, calculation, AP type, AP field, ISSS/AFP, Renta, order, description
CONCEPTS = [
    ("SALARIO", "Salario ordinario del periodo", "EARNING", "SALARY", "ENGINE", "", "", True, True, 10,
     "Salario base mensual del expediente proporcional al periodo (días contratados)."),
    ("AUSENCIA", "Unjustified Absence", "TIME_DISCOUNT", "ADHERENCE", "ENGINE", "", "", True, True, 20,
     "Un día de salario por cada contenedor marcado como ausencia injustificada (Fase 19)."),
    ("SEPTIMO_DIA", "Pérdida del séptimo día", "TIME_DISCOUNT", "ADHERENCE", "ENGINE", "", "", True, True, 21,
     "Día de descanso no remunerado por semana con ausencia injustificada."),
    ("LATENESS", "Lateness", "TIME_DISCOUNT", "ADHERENCE", "ENGINE", "", "", True, True, 22,
     "Tiempo del segmento Lateness no reemplazado con AP, por hora ordinaria."),
    ("PERMISO_SIN_GOCE", "Permisos sin goce de sueldo", "TIME_DISCOUNT", "ADHERENCE", "ENGINE", "", "", True, True, 23,
     "Segmentos programados de actividades no pagadas (HR Confidential Unpaid y similares)."),
    ("TIEMPO_NO_LABORADO", "Tiempo no laborado (Out of Adherence)", "TIME_DISCOUNT", "ADHERENCE", "ENGINE", "", "", True, True, 24,
     "Programado pagado que la adherencia guardada no validó para pago."),
    ("NOCTURNIDAD", "Recargo nocturno", "EARNING", "WEB_TIMER", "ENGINE", "", "", True, True, 30,
     "Minutos nocturnos del Web Timer × % de la regla de nocturnidad × hora ordinaria."),
    ("HORAS_EXTRA_DIURNAS", "Horas extra diurnas", "EARNING", "AP", "OVERTIME_DAY", "AP_HORAS_EXTRA", "horas_diurnas", True, True, 40, ""),
    ("HORAS_EXTRA_NOCTURNAS", "Horas extra nocturnas", "EARNING", "AP", "OVERTIME_NIGHT", "AP_HORAS_EXTRA", "horas_nocturnas", True, True, 41, ""),
    ("BONIFICACION", "Bonificación / comisión", "EARNING", "AP", "AMOUNT", "AP_BONIFICACION", "monto", True, True, 50, ""),
    ("PRIMA_VACACIONES", "Prima de vacaciones", "EARNING", "AP", "VACATION", "AP_VACACIONES", "dias", True, True, 60, ""),
    ("DESCUENTO_AP", "Descuento autorizado por AP", "DEDUCTION", "AP", "AMOUNT", "AP_DESCUENTO", "monto", False, False, 700,
     "Préstamos, anticipos, embargos o cuotas autorizadas; se aplican después de las retenciones de ley."),
]

AP_TYPES = [
    {
        "code": "AP_HORAS_EXTRA", "name": "Horas extra autorizadas", "category": "COMPENSATION", "effect": "PAYROLL",
        "folio_prefix": "APHE", "creator_signs_first_step": True, "display_order": 40,
        "description": "Horas extra trabajadas en la fecha efectiva; sin esta AP el exceso de login no se paga (Unpaid Excess Login).",
        "attributes": [
            {"key": "motivo", "label": "Motivo", "data_type": "CHOICE", "required": True, "display_order": 10,
             "choices": ["Volumen de contactos", "Cobertura de ausencias", "Proyecto / campaña", "Capacitación", "Otro"]},
            {"key": "horas_diurnas", "label": "Horas extra diurnas", "data_type": "DECIMAL", "required": False, "display_order": 20,
             "min_value": "0", "max_value": "24", "help_text": "Horas (con decimales) fuera de la jornada, en horario diurno."},
            {"key": "horas_nocturnas", "label": "Horas extra nocturnas", "data_type": "DECIMAL", "required": False, "display_order": 30,
             "min_value": "0", "max_value": "24", "help_text": "Horas en la franja nocturna del país (llevan además el recargo nocturno)."},
        ],
        "steps": [(1, "Visto bueno de Workforce (WFM)", "WFM"), (2, "Autorización de Recursos Humanos", "HR")],
    },
    {
        "code": "AP_BONIFICACION", "name": "Bonificación / comisión", "category": "COMPENSATION", "effect": "PAYROLL",
        "folio_prefix": "APBO", "creator_signs_first_step": True, "display_order": 41,
        "view_permission": "payroll.view", "create_permission": "payroll.manage",
        "description": "Monto que se suma al devengado de la planilla del periodo (cotiza y es gravado).",
        "attributes": [
            {"key": "concepto", "label": "Concepto", "data_type": "CHOICE", "required": True, "display_order": 10,
             "choices": ["Bono por desempeño", "Comisión", "Incentivo de campaña", "Otro"]},
            {"key": "monto", "label": "Monto", "data_type": "DECIMAL", "required": True, "display_order": 20, "min_value": "0.01"},
        ],
        "steps": [(1, "Autorización de Recursos Humanos", "HR"), (2, "Aprobación de Administración / Gerencia", "ADMIN")],
    },
    {
        "code": "AP_VACACIONES", "name": "Vacaciones anuales (prima)", "category": "STATUS", "effect": "PAYROLL",
        "folio_prefix": "APVA", "creator_signs_first_step": True, "display_order": 42,
        "description": "Goce de vacaciones desde la fecha efectiva: la planilla paga la prima sobre el salario de los días.",
        "attributes": [
            {"key": "dias", "label": "Días de vacaciones", "data_type": "DECIMAL", "required": True, "display_order": 10,
             "min_value": "1", "max_value": "30", "help_text": "Código de Trabajo: 15 días por año de servicio."},
        ],
        "steps": [(1, "Autorización de Recursos Humanos", "HR")],
    },
    {
        "code": "AP_DESCUENTO", "name": "Descuento autorizado en planilla", "category": "COMPENSATION", "effect": "PAYROLL",
        "folio_prefix": "APDE", "creator_signs_first_step": True, "display_order": 43,
        "view_permission": "payroll.view", "create_permission": "payroll.manage",
        "description": "Descuento después de las retenciones de ley; nunca deja el líquido en negativo.",
        "attributes": [
            {"key": "concepto", "label": "Concepto", "data_type": "CHOICE", "required": True, "display_order": 10,
             "choices": ["Préstamo", "Anticipo de salario", "Embargo judicial", "Cuota sindical", "Otro autorizado por el colaborador"]},
            {"key": "monto", "label": "Monto a descontar", "data_type": "DECIMAL", "required": True, "display_order": 20, "min_value": "0.01"},
        ],
        "steps": [(1, "Autorización de Recursos Humanos", "HR"), (2, "Aprobación de Administración / Gerencia", "ADMIN")],
    },
]

# Renta quincenal de referencia (la tabla mensual sembrada en 090 dividida entre dos).
ISR_BIWEEKLY = [(Decimal("0.00"), Decimal("275.00"), Decimal("0"), Decimal("0.00"), Decimal("0.00")),
                (Decimal("275.01"), Decimal("447.62"), Decimal("0.10"), Decimal("8.83"), Decimal("275.00")),
                (Decimal("447.63"), Decimal("1019.05"), Decimal("0.20"), Decimal("30.00"), Decimal("447.62")),
                (Decimal("1019.06"), None, Decimal("0.30"), Decimal("144.28"), Decimal("1019.05"))]


def seed(apps, schema_editor):
    Country = apps.get_model("common", "Country")
    Setting = apps.get_model("payroll", "PayrollSetting")
    Concept = apps.get_model("payroll", "PayConcept")
    # fin.* es SQL-first (managed = False): el estado histórico no conserva sus FKs, se usan los modelos reales.
    from apps.payroll.models import DeductionBracket as Bracket, DeductionType

    ActionType = apps.get_model("personnel_actions", "ActionType")
    Attribute = apps.get_model("personnel_actions", "ActionAttribute")
    Step = apps.get_model("personnel_actions", "ApprovalStep")

    sv = Country.objects.filter(country_code="SV").first()
    if sv and not Setting.objects.filter(country_id=sv.pk).exists():
        Setting.objects.create(country_id=sv.pk, **SV_SETTING)
    for code, name, kind, source, calc, ap, key, ss, tax, order, desc in CONCEPTS:
        Concept.objects.get_or_create(code=code, defaults={
            "name": name, "kind": kind, "source": source, "calculation": calc, "action_type_code": ap, "action_attribute_key": key,
            "affects_social_security": ss, "affects_income_tax": tax, "display_order": order, "description": desc})
    for spec in AP_TYPES:
        spec = dict(spec)
        attributes, steps = spec.pop("attributes"), spec.pop("steps")
        if ActionType.objects.filter(code=spec["code"]).exists():
            continue
        t = ActionType.objects.create(**spec)
        for a in attributes:
            Attribute.objects.create(action_type=t, **a)
        for order, label, role in steps:
            Step.objects.create(action_type=t, order=order, label=label, role=role)
    if sv:
        if not DeductionType.objects.filter(country_id=sv.pk, code="INSAFORP_PAT").exists():
            DeductionType.objects.create(
                country_id=sv.pk, code="INSAFORP_PAT", name="INSAFORP aporte patronal", category="OTHER", party="EMPLOYER",
                calculation_method="PERCENTAGE", rate=Decimal("0.01"), reduces_taxable_base=False, calculation_order=30,
                effective_start_date=date(2026, 1, 1), is_active=True,
                legal_reference="Ley de Formación Profesional: 1 % patronal (empleadores con 10 o más trabajadores).")
        isr = DeductionType.objects.filter(country_id=sv.pk, code="ISR_SV").order_by("-effective_start_date").first()
        if isr and not Bracket.objects.filter(deduction_type_id=isr.pk, pay_frequency="BIWEEKLY").exists():
            for lower, upper, rate, fee, excess in ISR_BIWEEKLY:
                Bracket.objects.create(deduction_type_id=isr.pk, pay_frequency="BIWEEKLY", lower_bound=lower, upper_bound=upper,
                                       rate=rate, fixed_fee=fee, excess_over=excess)


def unseed(apps, schema_editor):
    Setting = apps.get_model("payroll", "PayrollSetting")
    Concept = apps.get_model("payroll", "PayConcept")
    ActionType = apps.get_model("personnel_actions", "ActionType")
    Action = apps.get_model("personnel_actions", "PersonnelAction")
    from apps.payroll.models import DeductionBracket as Bracket, DeductionType

    Setting.objects.filter(runs__isnull=True, name=SV_SETTING["name"]).delete()
    Concept.objects.filter(code__in=[c[0] for c in CONCEPTS]).delete()
    for spec in AP_TYPES:
        if not Action.objects.filter(action_type__code=spec["code"]).exists():
            ActionType.objects.filter(code=spec["code"]).delete()
    Bracket.objects.filter(deduction_type__code="ISR_SV", pay_frequency="BIWEEKLY", deduction_type__effective_start_date=date(2026, 1, 1)).delete()
    DeductionType.objects.filter(code="INSAFORP_PAT").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0001_initial"),
        ("personnel_actions", "0006_alter_actiontype_effect"),
    ]

    operations = [
        migrations.RunSQL(_REQUIRE + _fk_sql(), _fk_drop()),
        migrations.RunSQL(LOCK_DETAIL, "DROP TRIGGER IF EXISTS fin.TR_fin_PayrollDetail_locked;"),
        migrations.RunSQL(LOCK_DEDUCTION, "DROP TRIGGER IF EXISTS fin.TR_fin_PayrollDeduction_locked;"),
        migrations.RunSQL(LOCK_LINE, "DROP TRIGGER IF EXISTS dbo.TR_pay_payroll_line_rules;"),
        migrations.RunSQL(PAYROLL_STATUS, "DROP TRIGGER IF EXISTS fin.TR_fin_Payroll_status;"),
        migrations.RunSQL(PAYSLIP_RULES, "DROP TRIGGER IF EXISTS dbo.TR_pay_payslip_rules;"),
        migrations.RunSQL(DETAIL_VIEW, "DROP VIEW IF EXISTS dbo.vw_PayPayrollDetail;"),
        migrations.RunSQL(INVENTORY_VIEW, "DROP VIEW IF EXISTS dbo.vw_PayPayslipInventory;"),
        migrations.RunPython(seed, unseed),
    ]
