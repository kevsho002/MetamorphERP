"""Fase 10: cortes BPO que cruzan de mes, carga manual de tiempos retirada, ciclos agrupados por año,
varios bloques / AP el mismo día con reglas de almuerzo por país y desglose por fecha de ocurrencia."""

from datetime import date, time

import pytest
from django.db import DatabaseError, connection, transaction

from apps.personnel_actions.models import PersonnelAction
from apps.scheduling import engine
from apps.scheduling.models import AttendanceCutoff, LunchRule, PayCycle, PayPeriod, ScheduleAssignment
from tests.test_phase9 import hire

pytestmark = pytest.mark.django_db
S = "/api/v1/scheduling"
PA = "/api/v1/personnel-actions"


# ------------------------------------------------------------------ 1. ciclos BPO (10–24 / 25–9)
def test_bpo_half_month_crosses_months_and_is_contiguous():
    rule = engine.CycleRule("HALF_MONTH", first_half_end_day=24, period_start_day=10)
    periods = engine.generate_periods(rule, 2026)
    assert len(periods) == 24
    nov2 = next(p for p in periods if p["label"] == "2026-11-Q2")
    assert (nov2["period_start"], nov2["period_end"]) == (date(2026, 11, 25), date(2026, 12, 9))
    feb2 = next(p for p in periods if p["label"] == "2026-02-Q2")
    assert (feb2["period_start"], feb2["period_end"]) == (date(2026, 2, 25), date(2026, 3, 9))
    for a, b in zip(periods, periods[1:]):
        assert (b["period_start"] - a["period_end"]).days == 1
    assert engine.describe_rule(rule) == "Del 10 al 24 y del 25 al 9 del mes siguiente"
    monthly = engine.generate_periods(engine.CycleRule("MONTH", period_start_day=21), 2026)
    assert (monthly[0]["period_start"], monthly[0]["period_end"]) == (date(2026, 1, 21), date(2026, 2, 20))


def test_seeded_bpo_cycle_and_sql_continuity_rules(api, hr_user):
    """Fase 11: el ejemplo BPO paga por quincena calendario y corta la asistencia del 25 al 9 y del 10 al 24."""
    cycle = PayCycle.objects.get(code="SV_QUINCENAL_BPO")
    assert not cycle.is_default and cycle.periods.count() == 24 and cycle.cutoffs.count() == 24
    last = cycle.periods.order_by("period_start").last()
    assert (last.period_start, last.period_end) == (date(2026, 12, 16), date(2026, 12, 31))

    # Cerrar / reabrir un corte no se ve afectado por las reglas de continuidad
    api.force_login(hr_user)
    first = cycle.cutoffs.order_by("cutoff_start").first()
    assert api.post(f"{S}/cutoffs/{first.pk}/close/").status_code == 200
    assert api.post(f"{S}/cutoffs/{first.pk}/reopen/").status_code == 200

    # 50045: hueco contra el fin del periodo de pago anterior
    with pytest.raises(DatabaseError) as exc, transaction.atomic():
        PayPeriod.objects.create(cycle=cycle, code="GAP", period_start=date(2027, 1, 3), period_end=date(2027, 1, 15),
                                 payment_date=date(2027, 1, 15))
    assert "50045" in str(exc.value)


def test_cutoff_window_gap_is_rejected_by_sql_server():
    cycle = PayCycle.objects.get(code="SV_QUINCENAL_BPO")
    dec2 = cycle.periods.get(code="2026-12-Q2")
    with pytest.raises(DatabaseError) as exc, transaction.atomic():  # el último corte cierra el 24/12
        AttendanceCutoff.objects.create(cycle=cycle, pay_period=dec2, code="CUT", cutoff_start=date(2026, 12, 27), cutoff_end=date(2026, 12, 30))
    assert "50046" in str(exc.value)


def test_period_model_validation_explains_continuity():
    cycle = PayCycle.objects.get(code="SV_QUINCENAL_BPO")
    p = PayPeriod(cycle=cycle, code="X", period_start=date(2027, 1, 5), period_end=date(2027, 1, 15), payment_date=date(2027, 1, 15))
    errors = p.continuity_errors()
    assert "deja un hueco después de 2026-12-Q2" in errors["period_start"] and "01/01/2027" in errors["period_start"]


