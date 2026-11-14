"""Fase 5: parámetros de sesión, control del cliente web y registro de auditoría."""

import pytest
from django.contrib.sessions.models import Session

from apps.system import sessions
from apps.system.models import AuditEvent, PlatformSettings, UserSession
from tests.conftest import STRONG_PASSWORD

pytestmark = pytest.mark.django_db
LOGIN = "/api/v1/auth/login/"
ME = "/api/v1/auth/me/"
CONFIG = "/api/v1/system/client-config/"


def login(client, user, password=STRONG_PASSWORD):
    return client.post(LOGIN, {"username": user.username, "password": password}, content_type="application/json")


def set_policy(**values):
    PlatformSettings.objects.update_or_create(pk=1, defaults=values)


def age_session(client, **shift):
    """Retrocede las marcas de tiempo de la sesión del cliente (simula el paso del tiempo)."""
    session = client.session
    for key, seconds in shift.items():
        session[{"login": sessions.LOGIN_AT, "seen": sessions.LAST_SEEN}[key]] -= seconds
    session.save()


def test_client_config_is_public_and_reflects_settings(client):
    body = client.get(CONFIG).json()
    assert body["idle_timeout_seconds"] == 1800 and body["maintenance_mode"] is False
    assert body["allowed_image_types"] == ["image/png", "image/jpeg"]
    set_policy(announcement="Cierre de planilla el viernes", announcement_level="warning", idle_timeout_minutes=10)
    body = client.get(CONFIG).json()
    assert body["announcement"] == "Cierre de planilla el viernes" and body["idle_timeout_seconds"] == 600


def test_login_and_logout_are_tracked_and_audited(client, hr_user):
    assert login(client, hr_user, "incorrecta").status_code == 400
    failed = AuditEvent.objects.get(action="login_failed")
    assert failed.success is False and failed.actor_username == hr_user.username and "incorrecta" not in str(failed.details)
    assert login(client, hr_user).status_code == 200
    tracked = UserSession.objects.get(user=hr_user)
    assert tracked.is_active and tracked.session_key == client.session.session_key
    client.post("/api/v1/auth/logout/")
    tracked.refresh_from_db()
    assert tracked.end_reason == "LOGOUT"
    assert list(AuditEvent.objects.filter(category="AUTH").order_by("id").values_list("action", flat=True)) == [
        "login_failed", "login", "logout",
    ]


def test_idle_timeout_closes_the_session(client, hr_user):
    set_policy(idle_timeout_minutes=15)
    login(client, hr_user)
    assert client.get(ME).status_code == 200
    age_session(client, seen=16 * 60)
    r = client.get(ME)
    assert r.status_code == 401 and r.json()["code"] == "session_expired"
    assert "inactividad" in r.json()["detail"]
    assert UserSession.objects.get(user=hr_user).end_reason == "IDLE"
    assert AuditEvent.objects.filter(action="session_expired").exists()
    assert not AuditEvent.objects.filter(action="logout").exists()  # no se confunde con un cierre voluntario
    assert client.get(ME).status_code in (401, 403)


def test_max_session_age_is_enforced_even_with_activity(client, hr_user):
    set_policy(max_session_hours=2)
    login(client, hr_user)
    age_session(client, login=3 * 3600)
    r = client.get(ME)
    assert r.status_code == 401 and "duración máxima" in r.json()["detail"]
    assert UserSession.objects.get(user=hr_user).end_reason == "MAX_AGE"


def test_concurrent_session_limit_closes_the_oldest(client, hr_user, django_user_model):
    from django.test import Client

    set_policy(max_sessions_per_user=1)
    login(client, hr_user)
    second = Client()
    login(second, hr_user)
    assert second.get(ME).status_code == 200
    assert client.get(ME).status_code in (401, 403)
    assert list(UserSession.objects.filter(user=hr_user).order_by("id").values_list("end_reason", flat=True)) == ["REPLACED", ""]


