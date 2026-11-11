"""Fase 9: Acciones de Personal (AP) EAV con folio, firmas por rol y efecto; horarios atómicos por día
(sin turnos predefinidos) y Primera AP de asignación de horario obligatoria en el alta."""

import io
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.hcm.models import Employee
from apps.personnel_actions import services
from apps.personnel_actions.models import ActionSignature, ActionType, ActionValue, PersonnelAction
from apps.scheduling.models import PayPeriod, ScheduleAssignment
from tests.test_employees import EMPLOYEES, IMPORTS, sv_row, to_csv

pytestmark = pytest.mark.django_db
PA = "/api/v1/personnel-actions"
NIGHT = {"days": {d: {"start": "22:00", "end": "06:00", "lunch_minutes": 30} for d in ("mon", "tue", "wed", "thu", "fri")}}


def hire(api, **overrides):
    r = api.post(EMPLOYEES, sv_row(**overrides), format="json")
    assert r.status_code == 201, r.json()
    return Employee.objects.get(employee_code=r.json()["employee"]["employee_code"])


# ------------------------------------------------------------------ alta: Primera AP obligatoria
def test_hire_creates_and_applies_the_initial_schedule_action(api, hr_user):
    api.force_login(hr_user)
    missing = api.post(f"{EMPLOYEES}validate/", sv_row(schedule=""), format="json").json()
    assert not missing["valid"] and any(e["field"] == "schedule" for e in missing["errors"])
    bad = api.post(f"{EMPLOYEES}validate/", sv_row(schedule="L-V 08:00-17:00 60, lunch_start 12:00"), format="json").json()
    assert not bad["valid"]

    emp = hire(api, schedule="L-V 14:00-23:00 60; S 08:00-12:00")
    action = PersonnelAction.objects.get(employee=emp)
    assert action.is_initial and action.status == "APPROVED" and action.applied_at is not None
    assert action.folio.startswith(f"APH-{emp.hire_date.year}-") and action.effective_date == emp.hire_date
    sig = action.signatures.get()
    assert sig.signer == hr_user and sig.required_role == "HR" and len(sig.signature) == 64
    a = ScheduleAssignment.objects.get(employee=emp)
    assert a.personnel_action == action and a.effective_start_date == emp.hire_date and a.effective_end_date is None
    (mon,) = a.definition["days"]["mon"]
    # 14:00–23:00 con 60 min de almuerzo y nocturnidad SV 19:00–06:00: 8 h netas = 4:27 diurnas + 3:33 nocturnas
    assert (mon["start"], mon["end"], mon["lunch_minutes"], mon["day_minutes"], mon["night_minutes"]) == ("14:00", "23:00", 60, 267, 213)
    assert a.definition["days"]["sun"] is None and a.weekly_minutes == 5 * 480 + 240

    body = api.get(f"{PA}/employees/{emp.employee_code}/").json()
    assert body["initial_action"]["folio"] == action.folio and body["current_schedule"]["folio"] == action.folio
    assert services.verify(action)["valid"]


def test_batch_hire_requires_schedule_column(api, hr_user):
    api.force_login(hr_user)
    rows = [sv_row(national_id_number="11111111-1", work_email="a1@metamorph.test"),
            sv_row(national_id_number="22222222-2", work_email="a2@metamorph.test", schedule="")]
    f = io.BytesIO(to_csv(rows)); f.name = "altas.csv"
    r = api.post(IMPORTS, {"file": f, "atomicity": "ROW"}, format="multipart")
    assert r.status_code in (200, 201), r.json()
    statuses = sorted(row["status"] for row in r.json()["rows"])
    assert statuses == ["CREATED", "ERROR"]
    assert PersonnelAction.objects.filter(is_initial=True, status="APPROVED").count() == 1


