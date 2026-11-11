"""Registro de auditoría (audit trail).

`record()` escribe un AuditEvent en la MISMA transacción que la operación
auditada (si la operación se revierte, su evento también) y lo replica en el
log `apps.system.audit`. Nunca guarde aquí contraseñas, tokens ni el contenido
de datos sensibles: solo qué se hizo, sobre qué objeto y quién.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.system.models import AuditEvent

logger = logging.getLogger("apps.system.audit")
Category = AuditEvent.Category


def client_ip(request) -> str | None:
    """IP del cliente. Detrás de un proxy, configure el proxy para fijar REMOTE_ADDR (no se confía en X-Forwarded-For)."""
    return (request.META.get("REMOTE_ADDR") or None) if request is not None else None


def user_agent(request) -> str:
    return (request.META.get("HTTP_USER_AGENT") or "")[:300] if request is not None else ""


def _target_of(obj) -> tuple[str, str]:
    if obj is None:
        return "", ""
    code = getattr(obj, "employee_code", None)
    if code and obj.__class__.__name__ == "Employee":
        return "employee", code
    if obj.__class__.__name__ == "CustomUser":
        return "user", str(obj.pk)
    return obj.__class__.__name__.lower(), str(obj.pk)


def record(
    action: str,
    category: str,
    summary: str,
    *,
    request=None,
    actor=None,
    actor_username: str | None = None,
    target=None,
    target_type: str = "",
    target_id: str = "",
    details: dict[str, Any] | None = None,
    success: bool = True,
) -> AuditEvent:
    if actor is None and request is not None:
        candidate = getattr(request, "user", None)
        actor = candidate if getattr(candidate, "is_authenticated", False) else None
    if target is not None:
        target_type, target_id = _target_of(target)
    event = AuditEvent.objects.create(
        category=category,
        action=action,
        success=success,
        actor=actor if getattr(actor, "pk", None) else None,
        actor_username=(actor_username or getattr(actor, "username", "") or "")[:150],
        target_type=target_type[:40],
        target_id=str(target_id)[:64],
        summary=summary[:500],
        details=details or {},
        ip_address=client_ip(request),
        user_agent=user_agent(request),
    )
    logger.log(
        logging.INFO if success else logging.WARNING,
        "%s actor=%s target=%s:%s %s",
        action,
        event.actor_username or "-",
        target_type or "-",
        target_id or "-",
        summary,
    )
    return event
