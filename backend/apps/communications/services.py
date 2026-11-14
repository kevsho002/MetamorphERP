"""Fase 25 — Periódico virtual: publicación, audiencia, acuse de recibo y reportes de cumplimiento (compliance)."""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.accounts.permissions import user_permissions
from apps.accounts.roles import Perm, Role
from apps.communications.models import CRITICAL_CATEGORIES, Announcement, AnnouncementAck, Category, ComplianceSnapshot, Status
from apps.system.audit import Category as AuditCategory
from apps.system.audit import client_ip, record, user_agent

DEFAULT_ACK_DAYS = 7
CATEGORY_LABELS = dict(Category.choices)
URL_CHECK = URLValidator(schemes=["http", "https"])
FROZEN_FIELDS = ("title", "summary", "body", "category", "link_url", "link_label", "requires_ack", "audience_roles")


class CommsError(Exception):
    def __init__(self, message: str, code: str = "invalid", status: int = 400, errors: dict | None = None):
        super().__init__(message)
        self.message, self.code, self.status, self.errors = message, code, status, errors or {}


def can_manage(user) -> bool:
    return Perm.ANNOUNCEMENTS_MANAGE in user_permissions(user)


def can_report(user) -> bool:
    return Perm.ANNOUNCEMENTS_COMPLIANCE in user_permissions(user)


def content_hash(a: Announcement) -> str:
    payload = {"title": a.title, "summary": a.summary, "body": a.body, "category": a.category, "link_url": a.link_url,
               "link_label": a.link_label}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


# ================================================================ audiencia
def in_audience(a: Announcement, user) -> bool:
    roles = a.audience_roles or []
    return not roles or getattr(user, "effective_role", None) in roles


def audience_users(a: Announcement) -> list[CustomUser]:
    """Usuarios ACTIVOS obligados (por su rol) a leer el comunicado. Un superusuario cuenta como Administrador."""
    users = CustomUser.objects.filter(is_active=True).select_related("employee", "cost_center").order_by("username")
    return [u for u in users if in_audience(a, u)]


def _visible(a: Announcement, user, today: date) -> bool:
    if a.status != Status.PUBLISHED or (a.expires_at and a.expires_at < today):
        return False
    return in_audience(a, user)


def feed(user, *, category: str = "", search: str = "", scope: str = "published", pending_only: bool = False) -> list[Announcement]:
    today = timezone.localdate()
    qs = Announcement.objects.select_related("created_by", "published_by").order_by("-pinned", "-published_at", "-id")
    if category:
        qs = qs.filter(category=category)
    if search:
        from django.db.models import Q

        qs = qs.filter(Q(title__icontains=search) | Q(summary__icontains=search) | Q(body__icontains=search))
    if scope in ("draft", "archived", "all") and can_manage(user):
        if scope != "all":
            qs = qs.filter(status=Status.DRAFT if scope == "draft" else Status.ARCHIVED)
        items = list(qs[:300])
    else:
        items = [a for a in qs.filter(status=Status.PUBLISHED)[:300] if _visible(a, user, today)]
    if pending_only:
        acked = set(AnnouncementAck.objects.filter(user=user).values_list("announcement_id", flat=True))
        items = [a for a in items if a.requires_ack and a.pk not in acked]
    return items


def pending_for(user) -> list[Announcement]:
    return feed(user, pending_only=True)


# ================================================================ validación y edición
def _date(value, label: str, errors: dict, key: str):
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        errors[key] = f"{label}: use AAAA-MM-DD."
        return None


