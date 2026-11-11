"""Fase 8: turnos JSON, asignación por fechas efectivas, tiempo por fecha de ocurrencia (turnos que cruzan
la medianoche), nocturnidad parametrizable, ciclos de pago y cortes internos, reporte teórico vs real."""

import io
from datetime import date, datetime, time

import pytest
from django.db import DatabaseError, connection, transaction

from apps.scheduling import engine
from apps.scheduling.models import NightRule, PayCycle, PayPeriod, ScheduleAssignment, TimeRecord, TimeRecordDay

pytestmark = pytest.mark.django_db
S = "/api/v1/scheduling"
NIGHT = {"days": {d: {"start": "22:00", "end": "06:00", "lunch_minutes": 30} for d in ("mon", "tue", "wed", "thu", "fri")}}
SV_NIGHT = engine.NightWindow(time(19), time(6), 25.0)


@pytest.fixture(autouse=True)
def _manual_time_entry(settings):
    # Fase 10: la carga manual está retirada por defecto; estas pruebas cubren la ingesta (base del Web Timer).
    settings.SCHEDULING_MANUAL_TIME_ENTRY = True


# ------------------------------------------------------------------ motor (puro)
def test_overnight_shift_is_split_by_occurrence_date_without_fragmenting_the_shift():
    d = engine.parse_definition(NIGHT)
    (inst,) = engine.shift_instances(d, date(2026, 10, 5), night_lookup=lambda _: SV_NIGHT)  # lunes
    assert inst.shift_date == date(2026, 10, 5) and inst.end == datetime(2026, 10, 6, 6, 0)
    first, second = inst.segments
    assert (first.occurrence_date, first.gross_minutes) == (date(2026, 10, 5), 120)
    assert (second.occurrence_date, second.gross_minutes) == (date(2026, 10, 6), 360)
    # 30 min de almuerzo repartidos proporcionalmente (la hora del almuerzo no es parte del turno)
    assert (first.lunch_minutes, second.lunch_minutes) == (7, 23) and inst.net_minutes == 450
    assert first.night_net_minutes == 113 and second.night_net_minutes == 337
    # Domingo de descanso: sin instancia
    assert engine.shift_instances(d, date(2026, 10, 11)) == []


def test_lunch_allocation_modes_and_night_window():
    assert engine.allocate_lunch([120, 360], 30, "START_DAY") == [30, 0]
    assert engine.allocate_lunch([20, 360], 30, "START_DAY") == [20, 10]
    assert engine.allocate_lunch([120, 360], 60, "LONGEST_SEGMENT") == [0, 60]
    assert sum(engine.allocate_lunch([241, 239], 61, "PROPORTIONAL")) == 61
    # 17:00–24:00 con nocturnidad 19:00–06:00 -> 5 h nocturnas
    assert engine.night_minutes(datetime(2026, 1, 1, 17), datetime(2026, 1, 2), SV_NIGHT) == 300
    assert engine.night_minutes(datetime(2026, 1, 1, 8), datetime(2026, 1, 1, 17), SV_NIGHT) == 0


def test_definition_rules():
    with pytest.raises(engine.DefinitionError) as exc:
        engine.parse_definition({"days": {"mon": {"start": "08:00", "end": "17:00", "lunch_minutes": 60, "lunch_start": "12:00"}}})
    assert "programa WFM" in exc.value.errors[0]["message"]
    with pytest.raises(engine.DefinitionError) as exc:
        engine.parse_definition({"days": {"mon": {"start": "22:00", "end": "08:00"}, "tue": {"start": "07:00", "end": "15:00"}}})
    assert "se traslapa" in str(exc.value)
    with pytest.raises(engine.DefinitionError):
        engine.parse_definition({"days": {"mon": {"start": "08:00", "end": "09:00", "lunch_minutes": 60}}})
    with pytest.raises(engine.DefinitionError):
        engine.parse_definition({"days": {"lunes": {"start": "8:00", "end": "8:00"}}})
    parsed = engine.parse_definition({"days": {"Lunes": {"start": "8:00", "end": "17:00", "lunch_minutes": "60"}}})
    assert parsed.as_json()["days"]["mon"] == [{"start": "08:00", "end": "17:00", "lunch_minutes": 60}]
    assert parsed.weekly_net_minutes == 480


