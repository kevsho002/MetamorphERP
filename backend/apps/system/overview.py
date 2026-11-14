"""Fase 25 — Estado del sistema: control de sesiones y usuarios en tiempo real (panel del Administrador)."""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.accounts.roles import Role
from apps.system import policy, sessions
from apps.system.models import AuditEvent, UserSession


def _agent(ua: str) -> str:
    """Navegador y sistema en pocas palabras (sin exponer la cadena completa)."""
    ua = ua or ""
    browser = next((b for k, b in (("Edg/", "Edge"), ("OPR/", "Opera"), ("Chrome/", "Chrome"), ("Firefox/", "Firefox"),
                                    ("Safari/", "Safari")) if k in ua), "Otro")
    system = next((s for k, s in (("Windows", "Windows"), ("Android", "Android"), ("iPhone", "iOS"), ("Mac OS", "macOS"),
                                   ("Linux", "Linux")) if k in ua), "")
    return f"{browser}{' · ' + system if system else ''}" if ua else "—"


def snapshot(request=None) -> dict:
    sessions.sweep_expired()
    now = timezone.now()
    s = policy.current()
    users = CustomUser.objects.all()
    counts = users.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(is_active=True, locked_at__isnull=True)),
        inactive=Count("id", filter=Q(is_active=False)),
        locked=Count("id", filter=Q(locked_at__isnull=False)),
        must_change_password=Count("id", filter=Q(must_change_password=True, is_active=True)),
        never_logged=Count("id", filter=Q(last_login__isnull=True, is_active=True)),
        superusers=Count("id", filter=Q(is_superuser=True)),
        with_failures=Count("id", filter=Q(failed_login_count__gt=0, locked_at__isnull=True)),
    )
    by_role = dict(users.filter(is_active=True).values_list("role").annotate(n=Count("id")))
    active = list(UserSession.objects.filter(ended_at__isnull=True).select_related("user").order_by("-last_activity")[:200])
    current_key = getattr(getattr(request, "session", None), "session_key", None)
    idle_limit = s.idle_timeout_minutes * 60
    day_ago = now - timedelta(hours=24)
    today = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    auth = AuditEvent.objects.filter(category=AuditEvent.Category.AUTH, occurred_at__gte=day_ago)
    return {
        "generated_at": now,
        "users": {**counts, "connected": len({x.user_id for x in active}),
                  "by_role": [{"role": v, "label": label, "count": by_role.get(v, 0)} for v, label in Role.choices]},
        "sessions": {
            "active": len(active),
            "started_today": UserSession.objects.filter(started_at__gte=today).count(),
            "ended_today": UserSession.objects.filter(ended_at__gte=today).count(),
            "failed_logins_24h": auth.filter(action="login_failed").count(),
            "locks_24h": AuditEvent.objects.filter(action="account_locked", occurred_at__gte=day_ago).count(),
            "end_reasons_today": [{"reason": r or "—", "label": dict(UserSession.EndReason.choices).get(r, r), "count": n}
                                  for r, n in UserSession.objects.filter(ended_at__gte=today).values_list("end_reason")
                                  .annotate(n=Count("id")).order_by("-n")],
            "rows": [{
                "id": x.pk, "username": x.user.username, "name": x.user.get_full_name(), "role": x.user.effective_role,
                "ip": x.ip_address, "agent": _agent(x.user_agent), "started_at": x.started_at, "last_activity": x.last_activity,
                "idle_seconds": max(0, int((now - x.last_activity).total_seconds())),
                "idle_warning": idle_limit > 0 and (now - x.last_activity).total_seconds() > idle_limit * 0.75,
                "current": bool(current_key and x.session_key == current_key),
            } for x in active],
        },
        "locked": [{"id": u.pk, "username": u.username, "name": u.get_full_name(), "locked_at": u.locked_at,
                    "reason": u.lock_reason, "failed_login_count": u.failed_login_count}
                   for u in users.filter(locked_at__isnull=False).order_by("-locked_at")[:50]],
        "pending_password": [{"id": u.pk, "username": u.username, "name": u.get_full_name(), "last_login": u.last_login}
                             for u in users.filter(must_change_password=True, is_active=True).order_by("username")[:50]],
        "policy": {"idle_timeout_minutes": s.idle_timeout_minutes, "max_session_hours": s.max_session_hours,
                   "max_sessions_per_user": s.max_sessions_per_user, "max_failed_logins": s.max_failed_logins,
                   "maintenance_mode": s.maintenance_mode},
        "admin_urls": {"users": "/admin/accounts/customuser/", "sessions": "/admin/system/usersession/?estado=activa",
                       "settings": "/admin/system/platformsettings/", "locked": "/admin/accounts/customuser/?acceso=bloqueada"},
    }
