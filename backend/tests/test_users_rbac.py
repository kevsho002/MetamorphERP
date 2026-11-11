"""CRUD de usuarios bajo RBAC: matriz de roles, escalamiento de privilegios y reseteo seguro."""

from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.accounts import services
from apps.accounts.models import CustomUser
from tests.conftest import STRONG_PASSWORD

pytestmark = pytest.mark.django_db

USERS = "/api/v1/users/"


def detail(user, suffix=""):
    return f"{USERS}{user.pk}/{suffix}"


# ------------------------------------------------------------------ acceso
@pytest.mark.parametrize("role_fixture", ["wfm_user", "employee_user"])
def test_non_admin_roles_cannot_manage_users(request, as_user, role_fixture, admin_user):
    client = as_user(request.getfixturevalue(role_fixture))
    assert client.get(USERS).status_code == 403
    assert client.get(detail(admin_user)).status_code == 403
    assert client.post(USERS, {"username": "x"}, format="json").status_code == 403
    assert client.post(detail(admin_user, "reset-password/")).status_code == 403
    assert client.get("/api/v1/roles/").status_code == 403


def test_anonymous_gets_401(api):
    assert api.get(USERS).status_code == 401


@pytest.mark.parametrize("role_fixture", ["admin_user", "hr_user"])
def test_admin_and_hr_can_list_and_filter(request, as_user, role_fixture, employee_user, wfm_user):
    client = as_user(request.getfixturevalue(role_fixture))
    body = client.get(USERS).json()
    assert body["count"] >= 3
    only_wfm = client.get(USERS, {"role": "wfm"}).json()["results"]
    assert [u["username"] for u in only_wfm] == [wfm_user.username]
    by_code = client.get(USERS, {"search": employee_user.employee_id}).json()["results"]
    assert [u["username"] for u in by_code] == [employee_user.username]


def test_roles_catalog(as_user, hr_user):
    roles = {r["code"]: r for r in as_user(hr_user).get("/api/v1/roles/").json()}
    assert set(roles) == {"ADMIN", "HR", "WFM", "EMPLOYEE"}
    assert roles["ADMIN"]["assignable"] is False
    assert roles["EMPLOYEE"]["assignable"] is True


# ------------------------------------------------------------------ alta
def test_admin_creates_user_linked_to_employee(as_user, admin_user, make_employee, cost_center):
    employee = make_employee("SV")
    client = as_user(admin_user)
    r = client.post(
        USERS,
        {
            "username": "ana.lopez",
            "role": "WFM",
            "employee_code": employee.employee_code.lower(),  # se normaliza a mayúsculas
            "cost_center_id": cost_center("SV-OPS").cost_center_id,
        },
        format="json",
    )
    assert r.status_code == 201, r.json()
    body = r.json()
    assert r["Cache-Control"] == "no-store"
    assert body["employee_code"] == employee.employee_code
    assert body["employee_country"] == "SV"
    assert body["cost_center"]["code"] == "SV-OPS"
    assert body["first_name"] == employee.first_name  # tomado del expediente
    assert body["email"] == employee.work_email
    assert body["must_change_password"] is True

    temp = body["temporary_password"]
    assert len(temp) == services.TEMP_PASSWORD_LENGTH
    user = CustomUser.objects.get(username="ana.lopez")
    assert user.check_password(temp)
    assert "temporary_password" not in client.get(detail(user)).json()


def test_new_user_must_change_temporary_password_before_using_api(as_user, admin_user, make_employee):
    employee = make_employee()
    temp = as_user(admin_user).post(
        USERS, {"username": "nuevo.rrhh", "role": "HR", "employee_code": employee.employee_code}, format="json"
    ).json()["temporary_password"]

    client = APIClient()
    r = client.post("/api/v1/auth/login/", {"username": "nuevo.rrhh", "password": temp}, format="json")
    assert r.status_code == 200
    r = client.get(USERS)
    assert r.status_code == 403
    assert r.json()["detail"] == "Debe cambiar su contraseña antes de continuar."
    assert client.get("/api/v1/auth/me/").json()["must_change_password"] is True

    r = client.post(
        "/api/v1/auth/password/change/", {"current_password": temp, "new_password": "MiClaveNueva!2026"}, format="json"
    )
    assert r.status_code == 200
    assert client.get(USERS).status_code == 200


