"""Fase 5: cuenta de usuario Metamorph creada y vinculada desde el alta del empleado."""

import pytest

from apps.accounts.models import CustomUser
from apps.common.models import EmployeeCodeSequence
from apps.hcm.models import Employee
from apps.system.models import AuditEvent, UserSession
from tests.test_employees import EMPLOYEES, sv_row

pytestmark = pytest.mark.django_db


def with_account(**account):
    return sv_row(user_account={"create": True, **account})


def test_create_employee_with_linked_account(api, hr_user):
    api.force_login(hr_user)
    r = api.post(EMPLOYEES, with_account(role="EMPLOYEE"), format="json")
    body = r.json()
    assert r.status_code == 201, body
    assert r["Cache-Control"] == "no-store"  # la contraseña temporal no se guarda en cachés
    account = body["user_account"]
    code = body["employee"]["employee_code"]
    assert account["username"] == "ana.lopez" and account["role"] == "EMPLOYEE" and account["must_change_password"]
    assert len(account["temporary_password"]) == 16
    assert "Se creó la cuenta Metamorph «ana.lopez» (Empleado) vinculada al ID corporativo" in body["feedback"]

    user = CustomUser.objects.get(username="ana.lopez")
    assert user.employee_id == code  # FK al ID corporativo
    assert user.cost_center.code == "SV-OPS" and user.email == "ana.lopez@metamorph.test"
    assert user.first_name == "Ana" and user.check_password(account["temporary_password"])
    assert body["employee"]["has_user_account"] is True and body["employee"]["user_account"]["id"] == user.pk
    actions = set(AuditEvent.objects.values_list("action", flat=True))
    assert {"employee_created", "user_created"} <= actions

    # El nuevo usuario entra con la temporal y debe cambiarla.
    api.logout()
    login = api.post("/api/v1/auth/login/", {"username": "ana.lopez", "password": account["temporary_password"]}, format="json")
    assert login.status_code == 200 and login.json()["must_change_password"] is True
    assert login.json()["employee_code"] == code


def test_validate_previews_account_without_creating_anything(api, hr_user):
    api.force_login(hr_user)
    make = CustomUser.objects.create(username="ana.lopez", role="ADMIN")
    r = api.post(f"{EMPLOYEES}validate/", with_account(), format="json")
    body = r.json()
    assert body["valid"] is True, body
    assert body["user_account_preview"] == {
        "username": "ana.lopez2", "role": "EMPLOYEE", "role_label": "Empleado", "email": "ana.lopez@metamorph.test",
    }
    assert CustomUser.objects.count() == 2 and make.pk  # solo rrhh.test + el existente
    assert not Employee.objects.filter(first_name="Ana").exists()


def test_account_errors_block_the_whole_hire(api, hr_user, countries):
    api.force_login(hr_user)
    CustomUser.objects.create(username="ocupado", role="ADMIN")
    before = list(EmployeeCodeSequence.objects.values_list("last_value", flat=True))
    r = api.post(EMPLOYEES, with_account(username="ocupado"), format="json")
    body = r.json()
    assert r.status_code == 400
    assert {"field": "user_account.username", "code": "username_taken"}.items() <= body["errors"][0].items()
    assert "El usuario «ocupado» ya existe" in body["feedback"]
    assert not Employee.objects.filter(first_name="Ana").exists()
    assert list(EmployeeCodeSequence.objects.values_list("last_value", flat=True)) == before  # sin ID consumido

    r = api.post(EMPLOYEES, with_account(username="con espacio", role="ADMIN"), format="json")
    codes = {e["code"] for e in r.json()["errors"]}
    assert {"invalid_username", "role_not_allowed"} <= codes  # RRHH no otorga Administrador


def test_without_users_permission_no_account_is_offered(api, make_user):
    # Un rol con hcm.manage pero sin users.create no existe hoy; se simula con WFM (sin ambos).
    api.force_login(make_user("wfm.x", "WFM"))
    assert api.post(EMPLOYEES, with_account(), format="json").status_code == 403


def test_create_account_for_existing_employee(api, hr_user, admin_user, make_employee, cost_center):
    employee = make_employee("SV", first_name="José", last_name="Núñez Paz", cost_center=cost_center("SV-OPS"))
    api.force_login(hr_user)
    url = f"{EMPLOYEES}{employee.employee_code}/user-account/"
    r = api.post(url, {"role": "WFM"}, format="json")
    body = r.json()
    assert r.status_code == 201, body
    assert body["user_account"]["username"] == "jose.nunez" and body["user_account"]["role"] == "WFM"
    again = api.post(url, {"role": "WFM"}, format="json")
    assert again.status_code == 400 and again.json()["errors"][0]["code"] == "already_linked"

    retired = make_employee("SV", employment_status="TERMINATED", termination_date=employee.hire_date)
    r = api.post(f"{EMPLOYEES}{retired.employee_code}/user-account/", {}, format="json")
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "terminated"


def test_linked_account_visible_only_to_user_managers(api, hr_user, wfm_user):
    api.force_login(hr_user)
    code = api.post(EMPLOYEES, with_account(), format="json").json()["employee"]["employee_code"]
    assert api.get(f"{EMPLOYEES}{code}/").json()["user_account"]["username"] == "ana.lopez"
    api.force_login(wfm_user)
    data = api.get(f"{EMPLOYEES}{code}/").json()
    assert data["user_account"] is None and data["has_user_account"] is True


def test_termination_deactivates_linked_account_and_closes_sessions(api, hr_user, client):
    api.force_login(hr_user)
    created = api.post(EMPLOYEES, with_account(), format="json").json()
    code, temporary = created["employee"]["employee_code"], created["user_account"]["temporary_password"]
    assert client.post("/api/v1/auth/login/", {"username": "ana.lopez", "password": temporary},
                       content_type="application/json").status_code == 200
    assert UserSession.objects.filter(user__username="ana.lopez", ended_at__isnull=True).count() == 1

    url = f"{EMPLOYEES}{code}/"
    preview = api.post(f"{url}validate/", {"employment_status": "TERMINATED", "termination_date": "2026-06-30"}, format="json").json()
    assert "se desactivará la cuenta de usuario vinculada «ana.lopez»" in preview["feedback"]
    assert CustomUser.objects.get(username="ana.lopez").is_active  # la validación no cambia nada

    r = api.patch(url, {"employment_status": "TERMINATED", "termination_date": "2026-06-30"}, format="json")
    assert r.status_code == 200, r.json()
    assert "Se desactivó la cuenta de usuario vinculada «ana.lopez»" in r.json()["feedback"]
    account = CustomUser.objects.get(username="ana.lopez")
    assert not account.is_active
    session = UserSession.objects.get(user=account)
    assert session.end_reason == "DEACTIVATED"
    assert client.get("/api/v1/auth/me/").status_code in (401, 403)  # la sesión del empleado ya no sirve
    assert AuditEvent.objects.filter(action="user_deactivated", target_id=str(account.pk)).exists()

    history = api.get(f"{url}history/").json()["results"]
    actions = [e["action"] for e in history]
    assert {"employee_created", "user_created", "employee_updated", "user_deactivated"} <= set(actions)
