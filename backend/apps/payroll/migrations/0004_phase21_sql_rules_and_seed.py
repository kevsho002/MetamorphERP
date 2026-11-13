"""Fase 21: integridad en SQL Server del motor por horas, las excepciones y las liquidaciones; datos de referencia.

* FKs de las nuevas tablas dbo.pay_* a fin.Payroll, hcm.Employee y core.catCountry (SQL-first).
* TR_pay_settlement_rules (50095): una liquidación APROBADA o PAGADA no cambia sus montos, fechas, empleado ni su sello,
  el estado solo avanza (borrador → calculada → aprobada → pagada; anulada solo desde borrador / calculada) y no se
  elimina; sus líneas tampoco cambian.
* TR_pay_settlement_batch_rules (50096): un lote de pago solo contiene liquidaciones aprobadas o pagadas; un lote pagado
  no cambia ni pierde liquidaciones.
* Vista dbo.vw_PaySettlement: liquidaciones con su lote, cheque y totales.
* Conceptos del motor por horas: «Salario por horas laboradas», «Vacaciones (horas pagadas)» y «Feriado laborado»; se
  desactivan los descuentos por días de la Fase 20 (las horas no laboradas simplemente no se pagan). El séptimo día pasa
  a ser opcional (apagado por defecto; cada cuenta lo puede activar).
"""

from django.db import migrations

_FKS = [
    ("pay_payroll_exception", "payroll_id", "fin.Payroll", "PayrollId"),
    ("pay_payroll_exception", "employee_id", "hcm.Employee", "EmployeeId"),
    ("pay_settlement", "employee_id", "hcm.Employee", "EmployeeId"),
    ("pay_settlement_batch", "country_id", "core.catCountry", "CountryId"),
]


def _fk_sql():
    return "".join(f"""
IF OBJECT_ID(N'dbo.FK_{t}_{c}', N'F') IS NULL
    ALTER TABLE dbo.{t} WITH CHECK ADD CONSTRAINT FK_{t}_{c} FOREIGN KEY ({c}) REFERENCES {r} ({rc});
""" for t, c, r, rc in _FKS)


def _fk_drop():
    return "".join(f"""
IF OBJECT_ID(N'dbo.FK_{t}_{c}', N'F') IS NOT NULL ALTER TABLE dbo.{t} DROP CONSTRAINT FK_{t}_{c};
""" for t, c, *_ in _FKS)


SETTLEMENT_RULES = """
CREATE OR ALTER TRIGGER dbo.TR_pay_settlement_rules
ON dbo.pay_settlement
AFTER UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted WHERE status IN (N'APPROVED', N'PAID'))
        THROW 50095, N'Liquidación: una liquidación aprobada o pagada no se elimina.', 1;
    IF EXISTS (
        SELECT 1 FROM inserted i JOIN deleted d ON d.id = i.id
        WHERE d.status IN (N'APPROVED', N'PAID')
          AND (i.gross <> d.gross OR i.deductions <> d.deductions OR i.net <> d.net OR i.employee_id <> d.employee_id
               OR i.termination_date <> d.termination_date OR i.hire_date <> d.hire_date OR i.content_hash <> d.content_hash
               OR i.base_salary <> d.base_salary)
    )
        THROW 50095, N'Liquidación: el contenido de una liquidación aprobada (montos, fechas, sello) no cambia.', 1;
    IF EXISTS (
        SELECT 1 FROM inserted i JOIN deleted d ON d.id = i.id
        WHERE i.status <> d.status AND NOT (
               (d.status = N'DRAFT' AND i.status IN (N'CALCULATED', N'CANCELLED'))
            OR (d.status = N'CALCULATED' AND i.status IN (N'APPROVED', N'CANCELLED', N'DRAFT'))
            OR (d.status = N'APPROVED' AND i.status = N'PAID'))
    )
        THROW 50095, N'Liquidación: el estado solo avanza (borrador → calculada → aprobada → pagada).', 1;
    IF EXISTS (SELECT 1 FROM inserted WHERE batch_id IS NOT NULL AND status NOT IN (N'APPROVED', N'PAID'))
        THROW 50096, N'Lote de liquidaciones: solo admite liquidaciones aprobadas o pagadas.', 1;
    IF EXISTS (
        SELECT 1 FROM inserted i JOIN deleted d ON d.id = i.id
        JOIN dbo.pay_settlement_batch b ON b.id = d.batch_id
        WHERE b.status = N'PAID' AND (ISNULL(i.batch_id, -1) <> d.batch_id OR i.check_number <> d.check_number)
    )
        THROW 50096, N'Lote de liquidaciones: un lote pagado no pierde liquidaciones ni cambia sus cheques.', 1;
END;
"""

SETTLEMENT_LINES = """
CREATE OR ALTER TRIGGER dbo.TR_pay_settlement_line_locked
ON dbo.pay_settlement_line
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1 FROM (SELECT settlement_id FROM inserted UNION SELECT settlement_id FROM deleted) x
        JOIN dbo.pay_settlement s ON s.id = x.settlement_id
        WHERE s.status IN (N'APPROVED', N'PAID')
    )
        THROW 50095, N'Liquidación: las líneas de una liquidación aprobada o pagada no cambian.', 1;
END;
"""

