"""Seguimiento y cierre de sesiones (control del cliente web).

Cerrar una sesión = borrar su fila de django_session (la cookie del navegador
deja de ser válida en el siguiente request) y marcar el UserSession con el motivo.
"""

from __future__ import annotations

from django.contrib.sessions.models import Session
from django.utils import timezone

from apps.system import policy
from apps.system.audit import client_ip, user_agent
from apps.system.models import UserSession

# Marcas guardadas en la sesión de Django (segundos epoch).
LOGIN_AT = "_mm_login_at"
LAST_SEEN = "_mm_last_seen"

Reason = UserSession.EndReason


def _end(queryset, reason: str) -> int:
    rows = list(queryset.filter(ended_at__isnull=True))
    if not rows:
        return 0
    Session.objects.filter(session_key__in=[r.session_key for r in rows]).delete()
    UserSession.objects.filter(pk__in=[r.pk for r in rows]).update(ended_at=timezone.now(), end_reason=reason)
    return len(rows)


def end_sessions(sessions, reason: str) -> int:
    """Cierra las sesiones indicadas (queryset de UserSession)."""
    return _end(sessions, reason)


def end_user_sessions(user, reason: str, *, except_key: str | None = None) -> int:
    qs = UserSession.objects.filter(user=user)
    if except_key:
        qs = qs.exclude(session_key=except_key)
    return _end(qs, reason)


def mark_ended(session_key: str | None, reason: str) -> None:
    """Marca como cerrada la sesión actual (Django se encarga de borrarla con logout())."""
    if session_key:
        UserSession.objects.filter(session_key=session_key, ended_at__isnull=True).update(
            ended_at=timezone.now(), end_reason=reason
        )


def sweep_expired(user=None) -> int:
    """Sesiones cuya cookie ya venció o se borró (navegador cerrado) -> EXPIRED."""
    qs = UserSession.objects.filter(ended_at__isnull=True)
    if user is not None:
        qs = qs.filter(user=user)
    keys = list(qs.values_list("session_key", flat=True))
    if not keys:
        return 0
    alive = set(
        Session.objects.filter(session_key__in=keys, expire_date__gt=timezone.now()).values_list("session_key", flat=True)
    )
    dead = [k for k in keys if k not in alive]
    if dead:
        qs.filter(session_key__in=dead).update(ended_at=timezone.now(), end_reason=Reason.EXPIRED)
    return len(dead)


def start(request, user) -> UserSession | None:
    """Registra la sesión recién iniciada y aplica el límite de sesiones simultáneas."""
    session = getattr(request, "session", None)
    if session is None:
        return None
    if session.session_key is None:
        session.save()
    now = int(timezone.now().timestamp())
    session[LOGIN_AT] = now
    session[LAST_SEEN] = now
    sweep_expired(user)
    record = UserSession.objects.create(
        user=user, session_key=session.session_key, ip_address=client_ip(request), user_agent=user_agent(request)
    )
    limit = policy.current().max_sessions_per_user
    if limit:
        others = UserSession.objects.filter(user=user, ended_at__isnull=True).exclude(pk=record.pk).order_by("started_at")
        excess = others.count() + 1 - limit
        if excess > 0:
            _end(UserSession.objects.filter(pk__in=list(others.values_list("pk", flat=True)[:excess])), Reason.REPLACED)
    return record


def touch(session_key: str | None) -> None:
    if session_key:
        UserSession.objects.filter(session_key=session_key, ended_at__isnull=True).update(last_activity=timezone.now())


def rekey(old_key: str | None, new_key: str | None) -> None:
    """La sesión cambió de clave (p. ej. update_session_auth_hash): se conserva su seguimiento."""
    if old_key and new_key and old_key != new_key:
        UserSession.objects.filter(session_key=old_key, ended_at__isnull=True).update(session_key=new_key)