def _apply(a: Announcement, data: dict, *, frozen: bool) -> None:
    errors: dict = {}
    if frozen:
        blocked = [f for f in FROZEN_FIELDS if f in data and data[f] != getattr(a, f)]
        if blocked:
            raise CommsError("El comunicado crítico ya fue publicado: su contenido quedó congelado para que cada acuse pruebe "
                             "qué texto se confirmó. Archívelo y publique uno nuevo.", "frozen", 409)
    else:
        if "title" in data:
            a.title = str(data.get("title") or "").strip()[:200]
        if "summary" in data:
            a.summary = str(data.get("summary") or "").strip()[:400]
        if "body" in data:
            a.body = str(data.get("body") or "").replace("\r\n", "\n").strip()[:20000]
        if "category" in data:
            a.category = str(data.get("category") or "").upper()
        if "link_url" in data:
            a.link_url = str(data.get("link_url") or "").strip()[:500]
        if "link_label" in data:
            a.link_label = str(data.get("link_label") or "").strip()[:80]
        if "requires_ack" in data:
            a.requires_ack = bool(data.get("requires_ack"))
        if "audience_roles" in data:
            roles = data.get("audience_roles") or []
            if not isinstance(roles, list) or any(r not in Role.values for r in roles):
                errors["audience_roles"] = "Roles inválidos."
            else:
                a.audience_roles = sorted(set(roles))
    if "pinned" in data:
        a.pinned = bool(data.get("pinned"))
    if "expires_at" in data:
        a.expires_at = _date(data.get("expires_at"), "Visible hasta", errors, "expires_at")
    if "ack_due_date" in data:
        new_due = _date(data.get("ack_due_date"), "Plazo del acuse", errors, "ack_due_date")
        if frozen and a.ack_due_date and (new_due is None or new_due < a.ack_due_date):
            errors["ack_due_date"] = "En un comunicado publicado el plazo solo se puede extender."
        else:
            a.ack_due_date = new_due
    if len(a.title) < 5:
        errors["title"] = "El título debe tener al menos 5 caracteres."
    if len(a.body) < 10:
        errors["body"] = "Escriba el contenido del comunicado (al menos 10 caracteres)."
    if a.category not in Category.values:
        errors["category"] = "Categoría inválida."
    if a.link_url:
        try:
            URL_CHECK(a.link_url)
        except DjangoValidationError:
            errors["link_url"] = "Enlace inválido (http:// o https://)."
    if a.category == Category.FORM and not a.link_url:
        errors["link_url"] = "Un comunicado de Formularios necesita el enlace al formulario."
    if a.category in CRITICAL_CATEGORIES:
        a.requires_ack = True  # obligatorio en seguridad y cambios organizacionales
    if a.expires_at and a.ack_due_date and a.expires_at < a.ack_due_date:
        errors["expires_at"] = "Debe seguir visible al menos hasta el plazo del acuse."
    if errors:
        raise CommsError(next(iter(errors.values())), "invalid", 400, errors)


@transaction.atomic
def create(data: dict, *, user, request=None) -> Announcement:
    a = Announcement(created_by=user, title="", body="")
    _apply(a, data, frozen=False)
    a.save()
    record("announcement_created", AuditCategory.COMMS, f"Comunicado «{a.title}» creado (borrador).", request=request, actor=user,
           target_type="Announcement", target_id=str(a.pk), details={"category": a.category, "requires_ack": a.requires_ack})
    if data.get("publish"):
        a = publish(a, user=user, request=request)
    return a


@transaction.atomic
def update(a: Announcement, data: dict, *, user, request=None) -> Announcement:
    a = Announcement.objects.select_for_update().get(pk=a.pk)
    if a.status == Status.ARCHIVED:
        raise CommsError("El comunicado está archivado: no se modifica.", "archived", 409)
    frozen = a.status == Status.PUBLISHED and a.requires_ack
    before = {f: getattr(a, f) for f in (*FROZEN_FIELDS, "pinned", "expires_at", "ack_due_date")}
    _apply(a, data, frozen=frozen)
    if a.status == Status.PUBLISHED:
        a.content_hash = content_hash(a)
    a.save()
    diff = [f for f, v in before.items() if getattr(a, f) != v]
    if diff:
        record("announcement_updated", AuditCategory.COMMS, f"Comunicado «{a.title}» modificado: {', '.join(diff)}.",
               request=request, actor=user, target_type="Announcement", target_id=str(a.pk), details={"fields": diff})
    return a


@transaction.atomic
def publish(a: Announcement, *, user, request=None) -> Announcement:
    a = Announcement.objects.select_for_update().get(pk=a.pk)
    if a.status != Status.DRAFT:
        raise CommsError("Solo se publica un borrador.", "not_draft", 409)
    today = timezone.localdate()
    if a.requires_ack:
        if a.ack_due_date is None:
            a.ack_due_date = today + timedelta(days=DEFAULT_ACK_DAYS)
        elif a.ack_due_date < today:
            raise CommsError("El plazo del acuse no puede estar en el pasado.", "invalid", 400, {"ack_due_date": "Plazo vencido."})
    a.status, a.published_at, a.published_by = Status.PUBLISHED, timezone.now(), user
    a.content_hash = content_hash(a)
    a.save()
    audience = len(audience_users(a))
    record("announcement_published", AuditCategory.COMMS,
           f"Comunicado «{a.title}» publicado ({CATEGORY_LABELS[a.category]})"
           + (f"; acuse obligatorio para {audience} usuario(s) hasta el {a.ack_due_date:%d/%m/%Y}." if a.requires_ack else "."),
           request=request, actor=user, target_type="Announcement", target_id=str(a.pk),
           details={"category": a.category, "requires_ack": a.requires_ack, "audience": audience, "sha256": a.content_hash})
    return a


