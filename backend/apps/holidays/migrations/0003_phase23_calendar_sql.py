"""Fase 23: calendario de feriados en SQL Server.

* dbo.fn_EasterSunday(@Year)        domingo de Pascua (algoritmo gregoriano anónimo) para los feriados móviles.
* dbo.usp_HolidayCopyYear           copia los feriados de un año a otro: los fijos con el mismo día y mes y los de
                                    Semana Santa (Jueves, Viernes y Sábado Santo) recalculados con la Pascua del año
                                    destino; omite las fechas que ya existen (y el 29 de febrero en años no bisiestos).
* dbo.vw_HolidayCalendar            calendario por país, año, mes, día y día de la semana ISO (lunes = 1) con los
                                    Holiday Segments generados.
"""

from django.db import migrations

EASTER = """
CREATE OR ALTER FUNCTION dbo.fn_EasterSunday (@Year int)
RETURNS date
AS
BEGIN
    DECLARE @a int = @Year % 19, @b int = @Year / 100, @c int = @Year % 100;
    DECLARE @d int = @b / 4, @e int = @b % 4, @f int = (@b + 8) / 25;
    DECLARE @g int = (@b - @f + 1) / 3;
    DECLARE @h int = (19 * @a + @b - @d - @g + 15) % 30;
    DECLARE @i int = @c / 4, @k int = @c % 4;
    DECLARE @l int = (32 + 2 * @e + 2 * @i - @h - @k) % 7;
    DECLARE @m int = (@a + 11 * @h + 22 * @l) / 451;
    DECLARE @month int = (@h + @l - 7 * @m + 114) / 31;
    DECLARE @day int = ((@h + @l - 7 * @m + 114) % 31) + 1;
    RETURN DATEFROMPARTS(@Year, @month, @day);
END;
"""

COPY = """
CREATE OR ALTER PROCEDURE dbo.usp_HolidayCopyYear
    @CountryId int,
    @FromYear int,
    @ToYear int,
    @UserId int = NULL
AS
BEGIN
    SET NOCOUNT ON;
    IF @FromYear = @ToYear
        THROW 50098, N'El año destino debe ser distinto del año de origen.', 1;
    DECLARE @Easter date = dbo.fn_EasterSunday(@ToYear);
    DECLARE @created TABLE (id bigint, date date, name nvarchar(120));
    WITH src AS (
        SELECT h.country_id, h.name, h.kind, h.premium_percent, h.legal_reference, h.is_active,
               CASE
                   WHEN h.name LIKE N'Jueves Santo%' THEN DATEADD(day, -3, @Easter)
                   WHEN h.name LIKE N'Viernes Santo%' THEN DATEADD(day, -2, @Easter)
                   WHEN h.name LIKE N'S_bado Santo%' THEN DATEADD(day, -1, @Easter)
                   WHEN MONTH(h.date) = 2 AND DAY(h.date) = 29
                        AND NOT (@ToYear % 4 = 0 AND (@ToYear % 100 <> 0 OR @ToYear % 400 = 0)) THEN NULL
                   ELSE DATEFROMPARTS(@ToYear, MONTH(h.date), DAY(h.date))
               END AS new_date
        FROM dbo.hol_holiday h
        WHERE h.country_id = @CountryId AND YEAR(h.date) = @FromYear
    )
    INSERT INTO dbo.hol_holiday (country_id, date, name, kind, premium_percent, legal_reference, is_active, created_at, created_by_id)
    OUTPUT inserted.id, inserted.date, inserted.name INTO @created (id, date, name)
    SELECT s.country_id, s.new_date, s.name, s.kind, s.premium_percent, s.legal_reference, s.is_active, SYSUTCDATETIME(), @UserId
    FROM src s
    WHERE s.new_date IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM dbo.hol_holiday x WHERE x.country_id = s.country_id AND x.date = s.new_date);
    SELECT id, date, name FROM @created ORDER BY date;
END;
"""

VIEW = """
CREATE OR ALTER VIEW dbo.vw_HolidayCalendar
AS
SELECT h.id AS HolidayId, c.CountryCode, h.date AS HolidayDate,
       YEAR(h.date) AS CalendarYear, MONTH(h.date) AS CalendarMonth, DAY(h.date) AS CalendarDay,
       (DATEDIFF(day, CONVERT(date, '19000101'), h.date) % 7) + 1 AS IsoWeekday,
       h.name AS HolidayName, h.kind AS Kind, h.premium_percent AS PremiumPercent, h.is_active AS IsActive,
       (SELECT COUNT(*) FROM dbo.hol_holiday_segment s WHERE s.holiday_id = h.id) AS SegmentCount
FROM dbo.hol_holiday h
JOIN core.catCountry c ON c.CountryId = h.country_id;
"""


class Migration(migrations.Migration):
    dependencies = [("holidays", "0002_sql_rules_and_seed")]

    operations = [
        migrations.RunSQL(EASTER, "DROP FUNCTION IF EXISTS dbo.fn_EasterSunday;"),
        migrations.RunSQL(COPY, "DROP PROCEDURE IF EXISTS dbo.usp_HolidayCopyYear;"),
        migrations.RunSQL(VIEW, "DROP VIEW IF EXISTS dbo.vw_HolidayCalendar;"),
    ]