@pytest.mark.parametrize(
    "payload, field",
    [
        ({"username": "sin.empleado", "role": "EMPLOYEE"}, "employee_code"),
        ({"username": "codigo.malo", "role": "EMPLOYEE", "employee_code": "SV-2026-000001-8"}, "employee_code"),
        ({"username": "no.existe", "role": "EMPLOYEE", "employee_code": "SV-2099-000001-3"}, "employee_code"),
        ({"username": "rol.raro", "role": "ROOT"}, "role"),
    ],
)
def test_create_validation_errors(as_user, admin_user, payload, field):
    r = as_user(admin_user).post(USERS, payload, format="json")
    assert r.status_code == 400
    assert field in r.json()


def test_employee_cannot_have_two_accounts(as_user, admin_user, employee_user):
    r = as_user(admin_user).post(
        USERS, {"username": "duplicado", "role": "EMPLOYEE", "employee_code": employee_user.employee_id}, format="json"
    )
    assert r.status_code == 400
    assert "ya tiene una cuenta" in r.json()["employee_code"][0]


def test_terminated_employee_cannot_get_account(as_user, admin_user, make_employee):
    employee = make_employee(employment_status="TERMINATED", termination_date=date(2026, 6, 30))
    r = as_user(admin_user).post(
        USERS, {"username": "retirado", "role": "EMPLOYEE", "employee_code": employee.employee_code}, format="json"
    )
    assert r.status_code == 400


def test_cost_center_must_match_employee_country(as_user, admin_user, make_employee, cost_center):
    employee = make_employee("GT")
    r = as_user(admin_user).post(
        USERS,
        {
            "username": "pais.cruzado",
            "role": "EMPLOYEE",
            "employee_code": employee.employee_code,
            "cost_center_id": cost_center("SV-ADM").cost_center_id,
        },
        format="json",
    )
    assert r.status_code == 400
    assert "cost_center_id" in r.json()


def test_admin_account_may_exist_without_employee(as_user, admin_user):
    r = as_user(admin_user).post(USERS, {"username": "svc.integracion", "role": "ADMIN"}, format="json")
    assert r.status_code == 201
    assert r.json()["employee_code"] is None


def test_hr_cannot_create_admin(as_user, hr_user):
    r = as_user(hr_user).post(USERS, {"username": "escalada", "role": "ADMIN"}, format="json")
    assert r.status_code == 403
    assert not CustomUser.objects.filter(username="escalada").exists()


def test_duplicate_username_rejected(as_user, admin_user):
    r = as_user(admin_user).post(USERS, {"username": admin_user.username, "role": "ADMIN"}, format="json")
    assert r.status_code == 400
    assert "username" in r.json()


# ------------------------------------------------------------------ edición
def test_hr_updates_operational_user(as_user, hr_user, employee_user, cost_center):
    r = as_user(hr_user).patch(
        detail(employee_user),
        {"email": "nuevo@metamorph.test", "cost_center_id": cost_center("SV-RRHH").cost_center_id},
        format="json",
    )
    assert r.status_code == 200, r.json()
    assert r.json()["email"] == "nuevo@metamorph.test"
    assert r.json()["cost_center"]["code"] == "SV-RRHH"


def test_update_ignores_role_and_status(as_user, admin_user, employee_user):
    r = as_user(admin_user).patch(detail(employee_user), {"role": "ADMIN", "is_active": False}, format="json")
    assert r.status_code == 200
    employee_user.refresh_from_db()
    assert employee_user.role == "EMPLOYEE" and employee_user.is_active


def test_hr_cannot_modify_admin_accounts(as_user, hr_user, admin_user):
    client = as_user(hr_user)
    assert client.get(detail(admin_user)).status_code == 200  # lectura permitida
    assert client.patch(detail(admin_user), {"first_name": "X"}, format="json").status_code == 403
    assert client.post(detail(admin_user, "reset-password/")).status_code == 403
    assert client.post(detail(admin_user, "deactivate/")).status_code == 403
    assert client.post(detail(admin_user, "role/"), {"role": "EMPLOYEE"}, format="json").status_code == 403


def test_only_superuser_manages_superuser(as_user, admin_user, make_user):
    root = make_user("root.test", "ADMIN", is_superuser=True)
    assert as_user(admin_user).post(detail(root, "reset-password/")).status_code == 403


def test_unlinking_employee_from_employee_role_is_rejected(as_user, admin_user, employee_user):
    r = as_user(admin_user).patch(detail(employee_user), {"employee_code": None}, format="json")
    assert r.status_code == 400


# ------------------------------------------------------------------ roles
def test_admin_assigns_role(as_user, admin_user, employee_user):
    r = as_user(admin_user).post(detail(employee_user, "role/"), {"role": "WFM"}, format="json")
    assert r.status_code == 200
    assert r.json()["role"] == "WFM"