def test_rule_change_generates_transition_period_without_gaps(api, hr_user):
    """SV_QUINCENAL (1–15 / 16–fin) pasa a corte BPO 10–24 / 25–9 para 2027: el primer periodo cubre el hueco."""
    api.force_login(hr_user)
    PayCycle.objects.filter(code="SV_QUINCENAL").update(period_start_day=10, first_half_end_day=24)
    r = api.post(f"{S}/pay-cycles/SV_QUINCENAL/generate/", {"year": 2027}, format="json")
    assert r.status_code == 200 and r.json()["created"] == 24, r.json()
    periods = list(PayCycle.objects.get(code="SV_QUINCENAL").periods.filter(period_start__year=2027).order_by("period_start"))
    assert (periods[0].period_start, periods[0].period_end) == (date(2027, 1, 1), date(2027, 1, 24))
    assert (periods[1].period_start, periods[1].period_end) == (date(2027, 1, 25), date(2027, 2, 9))
    # Saltarse un año entero deja un hueco: se rechaza con un mensaje claro
    r = api.post(f"{S}/pay-cycles/SV_QUINCENAL/generate/", {"year": 2029}, format="json")
    assert r.status_code == 400 and r.json()["code"] == "period_gap"


def test_cycle_clean_rules(countries):
    from django.core.exceptions import ValidationError

    c = PayCycle(code="T", name="T", country=countries["SV"], pay_frequency="BIWEEKLY", period_rule="HALF_MONTH",
                 period_start_day=20, first_half_end_day=24)
    with pytest.raises(ValidationError) as exc:
        c.clean()
    assert "first_half_end_day" in exc.value.message_dict


# ------------------------------------------------------------------ 2. carga manual retirada
def test_manual_time_entry_is_disabled_by_default(api, wfm_user, make_employee):
    api.force_login(wfm_user)
    emp = make_employee("SV", hire_date=date(2026, 3, 1))
    r = api.post(f"{S}/time-records/", {"employee_code": emp.employee_code, "occurrence_date": "2026-10-05", "hours": "8"}, format="json")
    assert r.status_code == 403 and r.json()["code"] == "manual_time_disabled"
    assert api.post(f"{S}/time-records/upload/", {"rows": []}, format="json").status_code == 403
    assert api.delete(f"{S}/time-records/1/").status_code == 403
    assert api.get(f"{S}/time-records/").status_code == 200  # consulta de lo existente
    body = api.get(f"{S}/catalogs/").json()
    assert body["manual_time_entry"] is False and any(s["value"] == "WEB_TIMER" for s in body["sources"])


# ------------------------------------------------------------------ 3. ciclos agrupados por año
def test_pay_cycles_grouped_by_year_without_repeating_cross_year_periods(api, hr_user):
    api.force_login(hr_user)
    y2026 = api.get(f"{S}/pay-cycles/", {"year": 2026}).json()
    assert 2026 in y2026["years"]
    bpo = next(c for c in y2026["results"] if c["code"] == "SV_QUINCENAL_BPO")
    assert bpo["cutoffs_cross_month"] and bpo["cutoff_rule_description"].startswith("Del 10 al 24")
    assert bpo["stats"]["total"] == 24 and bpo["stats"]["cutoffs"] == 24
    assert bpo["periods"][0]["cutoffs"][0]["crosses_month"]  # el corte 25/12–09/01 se paga en la quincena 1–15 de enero
    y2027 = api.get(f"{S}/pay-cycles/", {"year": 2027}).json()
    assert all(not c["periods"] for c in y2027["results"])
    monthly = api.get(f"{S}/pay-cycles/", {"year": 2026, "frequency": "MONTHLY"}).json()
    assert [c["code"] for c in monthly["results"]] == ["SV_MENSUAL"]