def test_periods_and_internal_cutoffs_are_contiguous():
    periods = engine.generate_periods(engine.CycleRule("HALF_MONTH", cutoff_lag_days=5, payment_lag_days=2), 2026)
    assert len(periods) == 24
    nov2 = next(p for p in periods if p["label"] == "2026-11-Q2")
    assert (nov2["period_start"], nov2["period_end"]) == (date(2026, 11, 16), date(2026, 11, 30))
    assert (nov2["cutoff_start"], nov2["cutoff_end"], nov2["payment_date"]) == (date(2026, 11, 11), date(2026, 11, 25), date(2026, 12, 2))
    for a, b in zip(periods, periods[1:]):
        assert (b["cutoff_start"] - a["cutoff_end"]).days == 1 and (b["period_start"] - a["period_end"]).days == 1
    feb = [p for p in periods if p["period_start"].month == 2]
    assert feb[1]["period_end"] == date(2026, 2, 28)
    assert len(engine.generate_periods(engine.CycleRule("MONTH"), 2026)) == 12
    weekly = engine.generate_periods(engine.CycleRule("FIXED_DAYS", length_days=7, anchor_date=date(2026, 1, 5)), 2026)
    assert weekly[0]["period_start"] == date(2026, 1, 5) and all((p["period_end"] - p["period_start"]).days == 6 for p in weekly)


# ------------------------------------------------------------------ parámetros sembrados
def test_seeded_reference_parameters(countries):
    rule = NightRule.objects.get(country=countries["SV"])
    assert (rule.start_time, rule.end_time, float(rule.surcharge_percent)) == (time(19), time(6), 25.0)
    cycle = PayCycle.objects.get(code="SV_QUINCENAL")
    assert cycle.periods.filter(period_start__year=2026).count() == 24


# ------------------------------------------------------------------ tiempo por fecha de ocurrencia
def test_time_record_crossing_midnight_goes_to_each_occurrence_date(api, wfm_user, make_employee):
    api.force_login(wfm_user)
    emp = make_employee("SV", hire_date=date(2026, 3, 1))
    ScheduleAssignment.objects.create(employee=emp, definition=NIGHT, effective_start_date=date(2026, 9, 1))
    r = api.post(f"{S}/time-records/", {"employee_code": emp.employee_code, "start_at": "2026-10-05 21:55", "end_at": "2026-10-06 06:05"}, format="json")
    assert r.status_code == 201, r.json()
    rec = r.json()["record"]
    assert rec["shift_date"] == "2026-10-05" and rec["minutes"] == 490
    days = {d["occurrence_date"]: d for d in rec["days"]}
    assert days["2026-10-05"]["minutes"] == 125 and days["2026-10-06"]["minutes"] == 365
    assert days["2026-10-05"]["night_minutes"] == 125 and days["2026-10-06"]["night_minutes"] == 360  # 06:00–06:05 es diurno
    assert {d["shift_date"] for d in rec["days"]} == {"2026-10-05"}  # un solo turno, trazable

    # La hora local se guarda tal cual (sin conversión a UTC)
    stored = TimeRecordDay.objects.get(record_id=rec["id"], occurrence_date=date(2026, 10, 6))
    assert stored.start_at == datetime(2026, 10, 6, 0, 0) and stored.end_at == datetime(2026, 10, 6, 6, 5)

    clash = api.post(f"{S}/time-records/", {"employee_code": emp.employee_code, "start_at": "2026-10-06 05:00", "end_at": "2026-10-06 07:00"}, format="json")
    assert clash.status_code == 400 and clash.json()["errors"][0]["code"] == "overlap"
    future = api.post(f"{S}/time-records/", {"employee_code": emp.employee_code, "occurrence_date": "2030-01-01", "hours": "8"}, format="json")
    assert future.status_code == 400
    tz = api.post(f"{S}/time-records/", {"employee_code": emp.employee_code, "start_at": "2026-10-07T22:00Z", "end_at": "2026-10-08 06:00"}, format="json")
    assert tz.status_code == 400 and tz.json()["errors"][0]["field"] == "start_at"

    with pytest.raises(DatabaseError) as exc, transaction.atomic():
        TimeRecord.objects.create(employee=emp, kind="INTERVAL", start_at=datetime(2026, 10, 5, 23), end_at=datetime(2026, 10, 6, 1),
                                  occurrence_date=date(2026, 10, 5), minutes=120)
    assert "50041" in str(exc.value)