@transaction.atomic
def archive(a: Announcement, *, user, request=None) -> Announcement:
    a = Announcement.objects.select_for_update().get(pk=a.pk)
    if a.status != Status.PUBLISHED:
        raise CommsError("Solo se archiva un comunicado publicado.", "not_published", 409)
    if a.requires_ack:
        take_snapshot(a, ComplianceSnapshot.Trigger.ARCHIVE)
    a.status, a.archived_at, a.archived_by = Status.ARCHIVED, timezone.now(), user
    a.save(update_fields=["status", "archived_at", "archived_by", "updated_at"])
    record("announcement_archived", AuditCategory.COMMS, f"Comunicado «{a.title}» archivado.", request=request, actor=user,
           target_type="Announcement", target_id=str(a.pk))
    return a


@transaction.atomic
def delete_draft(a: Announcement, *, user, request=None) -> None:
    if a.status != Status.DRAFT:
        raise CommsError("Solo se eliminan borradores; un comunicado publicado se archiva.", "not_draft", 409)
    title = a.title
    a.delete()
    record("announcement_deleted", AuditCategory.COMMS, f"Borrador «{title}» eliminado.", request=request, actor=user,
           target_type="Announcement", target_id=str(a.pk))


@transaction.atomic
def acknowledge(a: Announcement, *, user, request=None) -> AnnouncementAck:
    if a.status != Status.PUBLISHED or not a.requires_ack:
        raise CommsError("Este comunicado no requiere acuse de recibo.", "no_ack", 409)
    if not in_audience(a, user):
        raise CommsError("El comunicado no está dirigido a su rol.", "forbidden", 403)
    existing = AnnouncementAck.objects.filter(announcement=a, user=user).first()
    if existing:
        return existing
    try:
        with transaction.atomic():
            ack = AnnouncementAck.objects.create(announcement=a, user=user, username=user.username[:150], content_hash=a.content_hash,
                                                 ip_address=client_ip(request), user_agent=user_agent(request))
    except IntegrityError:  # doble clic simultáneo
        return AnnouncementAck.objects.get(announcement=a, user=user)
    late = bool(a.ack_due_date and timezone.localdate() > a.ack_due_date)
    record("announcement_acknowledged", AuditCategory.COMMS,
           f"Acuse de recibo del comunicado «{a.title}»" + (" (fuera de plazo)." if late else "."), request=request, actor=user,
           target_type="Announcement", target_id=str(a.pk), details={"sha256": a.content_hash, "late": late})
    return ack


# ================================================================ compliance
def compliance(a: Announcement, today: date | None = None) -> dict:
    today = today or timezone.localdate()
    users = audience_users(a)
    acks = {k.user_id: k for k in AnnouncementAck.objects.filter(announcement=a)}
    overdue_flag = bool(a.ack_due_date and today > a.ack_due_date)
    rows = []
    for u in users:
        k = acks.get(u.pk)
        if k:
            status = "LATE" if a.ack_due_date and timezone.localtime(k.acknowledged_at).date() > a.ack_due_date else "ACKNOWLEDGED"
        else:
            status = "OVERDUE" if overdue_flag else "PENDING"
        rows.append({
            "user_id": u.pk, "username": u.username, "name": u.get_full_name(), "role": u.effective_role,
            "employee_code": u.employee_id, "cost_center": u.cost_center.name if u.cost_center_id and u.cost_center else None,
            "status": status, "acknowledged_at": k.acknowledged_at if k else None, "ip": k.ip_address if k else None,
            "hash_ok": (k.content_hash == a.content_hash) if k else None,
        })
    acknowledged = sum(1 for r in rows if r["acknowledged_at"])
    total = len(rows)
    pct = (Decimal(acknowledged * 100) / Decimal(total)).quantize(Decimal("0.01"), ROUND_HALF_UP) if total else Decimal("100.00")
    pending = total - acknowledged
    return {"audience": total, "acknowledged": acknowledged, "pending": pending, "overdue": pending if overdue_flag else 0,
            "late": sum(1 for r in rows if r["status"] == "LATE"), "compliance_pct": pct, "due_date": a.ack_due_date,
            "is_overdue": overdue_flag, "rows": rows}