def test_promoting_to_admin_grants_django_admin_access(as_user, admin_user, employee_user):
    as_user(admin_user).post(detail(employee_user, "role/"), {"role": "ADMIN"}, format="json")
    employee_user.refresh_from_db()
    assert employee_user.is_staff is True


def test_hr_cannot_grant_admin(as_user, hr_user, employee_user):
    r = as_user(hr_user).post(detail(employee_user, "role/"), {"role": "ADMIN"}, format="json")
    assert r.status_code == 403
    employee_user.refresh_from_db()
    assert employee_user.role == "EMPLOYEE"


def test_role_requiring_employee_needs_link(as_user, admin_user, make_user):
    technical = make_user("svc.tecnica", "ADMIN")
    r = as_user(admin_user).post(detail(technical, "role/"), {"role": "HR"}, format="json")
    assert r.status_code == 400


def test_cannot_change_own_role(as_user, admin_user):
    r = as_user(admin_user).post(detail(admin_user, "role/"), {"role": "EMPLOYEE"}, format="json")
    assert r.status_code == 403


def test_admin_can_demote_another_admin(as_user, admin_user, make_user):
    other = make_user("admin.dos", "ADMIN", with_employee=True)
    assert as_user(admin_user).post(detail(other, "role/"), {"role": "HR"}, format="json").status_code == 200


def test_service_never_leaves_system_without_active_admin(make_user, hr_user):
    """Defensa en profundidad (p.ej. llamadas desde otros servicios/comandos)."""
    only_admin = make_user("unico.admin", "ADMIN", with_employee=True)
    with pytest.raises(services.Conflict):
        services.set_active(hr_user, only_admin, active=False)
    with pytest.raises(services.Conflict):
        services.assign_role(hr_user.__class__(pk=-1, role="ADMIN", is_superuser=True), only_admin, "HR")
    only_admin.refresh_from_db()
    assert only_admin.is_active and only_admin.role == "ADMIN"


# ------------------------------------------------------------------ contraseñas
def test_reset_password_flow(as_user, hr_user, employee_user):
    old_session = APIClient()
    old_session.force_login(employee_user)
    assert old_session.get("/api/v1/auth/me/").status_code == 200

    r = as_user(hr_user).post(detail(employee_user, "reset-password/"))
    assert r.status_code == 200
    assert r["Cache-Control"] == "no-store"
    temp = r.json()["temporary_password"]
    assert r.json()["must_change_password"] is True

    employee_user.refresh_from_db()
    assert not employee_user.check_password(STRONG_PASSWORD)
    assert employee_user.check_password(temp)
    # El cambio de hash invalida las sesiones existentes del usuario
    assert old_session.get("/api/v1/auth/me/").status_code == 401


def test_temporary_passwords_are_unique_and_strong():
    passwords = {services.generate_temporary_password() for _ in range(50)}
    assert len(passwords) == 50
    for p in passwords:
        assert any(c.isupper() for c in p) and any(c.islower() for c in p) and any(c.isdigit() for c in p)


def test_cannot_reset_own_password_via_admin_endpoint(as_user, admin_user):
    assert as_user(admin_user).post(detail(admin_user, "reset-password/")).status_code == 403


def test_reset_password_is_post_only(as_user, admin_user, employee_user):
    # Método no mapeado => acción desconocida => denegado por defecto (deny by default)
    assert as_user(admin_user).get(detail(employee_user, "reset-password/")).status_code in (403, 405)
    employee_user.refresh_from_db()
    assert employee_user.check_password(STRONG_PASSWORD)


# ------------------------------------------------------------------ baja lógica
def test_delete_is_soft_and_blocks_login(as_user, admin_user, employee_user):
    client = as_user(admin_user)
    assert client.delete(detail(employee_user)).status_code == 204
    employee_user.refresh_from_db()
    assert employee_user.is_active is False
    assert CustomUser.objects.filter(pk=employee_user.pk).exists()

    login = APIClient().post(
        "/api/v1/auth/login/", {"username": employee_user.username, "password": STRONG_PASSWORD}, format="json"
    )
    assert login.status_code == 400

    assert client.post(detail(employee_user, "activate/")).status_code == 200
    employee_user.refresh_from_db()
    assert employee_user.is_active is True


def test_cannot_deactivate_self(as_user, admin_user):
    assert as_user(admin_user).post(detail(admin_user, "deactivate/")).status_code == 403