def test_hours_report_theoretical_vs_actual_by_occurrence_date(api, hr_user, make_employee):
    api.force_login(hr_user)
    emp = make_employee("SV", hire_date=date(2026, 3, 1))
    ScheduleAssignment.objects.create(employee=emp, definition=NIGHT, effective_start_date=date(2026, 9, 1))
    api.post(f"{S}/time-records/", {"employee_code": emp.employee_code, "start_at": "2026-10-05 22:00", "end_at": "2026-10-06 06:00"}, format="json")
    api.post(f"{S}/time-records/", {"employee_code": emp.employee_code, "occurrence_date": "2026-10-10", "hours": "4:30"}, format="json")

    r = api.get(f"{S}/report/", {"from": "2026-10-05", "to": "2026-10-11", "employee": emp.employee_code})
    assert r.status_code == 200, r.json()
    rows = {x["occurrence_date"]: x for x in r.json()["results"]}
    mon, tue = rows["2026-10-05"], rows["2026-10-06"]
    assert (mon["scheduled_minutes"], mon["worked_minutes"]) == (113, 120)
    # Martes: 6 h del turno del lunes + 2 h del turno del martes (22:00) en teoría; realmente laboró 6 h del lunes
    assert tue["scheduled_minutes"] == 337 + 113 and tue["worked_minutes"] == 360
    assert tue["shift_dates"] == ["2026-10-05", "2026-10-06"]
    assert mon["worked_night_minutes"] == 120 and mon["night_premium_minutes"] == 30 and mon["night_surcharge_percent"] == 25.0
    assert rows["2026-10-07"]["flag"] == "ABSENT"
    assert rows["2026-10-10"]["flag"] == "SHORT" and rows["2026-10-10"]["worked_minutes"] == 270
    assert "2026-10-11" not in rows  # domingo de descanso sin registros
    assert rows["2026-10-10"]["scheduled_minutes"] == 337  # sábado: la porción del turno del viernes
    totals = r.json()["totals"]
    assert totals["scheduled_minutes"] == 5 * 450 and totals["worked_minutes"] == 480 + 270
    csv_resp = api.get(f"{S}/report/", {"from": "2026-10-05", "to": "2026-10-11", "employee": emp.employee_code, "export": "csv"})
    assert csv_resp.status_code == 200 and "Fecha de ocurrencia" in csv_resp.content.decode("utf-8-sig")