BATCH_RULES = """
CREATE OR ALTER TRIGGER dbo.TR_pay_settlement_batch_rules
ON dbo.pay_settlement_batch
AFTER UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (SELECT 1 FROM deleted d LEFT JOIN inserted i ON i.id = d.id WHERE d.status = N'PAID'
               AND (i.id IS NULL OR i.status <> N'PAID' OR i.payment_date <> d.payment_date OR i.method <> d.method))
        THROW 50096, N'Lote de liquidaciones: un lote pagado no cambia ni se elimina.', 1;
    IF EXISTS (SELECT 1 FROM inserted i JOIN deleted d ON d.id = i.id
               WHERE i.status <> d.status AND NOT ((d.status = N'OPEN' AND i.status = N'CLOSED')
                                                 OR (d.status = N'CLOSED' AND i.status IN (N'OPEN', N'PAID'))))
        THROW 50096, N'Lote de liquidaciones: el estado sigue abierto → cerrado → pagado.', 1;
END;
"""

SETTLEMENT_VIEW = """
CREATE OR ALTER VIEW dbo.vw_PaySettlement
AS
SELECT s.id AS SettlementId, s.folio AS Folio, e.EmployeeCode, e.FirstName, e.LastName, s.reason AS TerminationReason,
       s.hire_date AS HireDate, s.termination_date AS TerminationDate, s.base_salary AS BaseSalary, s.service_days AS ServiceDays,
       s.status AS Status, s.gross AS Gross, s.deductions AS Deductions, s.net AS Net, s.currency AS Currency,
       b.code AS BatchCode, b.method AS PaymentMethod, b.payment_date AS PaymentDate, b.status AS BatchStatus,
       s.check_number AS CheckNumber, s.approved_at AS ApprovedAt, s.paid_at AS PaidAt, s.content_hash AS ContentHash
FROM dbo.pay_settlement s
JOIN hcm.Employee e ON e.EmployeeId = s.employee_id
LEFT JOIN dbo.pay_settlement_batch b ON b.id = s.batch_id;
"""

NEW_CONCEPTS = [
    ("VACACIONES_GOCE", "Vacaciones (horas programadas pagadas)", "EARNING", "SALARY", 12,
     "Días de vacaciones de la AP: se pagan las horas programadas como tiempo laborado."),
    ("FERIADO", "Feriado laborado (recargo)", "EARNING", "WEB_TIMER", 35,
     "Holiday Segment: horas laboradas en un feriado; salario regular + el recargo del feriado (pago doble)."),
]
RETIRED = ["AUSENCIA", "LATENESS", "PERMISO_SIN_GOCE", "TIEMPO_NO_LABORADO"]
AGUINALDO = [{"min_years": 0, "days": 15}, {"min_years": 3, "days": 19}, {"min_years": 10, "days": 21}]


def seed(apps, schema_editor):
    Concept = apps.get_model("payroll", "PayConcept")
    Setting = apps.get_model("payroll", "PayrollSetting")
    Concept.objects.filter(code="SALARIO").update(
        name="Salario por horas laboradas",
        description="Rate por hora (salario del periodo ÷ horas programadas del corte) × horas pagables validadas.")
    Concept.objects.filter(code="SEPTIMO_DIA").update(description="Opcional por cuenta: horas de un día por semana con Unjustified Absence.")
    Concept.objects.filter(code__in=RETIRED).update(is_active=False)
    for code, name, kind, source, order, desc in NEW_CONCEPTS:
        Concept.objects.get_or_create(code=code, defaults={"name": name, "kind": kind, "source": source, "calculation": "ENGINE",
                                                           "display_order": order, "description": desc})
    for s in Setting.objects.all():
        if not s.aguinaldo_tiers:
            s.aguinaldo_tiers = AGUINALDO
        if not s.runs.filter(payroll__payroll_status__in=["APPROVED", "PAID"]).exists():
            s.seventh_day_penalty = False  # Fase 21: opcional; cada cuenta lo activa
        s.save()


def unseed(apps, schema_editor):
    Concept = apps.get_model("payroll", "PayConcept")
    Concept.objects.filter(code__in=RETIRED).update(is_active=True)
    Concept.objects.filter(code__in=[c[0] for c in NEW_CONCEPTS]).delete()


class Migration(migrations.Migration):
    dependencies = [("payroll", "0003_phase21_hours_engine_settlements")]

    operations = [
        migrations.RunSQL(_fk_sql(), _fk_drop()),
        migrations.RunSQL(SETTLEMENT_RULES, "DROP TRIGGER IF EXISTS dbo.TR_pay_settlement_rules;"),
        migrations.RunSQL(SETTLEMENT_LINES, "DROP TRIGGER IF EXISTS dbo.TR_pay_settlement_line_locked;"),
        migrations.RunSQL(BATCH_RULES, "DROP TRIGGER IF EXISTS dbo.TR_pay_settlement_batch_rules;"),
        migrations.RunSQL(SETTLEMENT_VIEW, "DROP VIEW IF EXISTS dbo.vw_PaySettlement;"),
        migrations.RunPython(seed, unseed),
    ]
