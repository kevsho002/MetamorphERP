"""Fase 25 — Boleta diaria en SQL Server (pasa al esquema `fin` en system.0015).

* FK reales a fin.Payroll, fin.PayrollDetail y hcm.Employee.
* TR_pay_payroll_day_rules: los días de una planilla cerrada o pagada no cambian (50099).
* vw_PayPayrollDay: cada fecha del corte con horas decimales y montos, lista para reportería.
"""

from django.db import migrations

FKS = [
    ("payroll_id", "fin.Payroll", "PayrollId"),
    ("payroll_detail_id", "fin.PayrollDetail", "PayrollDetailId"),
    ("employee_id", "hcm.Employee", "EmployeeId"),
]

FK_SQL = "".join(f"""
IF OBJECT_ID(N'dbo.FK_pay_payroll_day_{c}', N'F') IS NULL
    ALTER TABLE dbo.pay_payroll_day WITH CHECK ADD CONSTRAINT FK_pay_payroll_day_{c} FOREIGN KEY ({c}) REFERENCES {ref} ({col});
""" for c, ref, col in FKS)
FK_DROP = "".join(f"""
IF OBJECT_ID(N'dbo.FK_pay_payroll_day_{c}', N'F') IS NOT NULL ALTER TABLE dbo.pay_payroll_day DROP CONSTRAINT FK_pay_payroll_day_{c};
""" for c, _, _ in FKS)

TRIGGER = r"""
CREATE OR ALTER TRIGGER dbo.TR_pay_payroll_day_rules ON dbo.pay_payroll_day
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1 FROM (SELECT payroll_id FROM inserted UNION SELECT payroll_id FROM deleted) AS x
        JOIN fin.Payroll AS p ON p.PayrollId = x.payroll_id
        WHERE p.PayrollStatus IN (N'APPROVED', N'PAID')
    )
        THROW 50099, N'Planilla: una planilla cerrada o pagada no cambia (boleta diaria).', 1;
END
"""

VIEW = r"""
CREATE OR ALTER VIEW dbo.vw_PayPayrollDay
AS
SELECT d.id AS PayrollDayId, p.PayrollCode, p.PayrollStatus, p.PeriodStart, p.PeriodEnd, d.cutoff_code AS CutoffCode,
       e.EmployeeCode AS EmployeeId, CONCAT(e.FirstName, N' ', e.LastName) AS EmployeeName, d.work_date AS WorkDate,
       DATENAME(weekday, d.work_date) AS WeekdayName, d.day_type AS DayType, d.holiday_name AS HolidayName,
       CAST(d.scheduled_seconds / 3600.0 AS decimal(9, 2)) AS ScheduledHours,
       CAST(d.worked_seconds / 3600.0 AS decimal(9, 2)) AS WorkedHours,
       CAST(d.paid_seconds / 3600.0 AS decimal(9, 2)) AS PaidHours,
       CAST(d.night_seconds / 3600.0 AS decimal(9, 2)) AS NightHours,
       d.regular_amount AS RegularAmount, d.vacation_amount AS VacationAmount, d.night_amount AS NightAmount,
       d.holiday_amount AS HolidayAmount, d.discount_amount AS DiscountAmount, d.total_amount AS TotalAmount
FROM dbo.pay_payroll_day AS d
JOIN fin.Payroll AS p ON p.PayrollId = d.payroll_id
JOIN hcm.Employee AS e ON e.EmployeeId = d.employee_id;
"""


class Migration(migrations.Migration):
    dependencies = [("payroll", "0005_phase25_payroll_day")]

    operations = [
        migrations.RunSQL(FK_SQL, FK_DROP),
        migrations.RunSQL(TRIGGER, "DROP TRIGGER IF EXISTS dbo.TR_pay_payroll_day_rules;"),
        migrations.RunSQL(VIEW, "DROP VIEW IF EXISTS dbo.vw_PayPayrollDay;"),
    ]