# ------------------------------------------------------------------ cambio de horario por AP (cadena WFM -> RRHH)
def test_schedule_change_action_signature_chain_and_effective_dates(api, hr_user, wfm_user):
    api.force_login(hr_user)
    emp = hire(api)
    api.force_login(wfm_user)
    types = {t["code"]: t for t in api.get(f"{PA}/types/").json()["results"]}
    assert "AP_AJUSTE_SALARIAL" not in types  # WFM no ve datos salariales
    assert [s["role"] for s in types["AP_CAMBIO_HORARIO"]["steps"]] == ["WFM", "HR"]

    payload = {"action_type": "AP_CAMBIO_HORARIO", "employee_code": emp.employee_code, "effective_date": "2026-10-05",
               "justification": "Pasa a la cuenta nocturna.", "values": {"motivo": "Necesidad operativa", "horario": NIGHT}}
    wrong = api.post(f"{PA}/validate/", {**payload, "values": {"motivo": "Necesidad operativa", "horario": {
        "days": {"mon": {"start": "22:00", "end": "06:00", "lunch_minutes": 30, "night_minutes": 100}}}}}, format="json").json()
    assert not wrong["valid"] and "no coinciden" in wrong["errors"][0]["message"]

    r = api.post(PA + "/", {**payload, "submit": True}, format="json")
    assert r.status_code == 201, r.json()
    action = r.json()["action"]
    assert action["status"] == "PENDING" and action["steps"][0]["signature"]["signer"] == "wfm.test"
    assert action["next_step"]["role"] == "HR" and not action["can_sign"]
    assert action["values"][1]["schedule"]["days"][0]["night_minutes"] == 450
    folio = action["folio"]

    api.force_login(hr_user)
    assert api.get(f"{PA}/", {"pending_for_me": 1}).json()["count"] == 1
    assert api.post(f"{PA}/{folio}/sign/", {"decision": "REJECTED"}, format="json").status_code == 400  # motivo obligatorio
    r = api.post(f"{PA}/{folio}/sign/", {"decision": "APPROVED", "comment": "OK"}, format="json")
    assert r.status_code == 200 and r.json()["action"]["status"] == "APPROVED", r.json()
    rows = list(ScheduleAssignment.objects.filter(employee=emp).order_by("effective_start_date"))
    assert [(x.effective_start_date, x.effective_end_date) for x in rows] == [(emp.hire_date, date(2026, 10, 4)), (date(2026, 10, 5), None)]
    assert rows[1].personnel_action.folio == folio
    detail = api.get(f"{PA}/{folio}/").json()
    assert detail["integrity"]["valid"] and len(detail["steps"]) == 2

    # Una AP de horario no puede retroceder a fechas de un horario ya aplicado
    again = api.post(f"{PA}/validate/", {**payload, "effective_date": "2026-10-01"}, format="json").json()
    assert any(e["code"] == "schedule_overlap" for e in again["errors"])

    # El reporte de horas muestra la AP de origen
    rep = api.get("/api/v1/scheduling/report/", {"from": "2026-10-05", "to": "2026-10-06", "employee": emp.employee_code}).json()
    assert rep["results"][0]["actions"] == [folio]


def test_rejection_and_cancellation(api, hr_user, wfm_user):
    api.force_login(hr_user)
    emp = hire(api)
    api.force_login(wfm_user)
    base = {"action_type": "AP_CAMBIO_HORARIO", "employee_code": emp.employee_code, "effective_date": "2026-09-01",
            "justification": "x", "values": {"motivo": "Otro", "horario": "L-V 09:00-18:00 60"}}
    folio = api.post(PA + "/", {**base, "submit": True}, format="json").json()["action"]["folio"]
    api.force_login(hr_user)
    r = api.post(f"{PA}/{folio}/sign/", {"decision": "REJECTED", "comment": "No cubre la operación"}, format="json")
    assert r.json()["action"]["status"] == "REJECTED"
    assert ScheduleAssignment.objects.filter(employee=emp).count() == 1

    draft = api.post(PA + "/", base, format="json").json()["action"]
    assert draft["status"] == "DRAFT" and draft["can_edit"]
    assert api.patch(f"{PA}/{draft['folio']}/", {"justification": "Corregida"}, format="json").status_code == 200
    assert api.post(f"{PA}/{draft['folio']}/cancel/", {}, format="json").status_code == 400
    assert api.post(f"{PA}/{draft['folio']}/cancel/", {"reason": "Duplicada"}, format="json").json()["action"]["status"] == "CANCELLED"


def test_schedule_action_requires_initial_and_respects_closed_cutoffs(api, hr_user, make_employee):
    api.force_login(hr_user)
    legacy = make_employee("SV", hire_date=date(2026, 3, 1))  # creado sin el flujo de alta (p. ej. antes de la Fase 9)
    assert legacy.employee_code in [e["employee_code"] for e in api.get(f"{PA}/missing-initial/").json()["results"]]
    body = {"action_type": "AP_CAMBIO_HORARIO", "employee_code": legacy.employee_code, "effective_date": "2026-10-01",
            "justification": "x", "values": {"motivo": "Otro", "horario": "L-V 08:00-17:00 60"}}
    assert any(e["code"] == "initial_missing" for e in api.post(f"{PA}/validate/", body, format="json").json()["errors"])
    # Se regulariza con su Primera AP (fecha efectiva = ingreso)
    r = api.post(PA + "/", {"action_type": "AP_HORARIO_INICIAL", "employee_code": legacy.employee_code, "effective_date": "2026-03-01",
                            "justification": "Regularización", "values": {"horario": "L-V 08:00-17:00 60"}, "submit": True}, format="json")
    assert r.status_code == 201 and r.json()["action"]["status"] == "APPROVED", r.json()
    assert legacy.employee_code not in [e["employee_code"] for e in api.get(f"{PA}/missing-initial/").json()["results"]]

    period = PayPeriod.objects.get(cycle__code="SV_MENSUAL", code="2026-09")
    period.status = "CLOSED"
    period.save()
    blocked = api.post(f"{PA}/validate/", {**body, "effective_date": "2026-09-15"}, format="json").json()
    assert any(e["code"] == "closed_period" for e in blocked["errors"])