def take_snapshot(a: Announcement, trigger: str, today: date | None = None) -> ComplianceSnapshot:
    c = compliance(a, today)
    return ComplianceSnapshot.objects.create(
        announcement=a, trigger=trigger, audience=c["audience"], acknowledged=c["acknowledged"], pending=c["pending"],
        overdue=c["overdue"], compliance_pct=c["compliance_pct"],
        pending_users=[r["username"] for r in c["rows"] if not r["acknowledged_at"]][:500])


def run_daily(today: date | None = None) -> list[dict]:
    """Reporte automático: una foto diaria por comunicado con acuse vigente y otra al vencer su plazo."""
    today = today or timezone.localdate()
    out = []
    for a in Announcement.objects.filter(status=Status.PUBLISHED, requires_ack=True):
        taken = []
        if not a.snapshots.filter(trigger=ComplianceSnapshot.Trigger.DAILY, taken_at__date=today).exists():
            taken.append(take_snapshot(a, ComplianceSnapshot.Trigger.DAILY, today))
        if a.ack_due_date and today > a.ack_due_date and not a.snapshots.filter(trigger=ComplianceSnapshot.Trigger.DEADLINE).exists():
            taken.append(take_snapshot(a, ComplianceSnapshot.Trigger.DEADLINE, today))
        for s in taken:
            out.append({"announcement": a.pk, "title": a.title, "trigger": s.trigger, "compliance_pct": str(s.compliance_pct),
                        "pending": s.pending})
    if out:
        record("announcement_compliance_report", AuditCategory.COMMS, f"Reporte automático de cumplimiento: {len(out)} foto(s).",
               actor_username="system", target_type="Announcement", details={"snapshots": out})
    return out


def summary() -> list[dict]:
    out = []
    for a in Announcement.objects.filter(requires_ack=True).exclude(status=Status.DRAFT).order_by("-published_at"):
        c = compliance(a)
        c.pop("rows")
        out.append({**brief(a), **c})
    return out


# ================================================================ serialización
def brief(a: Announcement, *, user=None, acks: dict | None = None) -> dict:
    out = {
        "id": a.pk, "title": a.title, "summary": a.summary, "category": a.category, "category_label": CATEGORY_LABELS.get(a.category, a.category),
        "critical": a.is_critical, "requires_ack": a.requires_ack, "status": a.status, "status_label": Status(a.status).label,
        "pinned": a.pinned, "link_url": a.link_url, "link_label": a.link_label, "audience_roles": a.audience_roles,
        "ack_due_date": a.ack_due_date, "expires_at": a.expires_at, "published_at": a.published_at,
        "author": (a.published_by or a.created_by).get_full_name() or (a.published_by or a.created_by).username,
        "excerpt": a.summary or (a.body[:220] + ("…" if len(a.body) > 220 else "")),
    }
    if user is not None:
        k = (acks or {}).get(a.pk) if acks is not None else AnnouncementAck.objects.filter(announcement=a, user=user).first()
        out["my_ack"] = {"at": k.acknowledged_at, "sha256": k.content_hash} if k else None
        out["ack_pending"] = a.requires_ack and a.status == Status.PUBLISHED and k is None and in_audience(a, user)
        out["ack_overdue"] = bool(out["ack_pending"] and a.ack_due_date and timezone.localdate() > a.ack_due_date)
    return out


def detail(a: Announcement, user) -> dict:
    out = brief(a, user=user)
    manage = can_manage(user)
    out.update({
        "body": a.body, "content_hash": a.content_hash, "created_at": a.created_at, "updated_at": a.updated_at,
        "archived_at": a.archived_at, "can_manage": manage, "can_report": can_report(user),
        "can_edit": manage and (a.status == Status.DRAFT or a.status == Status.PUBLISHED),
        "content_frozen": a.status != Status.DRAFT and a.requires_ack,
    })
    if (manage or can_report(user)) and a.requires_ack and a.status != Status.DRAFT:
        c = compliance(a)
        c.pop("rows")
        out["compliance"] = c
    return out
