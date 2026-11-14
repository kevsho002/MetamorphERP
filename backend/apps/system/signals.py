"""Inicio/cierre de sesión y fallos de autenticación -> sesiones rastreadas + auditoría.

Se usan las señales de Django para cubrir por igual el login del SPA y el del /admin/.
"""

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from apps.system import sessions
from apps.system.audit import Category, record


@receiver(user_logged_in, dispatch_uid="system_user_logged_in")
def _on_login(sender, request, user, **kwargs):
    if request is None:
        return
    sessions.start(request, user)
    from apps.accounts import lockout

    lockout.register_success(user)  # Fase 25: reinicia el contador de intentos fallidos
    via = "admin" if request.path.startswith("/admin/") else "web"
    record("login", Category.AUTH, f"Inicio de sesión ({via}).", request=request, actor=user, target=user, details={"via": via})


@receiver(user_logged_out, dispatch_uid="system_user_logged_out")
def _on_logout(sender, request, user, **kwargs):
    if request is None or user is None:
        return
    sessions.mark_ended(getattr(request.session, "session_key", None), sessions.Reason.LOGOUT)
    if getattr(request, "_mm_forced_logout", False):
        return  # cierre por política (inactividad / duración): ya auditado por el middleware
    record("logout", Category.AUTH, "Cierre de sesión.", request=request, actor=user, target=user)


@receiver(user_login_failed, dispatch_uid="system_user_login_failed")
def _on_login_failed(sender, credentials, request=None, **kwargs):
    username = str(credentials.get("username", ""))[:150]  # Django ya enmascara la contraseña
    record(
        "login_failed",
        Category.AUTH,
        "Intento de inicio de sesión fallido (usuario o contraseña incorrectos, o cuenta inactiva).",
        request=request,
        actor_username=username,
        target_type="user",
        target_id=username[:64],
        success=False,
    )
    from apps.accounts import lockout

    lockout.register_failure(username, request=request)  # Fase 25: bloqueo tras N intentos fallidos