# ------------------------------------------------------------------ 4. varios bloques / AP el mismo día
def test_split_shift_without_lunch_and_lunch_rules():
    split = engine.parse_definition(engine.parse_schedule_text("L-V 08:00-12:00 + 13:00-17:00"))
    assert split.weekly_net_minutes == 5 * 480 and split.has_split_days
    rule = engine.LunchRule(360, 30, "WARN", "≥ 6 h")
    assert engine.check_lunch(split, [rule]) == ([], [])  # cada bloque dura 4 h: no requiere almuerzo
    continuous = engine.parse_definition(engine.parse_schedule_text("L 08:00-17:00"))
    errors, warnings = engine.check_lunch(continuous, [rule])
    assert not errors and "30 min" in warnings[0]["message"]
    errors, _ = engine.check_lunch(continuous, [engine.LunchRule(360, 30, "REQUIRE", "≥ 6 h")])
    assert errors and errors[0]["code"] == "lunch_rule"
    # tramos: aplica el de umbral más alto alcanzado
    tiers = [engine.LunchRule(300, 30, "WARN"), engine.LunchRule(540, 60, "WARN")]
    assert engine.lunch_rule_for(600, tiers).lunch_minutes == 60
    with pytest.raises(engine.DefinitionError):
        engine.parse_definition({"days": {"mon": [{"start": "08:00", "end": "12:00"}, {"start": "11:30", "end": "14:00"}]}})


def test_hire_with_split_shift_and_lunch_rule_feedback(api, hr_user, countries):
    api.force_login(hr_user)
    emp = hire(api, schedule="L-V 08:00-12:00 + 13:00-17:00")
    a = ScheduleAssignment.objects.get(employee=emp)
    assert a.mode == "PRIMARY" and len(a.definition["days"]["mon"]) == 2 and a.weekly_minutes == 5 * 480

    preview = api.post(f"{S}/schedule-preview/", {"schedule": "L-V 08:00-17:00", "country": "SV", "effective_date": "2026-10-05"}, format="json").json()
    assert preview["valid"] and preview["warnings"] and preview["lunch_rules"][0]["min_block_minutes"] == 360
    LunchRule.objects.filter(country=countries["SV"]).update(enforcement="REQUIRE")
    preview = api.post(f"{S}/schedule-preview/", {"schedule": "L-V 08:00-17:00", "country": "SV", "effective_date": "2026-10-05"}, format="json")
    assert preview.status_code == 400 and preview.json()["errors"][0]["field"].startswith("definition.days.mon")


def _approve(api, users, payload):
    api.force_login(users[0])
    r = api.post(PA + "/", {**payload, "submit": True}, format="json")
    assert r.status_code == 201, r.json()
    folio = r.json()["action"]["folio"]
    for user in users[1:]:
        api.force_login(user)
        r = api.post(f"{PA}/{folio}/sign/", {"decision": "APPROVED", "comment": "OK"}, format="json")
        assert r.status_code == 200, r.json()
    return PersonnelAction.objects.get(folio=folio)