# ------------------------------------------------------------------ ciclos y cortes
def test_closed_cutoff_blocks_time_changes_and_cycles_are_parametrizable(api, hr_user, wfm_user, make_employee, countries):
    emp = make_employee("SV", hire_date=date(2026, 3, 1))  # mensual -> ciclo SV_MENSUAL
    period = PayPeriod.objects.get(cycle__code="SV_MENSUAL", code="2026-09")
    api.force_login(wfm_user)
    assert api.post(f"/api/v1/scheduling/pay-periods/{period.pk}/close/").status_code == 403  # WFM no administra nómina
    api.force_login(hr_user)
    r = api.post(f"{S}/pay-periods/{period.pk}/close/")
    assert r.status_code == 200 and r.json()["period"]["status"] == "CLOSED"
    blocked = api.post(f"{S}/time-records/", {"employee_code": emp.employee_code, "occurrence_date": "2026-09-15", "hours": "8"}, format="json")
    assert blocked.status_code == 400 and blocked.json()["errors"][0]["code"] == "closed_period"
    assert api.post(f"{S}/pay-periods/{period.pk}/reopen/").status_code == 200

    cycle = PayCycle.objects.create(code="SV_SEMANAL", name="Semanal", country=countries["SV"], pay_frequency="WEEKLY",
                                    period_rule="FIXED_DAYS", length_days=7, anchor_date=date(2026, 1, 5), cutoff_lag_days=2)
    r = api.post(f"{S}/pay-cycles/SV_SEMANAL/generate/", {"year": 2026}, format="json")
    assert r.status_code == 200 and r.json()["created"] == 52
    assert api.post(f"{S}/pay-cycles/SV_SEMANAL/generate/", {"year": 2026}, format="json").json()["created"] == 0
    listing = api.get(f"{S}/pay-cycles/", {"year": 2026}).json()
    weekly = next(c for c in listing["results"] if c["code"] == "SV_SEMANAL")
    assert weekly["periods"][1]["cutoff_start"] == "2026-01-10"

    # Trigger 50044: ventanas de corte traslapadas
    first = cycle.periods.order_by("period_start").first()
    with pytest.raises(DatabaseError) as exc, transaction.atomic():
        PayPeriod.objects.create(cycle=cycle, code="X", period_start=date(2027, 6, 1), period_end=date(2027, 6, 7),
                                 cutoff_start=first.cutoff_end, cutoff_end=date(2027, 6, 5), payment_date=date(2027, 6, 7))
    assert "50044" in str(exc.value)


def test_night_rule_overlap_is_rejected_by_sql_server(countries):
    with pytest.raises(DatabaseError) as exc, transaction.atomic():
        NightRule.objects.create(country=countries["SV"], name="Duplicada", start_time=time(20), end_time=time(5),
                                 surcharge_percent=30, effective_start_date=date(2026, 1, 1))
    assert "50042" in str(exc.value)


# ------------------------------------------------------------------ carga de archivos
def test_time_upload_is_all_or_nothing(api, wfm_user, make_employee):
    api.force_login(wfm_user)
    emp = make_employee("SV", hire_date=date(2026, 3, 1))
    good = f"employee_code,start_at,end_at\n{emp.employee_code},2026-10-12 22:00,2026-10-13 06:00\n"
    bad = good + f"{emp.employee_code},2026-10-13 05:00,2026-10-13 07:00\n"

    def send(text, dry=False):
        f = io.BytesIO(text.encode()); f.name = "tiempos.csv"
        return api.post(f"{S}/time-records/upload/" + ("?dry_run=1" if dry else ""), {"file": f}, format="multipart")

    r = send(bad)
    assert r.status_code == 400 and r.json()["errors"] == 1 and "fila 2" in r.json()["rows"][1]["errors"][0]["message"]
    assert not TimeRecord.objects.filter(employee=emp).exists()
    assert send(good, dry=True).json()["created"] == 0
    r = send(good)
    assert r.status_code == 200 and r.json()["created"] == 1
    assert sorted(TimeRecordDay.objects.filter(employee=emp).values_list("occurrence_date", "minutes")) == [
        (date(2026, 10, 12), 120), (date(2026, 10, 13), 360)]


# ------------------------------------------------------------------ permisos y vistas SQL
def test_permissions_and_reporting_views(api, employee_user, wfm_user):
    api.force_login(employee_user)
    assert api.get(f"{S}/catalogs/").status_code == 403
    assert api.get(f"{S}/report/").status_code == 403
    api.force_login(wfm_user)
    body = api.get(f"{S}/catalogs/").json()
    assert body["can_manage"] and not body["can_manage_cycles"]
    assert any(r["country"] == "SV" and r["start_time"] == "19:00" for r in body["night_rules"])
    with connection.cursor() as cursor:
        for view in ("vw_SchTimeByOccurrenceDate", "vw_SchScheduleAssignment", "vw_SchPayPeriod"):
            cursor.execute(f"SELECT TOP 1 * FROM dbo.{view}")
