"""Fase 21: integridad del calendario de feriados en SQL Server y feriados legales de El Salvador.

* FKs de hol_holiday a core.catCountry y de hol_holiday_segment a hcm.Employee (SQL-first).
* TR_hol_holiday_locked (50097): un feriado que ya generó Holiday Segments no cambia de país ni de fecha y no se elimina.
* Vista dbo.vw_HolidaySegment: feriados laborados por colaborador (horas programadas, laboradas, nocturnas y recargo).
* Feriados nacionales de El Salvador 2026 y 2027 (Código de Trabajo, art. 190, con el Día del Padre del Decreto 399 de
  2016): 1 de enero, jueves / viernes / sábado santo, 1 y 10 de mayo, 17 de junio, 6 de agosto, 15 de septiembre, 2 de
  noviembre y 25 de diciembre. Las fiestas patronales locales (p. ej. 3–5 de agosto en San Salvador) se agregan desde
  la pantalla del calendario.
"""

from datetime import date

from django.db import migrations

FKS = """
IF OBJECT_ID(N'dbo.FK_hol_holiday_country', N'F') IS NULL
    ALTER TABLE dbo.hol_holiday WITH CHECK ADD CONSTRAINT FK_hol_holiday_country FOREIGN KEY (country_id) REFERENCES core.catCountry (CountryId);
IF OBJECT_ID(N'dbo.FK_hol_holiday_segment_employee', N'F') IS NULL
    ALTER TABLE dbo.hol_holiday_segment WITH CHECK ADD CONSTRAINT FK_hol_holiday_segment_employee
        FOREIGN KEY (employee_id) REFERENCES hcm.Employee (EmployeeId);
"""
FKS_DROP = """
IF OBJECT_ID(N'dbo.FK_hol_holiday_country', N'F') IS NOT NULL ALTER TABLE dbo.hol_holiday DROP CONSTRAINT FK_hol_holiday_country;
IF OBJECT_ID(N'dbo.FK_hol_holiday_segment_employee', N'F') IS NOT NULL
    ALTER TABLE dbo.hol_holiday_segment DROP CONSTRAINT FK_hol_holiday_segment_employee;
"""

LOCKED = """
CREATE OR ALTER TRIGGER dbo.TR_hol_holiday_locked
ON dbo.hol_holiday
AFTER UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1 FROM deleted d
        LEFT JOIN inserted i ON i.id = d.id
        WHERE EXISTS (SELECT 1 FROM dbo.hol_holiday_segment s WHERE s.holiday_id = d.id)
          AND (i.id IS NULL OR i.date <> d.date OR i.country_id <> d.country_id)
    )
        THROW 50097, N'El feriado ya generó Holiday Segments: no cambia de país ni de fecha y no se elimina (desactívelo).', 1;
END;
"""

VIEW = """
CREATE OR ALTER VIEW dbo.vw_HolidaySegment
AS
SELECT s.id AS HolidaySegmentId, h.date AS HolidayDate, h.name AS HolidayName, h.kind AS HolidayKind, c.CountryCode,
       e.EmployeeCode, e.FirstName, e.LastName, s.start_at AS ContainerStart, s.end_at AS ContainerEnd,
       CAST(s.scheduled_seconds / 3600.0 AS decimal(9, 2)) AS ScheduledHours,
       CAST(s.worked_seconds / 3600.0 AS decimal(9, 2)) AS WorkedHours,
       CAST(s.night_seconds / 3600.0 AS decimal(9, 2)) AS NightHours,
       s.premium_percent AS PremiumPercent, s.updated_at AS UpdatedAt
FROM dbo.hol_holiday_segment s
JOIN dbo.hol_holiday h ON h.id = s.holiday_id
JOIN core.catCountry c ON c.CountryId = h.country_id
JOIN hcm.Employee e ON e.EmployeeId = s.employee_id;
"""

REF = "Código de Trabajo de El Salvador, art. 190"
SV_HOLIDAYS = [
    (date(2026, 1, 1), "Año Nuevo", REF), (date(2026, 4, 2), "Jueves Santo", REF), (date(2026, 4, 3), "Viernes Santo", REF),
    (date(2026, 4, 4), "Sábado Santo", REF), (date(2026, 5, 1), "Día del Trabajo", REF), (date(2026, 5, 10), "Día de la Madre", REF),
    (date(2026, 6, 17), "Día del Padre", "Decreto Legislativo 399 (2016)"), (date(2026, 8, 6), "Fiestas Agostinas (Divino Salvador del Mundo)", REF),
    (date(2026, 9, 15), "Día de la Independencia", REF), (date(2026, 11, 2), "Día de los Difuntos", REF), (date(2026, 12, 25), "Navidad", REF),
    (date(2027, 1, 1), "Año Nuevo", REF), (date(2027, 3, 25), "Jueves Santo", REF), (date(2027, 3, 26), "Viernes Santo", REF),
    (date(2027, 3, 27), "Sábado Santo", REF), (date(2027, 5, 1), "Día del Trabajo", REF), (date(2027, 5, 10), "Día de la Madre", REF),
    (date(2027, 6, 17), "Día del Padre", "Decreto Legislativo 399 (2016)"), (date(2027, 8, 6), "Fiestas Agostinas (Divino Salvador del Mundo)", REF),
    (date(2027, 9, 15), "Día de la Independencia", REF), (date(2027, 11, 2), "Día de los Difuntos", REF), (date(2027, 12, 25), "Navidad", REF),
]


def seed(apps, schema_editor):
    Country = apps.get_model("common", "Country")
    Holiday = apps.get_model("holidays", "Holiday")
    sv = Country.objects.filter(country_code="SV").first()
    if sv is None:
        return
    for d, name, ref in SV_HOLIDAYS:
        Holiday.objects.get_or_create(country_id=sv.pk, date=d, defaults={"name": name, "kind": "NATIONAL", "premium_percent": 100,
                                                                             "legal_reference": ref})


def unseed(apps, schema_editor):
    Holiday = apps.get_model("holidays", "Holiday")
    Segment = apps.get_model("holidays", "HolidaySegment")
    used = set(Segment.objects.values_list("holiday_id", flat=True))
    Holiday.objects.filter(date__in=[d for d, *_ in SV_HOLIDAYS], kind="NATIONAL").exclude(pk__in=used).delete()


class Migration(migrations.Migration):
    dependencies = [("holidays", "0001_initial")]

    operations = [
        migrations.RunSQL(FKS, FKS_DROP),
        migrations.RunSQL(LOCKED, "DROP TRIGGER IF EXISTS dbo.TR_hol_holiday_locked;"),
        migrations.RunSQL(VIEW, "DROP VIEW IF EXISTS dbo.vw_HolidaySegment;"),
        migrations.RunPython(seed, unseed),
    ]
