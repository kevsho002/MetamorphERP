"""Aplica los parámetros de sesión y el modo mantenimiento en cada request autenticado.

Va DESPUÉS de AuthenticationMiddleware. Las respuestas de la API son JSON con un
`code` que el SPA interpreta (session_expired -> pantalla de login con aviso;
maintenance -> pantalla de mantenimiento).
"""

from __future__ import annotations

import time

from django.contrib.auth import logout
from django.http import JsonResponse

from apps.accounts.roles import Role
from apps.system import policy, sessions
from apps.system.audit import Category, record

API_PREFIX = "/api/"
CLIENT_CONFIG_PATH = "/api/v1/system/client-config/"
# Consultas que no cuentan como actividad del usuario (no prolongan la sesión).
PASSIVE_PATHS = {CLIENT_CONFIG_PATH}
# Disponibles durante el mantenimiento para cualquier usuario (ver estado, cerrar sesión).
MAINTENANCE_ALLOWED_PREFIXES = ("/api/v1/auth/", CLIENT_CONFIG_PATH, "/api/v1/health")
TOUCH_EVERY_SECONDS = 30

_MESSAGES = {
    sessions.Reason.IDLE: "Su sesión se cerró por inactividad. Inicie sesión de nuevo.",
    sessions.Reason.MAX_AGE: "Su sesión alcanzó la duración máxima permitida. Inicie sesión de nuevo.",
}


class SessionPolicyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and hasattr(request, "session"):
            response = self._enforce(request, user)
            if response is not None:
                return response
        return self.get_response(request)

    def _enforce(self, request, user):
        settings_obj = policy.current()
        session = request.session
        now = int(time.time())
        login_at = session.get(sessions.LOGIN_AT)
        last_seen = session.get(sessions.LAST_SEEN)
        if login_at is None:  # sesión anterior a esta política
            session[sessions.LOGIN_AT] = login_at = now

        reason = None
        if last_seen is not None and now - last_seen > settings_obj.idle_timeout_minutes * 60:
            reason = sessions.Reason.IDLE
        elif now - login_at > settings_obj.max_session_hours * 3600:
            reason = sessions.Reason.MAX_AGE
        if reason is not None:
            return self._expire(request, user, reason)

        if request.path not in PASSIVE_PATHS and (last_seen is None or now - last_seen >= TOUCH_EVERY_SECONDS):
            session[sessions.LAST_SEEN] = now
            sessions.touch(session.session_key)

        if (
            settings_obj.maintenance_mode
            and user.effective_role != Role.ADMIN
            and request.path.startswith(API_PREFIX)
            and not request.path.startswith(MAINTENANCE_ALLOWED_PREFIXES)
        ):
            return JsonResponse({"detail": settings_obj.maintenance_message, "code": "maintenance"}, status=503)
        return None

    def _expire(self, request, user, reason):
        sessions.mark_ended(request.session.session_key, reason)
        record(
            "session_expired",
            Category.AUTH,
            f"Sesión cerrada automáticamente: {sessions.Reason(reason).label.lower()}.",
            request=request,
            actor=user,
            target=user,
            details={"reason": reason},
        )
        request._mm_forced_logout = True
        logout(request)
        if request.path.startswith(API_PREFIX):
            return JsonResponse({"detail": _MESSAGES[reason], "code": "session_expired"}, status=401)
        return None  # /admin/ y el SPA siguen como anónimos (el admin redirige a su login)
