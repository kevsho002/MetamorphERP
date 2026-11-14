"""Fase 25 — Bloqueo y desbloqueo de cuentas (intentos fallidos y decisión administrativa)."""

from __future__ import annotations

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.system import policy, sessions
from apps.system.audit import Category, record


def register_failure(username: str, request=None) -> CustomUser | None:
    """Suma un intento fallido; al llegar al límite de la política bloquea la cuenta y cierra sus sesiones."""
    if not username:
        return None
    user = CustomUser.objects.filter(username__iexact=username).first()
    if user is None:
        return None
    now = timezone.now()
    CustomUser.objects.filter(pk=user.pk).update(failed_login_count=F("failed_login_count") + 1, last_failed_login_at=now)
    user.refresh_from_db(fields=["failed_login_count", "locked_at", "is_active"])
    limit = policy.current().max_failed_logins
    if limit and user.locked_at is None and user.is_active and user.failed_login_count >= limit:
        lock(user, f"{user.failed_login_count} intentos fallidos consecutivos.", request=request, automatic=True)
    return user


def register_success(user: CustomUser) -> None:
    if user.failed_login_count:
        CustomUser.objects.filter(pk=user.pk).update(failed_login_count=0)
        user.failed_login_count = 0


@transaction.atomic
def lock(user: CustomUser, reason: str, *, actor=None, request=None, automatic: bool = False) -> bool:
    if user.locked_at is not None:
        return False
    reason = (reason or "").strip()[:200] or "Bloqueo administrativo."
    user.locked_at, user.lock_reason = timezone.now(), reason
    CustomUser.objects.filter(pk=user.pk).update(locked_at=user.locked_at, lock_reason=reason, updated_at=user.locked_at)
    sessions.end_user_sessions(user, sessions.Reason.DEACTIVATED)
    record("account_locked", Category.USERS if not automatic else Category.AUTH,
           f"Cuenta «{user.username}» bloqueada: {reason}", request=request, actor=actor,
           actor_username="" if actor else "system", target=user, success=not automatic,
           details={"automatic": automatic, "failed_logins": user.failed_login_count})
    return True


@transaction.atomic
def unlock(user: CustomUser, *, actor=None, request=None) -> bool:
    if user.locked_at is None and not user.failed_login_count:
        return False
    was = user.lock_reason
    user.locked_at, user.lock_reason, user.failed_login_count = None, "", 0
    CustomUser.objects.filter(pk=user.pk).update(locked_at=None, lock_reason="", failed_login_count=0, updated_at=timezone.now())
    record("account_unlocked", Category.USERS, f"Cuenta «{user.username}» desbloqueada.", request=request, actor=actor,
           target=user, details={"previous_reason": was})
    return True