def test_additional_assignment_adds_hours_and_cannot_collide(api, hr_user, wfm_user):
    api.force_login(hr_user)
    emp = hire(api, schedule="L-V 08:00-12:00 + 13:00-17:00")
    base = {"action_type": "AP_HORARIO_ADICIONAL", "employee_code": emp.employee_code, "effective_date": "2026-10-05",
            "justification": "Refuerzo en campaña de cierre de año."}
    api.force_login(wfm_user)
    clash = api.post(f"{PA}/validate/", {**base, "values": {"motivo": "Refuerzo operativo", "horario": "L-V 16:00-19:00",
                                                         "vigente_hasta": "2026-12-31"}}, format="json").json()
    assert not clash["valid"] and clash["errors"][0]["code"] == "schedule_collision"
    no_end = api.post(f"{PA}/validate/", {**base, "values": {"motivo": "Refuerzo operativo", "horario": "L-V 18:00-20:00"}}, format="json").json()
    assert not no_end["valid"]

    action = _approve(api, [wfm_user, hr_user], {**base, "values": {
        "motivo": "Doble asignación / otra campaña", "horario": "L-V 18:00-20:00; S 08:00-12:00", "vigente_hasta": "2026-12-31"}})
    assert action.status == "APPROVED"
    extra = ScheduleAssignment.objects.get(personnel_action=action)
    assert extra.mode == "ADDITIONAL" and extra.effective_end_date == date(2026, 12, 31)
    primary = ScheduleAssignment.objects.get(employee=emp, mode="PRIMARY")
    assert primary.effective_end_date is None  # el principal sigue vigente

    api.force_login(hr_user)
    rows = {r["occurrence_date"]: r for r in api.get(f"{S}/report/", {"from": "2026-10-05", "to": "2026-10-11", "employee": emp.employee_code}).json()["results"]}
    mon = rows["2026-10-05"]
    assert mon["scheduled_minutes"] == 480 + 120 and len(mon["actions"]) == 2 and action.folio in mon["actions"]
    assert mon["scheduled_night_minutes"] == 60  # 19:00–20:00 nocturno (SV 19:00–06:00)
    assert rows["2026-10-10"]["scheduled_minutes"] == 240  # sábado: solo la asignación adicional

    # Un cambio del horario principal no puede pedir las horas de la asignación adicional
    api.force_login(wfm_user)
    change = api.post(f"{PA}/validate/", {"action_type": "AP_CAMBIO_HORARIO", "employee_code": emp.employee_code,
                                          "effective_date": "2026-11-02", "justification": "x",
                                          "values": {"motivo": "Otro", "horario": "L-V 12:00-21:00 60"}}, format="json").json()
    assert not change["valid"] and change["errors"][0]["code"] == "schedule_collision"

    body = api.get(f"{PA}/employees/{emp.employee_code}/").json()
    assert body["current_schedule"]["mode"] == "PRIMARY" and body["additional_schedules"][0]["folio"] == action.folio

    # SQL Server: dos horarios PRINCIPALES en fechas que se cruzan siguen prohibidos; uno ADICIONAL necesita fin
    with pytest.raises(DatabaseError) as exc, transaction.atomic():
        ScheduleAssignment.objects.create(employee=emp, definition=primary.definition, effective_start_date=date(2026, 11, 1))
    assert "50040" in str(exc.value)
    with pytest.raises(DatabaseError), transaction.atomic():
        ScheduleAssignment.objects.create(employee=emp, mode="ADDITIONAL", definition=primary.definition, effective_start_date=date(2027, 1, 1))


# ------------------------------------------------------------------ 5. desglose por fecha de ocurrencia
def test_day_detail_shows_blocks_including_previous_day_overnight(api, hr_user):
    api.force_login(hr_user)
    emp = hire(api, schedule="L-V 22:00-06:00 30")
    r = api.get(f"{S}/employees/{emp.employee_code}/days/2026-10-06/")
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["weekday"] == "martes" and body["previous_date"] == "2026-10-05"
    assert [b["from_previous_day"] for b in body["blocks"]] == [True, False]
    assert body["summary"]["scheduled_minutes"] == 337 + 113
    assert body["assignments"][0]["folio"] and body["night_rule"]["start"] == "19:00"
    assert body["period"]["cycle"] == "SV_MENSUAL" and body["cutoff"]["code"] == "C-2026-10" and body["lunch_rules"]
    assert api.get(f"{S}/employees/{emp.employee_code}/days/2026-13-45/").status_code == 400


def test_phase10_reporting_views(api, hr_user):
    api.force_login(hr_user)
    emp = hire(api, schedule="L-V 08:00-12:00 + 13:00-17:00")
    with connection.cursor() as cursor:
        cursor.execute("SELECT BlockNo, StartTime, DayMinutes FROM dbo.vw_SchScheduleDay WHERE EmployeeCode = %s AND DayKey = 'mon' ORDER BY BlockNo",
                       [emp.employee_code])
        assert [tuple(r) for r in cursor.fetchall()] == [(1, "08:00", 240), (2, "13:00", 240)]
        cursor.execute("SELECT AssignmentMode FROM dbo.vw_SchScheduleAssignment WHERE EmployeeCode = %s", [emp.employee_code])
        assert cursor.fetchone()[0] == "PRIMARY"
        cursor.execute("SELECT MinContinuousMinutes, LunchMinutes FROM dbo.vw_SchLunchRule WHERE CountryCode = 'SV'")
        assert tuple(cursor.fetchone()) == (360, 30)
    assert time(19) == engine.parse_hhmm("19:00")
