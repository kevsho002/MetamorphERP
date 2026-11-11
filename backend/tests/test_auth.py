"""Sesión, CSRF y cambio de contraseña."""

import pytest

from tests.conftest import STRONG_PASSWORD

pytestmark = pytest.mark.django_db


def _csrf_login(client, username, password):
    client.get("/api/v1/auth/csrf/")
    token = client.cookies["metamorph_csrftoken"].value
    return client.post(
        "/api/v1/auth/login/", {"username": username, "password": password}, format="json", HTTP_X_CSRFTOKEN=token
    )


def test_me_requires_session(api):
    r = api.get("/api/v1/auth/me/")
    assert r.status_code == 401


def test_login_requires_csrf_token(csrf_api, admin_user):
    r = csrf_api.post("/api/v1/auth/login/", {"username": admin_user.username, "password": STRONG_PASSWORD}, format="json")
    assert r.status_code == 403
    assert r.json()["code"] == "csrf_failed"  # JSON, no la página HTML de Django


def test_login_with_csrf_creates_session_and_me_returns_permissions(csrf_api, hr_user):
    r = _csrf_login(csrf_api, hr_user.username, STRONG_PASSWORD)
    assert r.status_code == 200, r.json()
    assert r["Cache-Control"] == "no-store"
    cookie = csrf_api.cookies["metamorph_sessionid"]
    assert cookie["httponly"]

    me = csrf_api.get("/api/v1/auth/me/").json()
    assert me["username"] == hr_user.username
    assert me["role"] == "HR"
    assert me["employee_code"] == hr_user.employee_id
    assert "users.reset_password" in me["permissions"]
    assert "wfm.manage" not in me["permissions"]


def test_unsafe_request_without_csrf_is_rejected_even_with_session(csrf_api, admin_user):
    _csrf_login(csrf_api, admin_user.username, STRONG_PASSWORD)
    r = csrf_api.post("/api/v1/auth/logout/")  # sin X-CSRFToken
    assert r.status_code == 403


def test_wrong_password_gives_generic_error(api, admin_user):
    r = api.post("/api/v1/auth/login/", {"username": admin_user.username, "password": "incorrecta"}, format="json")
    assert r.status_code == 400
    assert r.json()["detail"] == "Usuario o contraseña incorrectos."
    r = api.post("/api/v1/auth/login/", {"username": "no.existe", "password": "incorrecta"}, format="json")
    assert r.json()["detail"] == "Usuario o contraseña incorrectos."


def test_inactive_user_cannot_login(api, make_user):
    user = make_user("inactivo.test", "ADMIN", is_active=False)
    r = api.post("/api/v1/auth/login/", {"username": user.username, "password": STRONG_PASSWORD}, format="json")
    assert r.status_code == 400


def test_login_is_throttled(api, admin_user, settings):
    for _ in range(10):
        api.post("/api/v1/auth/login/", {"username": admin_user.username, "password": "x"}, format="json")
    r = api.post("/api/v1/auth/login/", {"username": admin_user.username, "password": STRONG_PASSWORD}, format="json")
    assert r.status_code == 429


def test_logout_ends_session(as_user, admin_user):
    client = as_user(admin_user)
    assert client.post("/api/v1/auth/logout/").status_code == 204
    assert client.get("/api/v1/auth/me/").status_code == 401


def test_change_password_validates_current_and_strength(as_user, employee_user):
    client = as_user(employee_user)
    r = client.post(
        "/api/v1/auth/password/change/",
        {"current_password": "mala", "new_password": "OtraClave!2026xyz"},
        format="json",
    )
    assert r.status_code == 400 and "current_password" in r.json()

    r = client.post(
        "/api/v1/auth/password/change/",
        {"current_password": STRONG_PASSWORD, "new_password": "12345678"},
        format="json",
    )
    assert r.status_code == 400 and "new_password" in r.json()

    r = client.post(
        "/api/v1/auth/password/change/",
        {"current_password": STRONG_PASSWORD, "new_password": "OtraClave!2026xyz"},
        format="json",
    )
    assert r.status_code == 200
    assert client.get("/api/v1/auth/me/").status_code == 200  # la sesión actual sigue válida
    employee_user.refresh_from_db()
    assert employee_user.check_password("OtraClave!2026xyz")
    assert employee_user.password_changed_at is not None