def test_maintenance_mode_only_lets_admins_in(client, hr_user, admin_user):
    login(client, hr_user)
    set_policy(maintenance_mode=True, maintenance_message="Volvemos a las 14:00")
    r = client.get("/api/v1/hcm/employees/")
    assert r.status_code == 503 and r.json() == {"detail": "Volvemos a las 14:00", "code": "maintenance"}
    assert client.get(ME).status_code == 200  # el SPA puede saber quién es y cerrar sesión
    client.post("/api/v1/auth/logout/")
    r = login(client, hr_user)
    assert r.status_code == 503 and r.json()["code"] == "maintenance"
    assert AuditEvent.objects.filter(action="login_blocked").exists()
    assert login(client, admin_user).status_code == 200
    assert client.get("/api/v1/hcm/employees/").status_code == 200


def test_password_change_keeps_current_session_and_closes_others(client, hr_user):
    from django.test import Client

    login(client, hr_user)
    other = Client()
    login(other, hr_user)
    r = client.post(
        "/api/v1/auth/password/change/",
        {"current_password": STRONG_PASSWORD, "new_password": "Otra-Clave!2026-Fuerte"},
        content_type="application/json",
    )
    assert r.status_code == 200
    assert client.get(ME).status_code == 200
    current = UserSession.objects.get(session_key=client.session.session_key)
    assert current.is_active  # el seguimiento sigue a la nueva clave de sesión
    assert UserSession.objects.filter(user=hr_user, end_reason="PASSWORD").count() == 1
    assert other.get(ME).status_code in (401, 403)


@pytest.fixture
def su_client(client, make_user):
    client.force_login(make_user("root.sys", "ADMIN", is_superuser=True))
    return client


def test_admin_settings_singleton_and_audit(su_client):
    r = su_client.get("/admin/system/platformsettings/")
    assert r.status_code == 302 and r["Location"].endswith("/admin/system/platformsettings/1/change/")
    data = {
        "idle_timeout_minutes": 20, "idle_warning_seconds": 60, "max_session_hours": 8, "max_sessions_per_user": 0,
        "maintenance_message": "Mantenimiento", "announcement": "Hola", "announcement_level": "info", "max_document_mb": 5, "max_attachment_mb": 10, "max_failed_logins": 5,
        # Fases 22 y 23: apariencia corporativa y alcance de las AP también se editan aquí
        "brand_palette": "NAVY", "brand_accent": "", "ap_full_scope_roles": '["HR", "WFM"]',
    }
    r = su_client.post("/admin/system/platformsettings/1/change/", data)
    assert r.status_code == 302
    event = AuditEvent.objects.get(action="settings_changed")
    assert event.details["idle_timeout_minutes"] == {"antes": 30, "despues": 20}
    assert PlatformSettings.objects.get().updated_by == "root.sys"
    assert su_client.get("/admin/system/platformsettings/add/").status_code == 403


def test_admin_can_close_sessions_and_audit_is_read_only(su_client, hr_user):
    from django.test import Client

    employee_client = Client()
    login(employee_client, hr_user)
    target = UserSession.objects.get(user=hr_user)
    r = su_client.post(
        "/admin/system/usersession/", {"action": "close_sessions", "_selected_action": [target.pk]}, follow=True
    )
    assert r.status_code == 200
    target.refresh_from_db()
    assert target.end_reason == "ADMIN" and not Session.objects.filter(session_key=target.session_key).exists()
    assert employee_client.get(ME).status_code in (401, 403)
    event = AuditEvent.objects.get(action="sessions_closed")
    assert event.details["usuarios"] == [hr_user.username]

    page = su_client.get(f"/admin/system/auditevent/{event.pk}/change/")
    assert page.status_code == 200 and 'name="summary"' not in page.content.decode()  # solo lectura
    assert su_client.post(f"/admin/system/auditevent/{event.pk}/delete/").status_code == 403
    csv = su_client.post("/admin/system/auditevent/", {"action": "export_csv", "_selected_action": [event.pk]})
    assert csv["Content-Type"].startswith("text/csv") and "sessions_closed" in csv.content.decode("utf-8-sig")