# ------------------------------------------------------------------ ajuste salarial (efecto SALARY)
def test_salary_adjustment_chain_and_due_application(api, hr_user, admin_user, wfm_user):
    api.force_login(hr_user)
    emp = hire(api)
    future = timezone.localdate() + timedelta(days=10)
    body = {"action_type": "AP_AJUSTE_SALARIAL", "employee_code": emp.employee_code, "justification": "Mérito anual",
            "values": {"tipo_ajuste": "Mérito", "new_base_salary": "950.00"}, "submit": True}
    now = api.post(PA + "/", {**body, "effective_date": "2026-10-01"}, format="json").json()["action"]
    later = api.post(PA + "/", {**body, "effective_date": future.isoformat(), "values": {"tipo_ajuste": "Promoción", "new_base_salary": "1200"}},
                     format="json").json()["action"]
    assert now["status"] == "PENDING" and now["next_step"]["role"] == "ADMIN"
    api.force_login(wfm_user)
    assert api.get(f"{PA}/{now['folio']}/").status_code == 404  # tipo no visible sin permisos de planilla
    api.force_login(admin_user)
    for folio in (now["folio"], later["folio"]):
        assert api.post(f"{PA}/{folio}/sign/", {"decision": "APPROVED"}, format="json").json()["action"]["status"] == "APPROVED"
    emp.refresh_from_db()
    assert emp.base_salary == Decimal("950.00")
    assert PersonnelAction.objects.get(folio=later["folio"]).applied_at is None
    services.apply_due_actions(today=future)
    emp.refresh_from_db()
    assert emp.base_salary == Decimal("1200.00")
    call_command("apply_due_personnel_actions")  # idempotente


def test_distinct_signers_option(api, admin_user):
    api.force_login(admin_user)
    t = ActionType.objects.get(code="AP_AJUSTE_SALARIAL")
    t.require_distinct_signers = True
    t.save()
    emp = hire(api)
    a = api.post(PA + "/", {"action_type": "AP_AJUSTE_SALARIAL", "employee_code": emp.employee_code, "effective_date": "2026-10-01",
                            "justification": "x", "values": {"tipo_ajuste": "Otro", "new_base_salary": "900"}, "submit": True}, format="json").json()["action"]
    assert a["steps_signed"] == 1  # el Administrador firmó el paso de RRHH al enviar
    r = api.post(f"{PA}/{a['folio']}/sign/", {"decision": "APPROVED"}, format="json")
    assert r.status_code == 400 and "firmantes distintos" in r.json()["detail"]


# ------------------------------------------------------------------ integridad en SQL Server
@pytest.mark.parametrize("what, number", [("signature", "50050"), ("value", "50051"), ("content", "50052")])
def test_sql_server_protects_signatures_and_sealed_content(api, hr_user, what, number):
    # Un error de trigger anula la transacción completa en SQL Server: un caso por prueba.
    api.force_login(hr_user)
    action = PersonnelAction.objects.get(employee=hire(api))
    with pytest.raises(DatabaseError) as exc, transaction.atomic():
        if what == "signature":
            ActionSignature.objects.filter(action=action).update(comment="alterada")
        elif what == "value":
            ActionValue.objects.filter(action=action).update(value_text="x")
        else:
            PersonnelAction.objects.filter(pk=action.pk).update(justification="otra")
    assert number in str(exc.value)


def test_reporting_views(api, hr_user):
    api.force_login(hr_user)
    emp = hire(api)
    with connection.cursor() as cursor:
        for view in ("vw_PersonnelAction", "vw_SchScheduleAssignment", "vw_SchScheduleDay"):
            cursor.execute(f"SELECT TOP 1 * FROM dbo.{view}")
        cursor.execute("SELECT DayKey, DayMinutes, NightMinutes FROM dbo.vw_SchScheduleDay WHERE EmployeeCode = %s AND DayKey = 'mon'", [emp.employee_code])
        assert tuple(cursor.fetchone()) == ("mon", 480, 0)


def test_preview_and_permissions(api, employee_user, wfm_user):
    api.force_login(employee_user)
    assert api.get(f"{PA}/").status_code == 403
    api.force_login(wfm_user)
    r = api.post(f"{PA}/schedule-preview/", {"schedule": "L-V 22:00-06:00 30", "country": "SV", "effective_date": "2026-10-05"}, format="json").json()
    mon = r["summary"]["days"][0]
    assert (mon["day_minutes"], mon["night_minutes"]) == (0, 450) and r["night_rule"]["start"] == "19:00"
    assert r["by_occurrence_date"][1]["minutes"] == 450  # martes: 6 h del lunes (337) + 2 h del martes (113)
