"""Fase 24 — Adjuntos (evidencias) de las Acciones de Personal y expediente de la AP.

* Formatos: imágenes PNG / JPG / JPEG (validadas con Pillow, igual que el expediente digital), PDF y documentos de
  Office (DOCX / XLSX y los antiguos DOC / XLS). Se valida la extensión, el tamaño (parámetro del admin) y la FIRMA
  binaria del contenido (un .pdf que no es PDF se rechaza). Los bytes se guardan ORIGINALES: su SHA-256 prueba la
  integridad del respaldo.
* Quién adjunta: quien puede elaborar el tipo de AP o quien firma el paso en curso, mientras la AP está en borrador o
  en aprobación (las resueltas o anuladas quedan congeladas, también en SQL Server).
* Retirar: nunca se borra; se retira con motivo (queda visible en la pestaña de evidencias y en la auditoría).
* `dossier`: las pestañas de la AP (evidencias y bitácora de auditoría: creación, envío, firmas, adjuntos, aplicación).
"""

from __future__ import annotations

import hashlib
import io
import uuid
import zipfile
from datetime import timedelta
from pathlib import PurePath

from django.db import transaction
from django.utils import timezone

from apps.employees.digital_files import private_storage
from apps.employees.media import ImageRejected, _safe_name, inspect_image
from apps.personnel_actions.models import ActionAttachment, AttachmentCategory, AttachmentKind, PersonnelAction, Status
from apps.system import policy
from apps.system.audit import Category, record

MAX_PER_ACTION = 15
OPEN = (Status.DRAFT, Status.PENDING)
OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
FORMATS = {
    ".png": (AttachmentKind.IMAGE, "image/png"),
    ".jpg": (AttachmentKind.IMAGE, "image/jpeg"),
    ".jpeg": (AttachmentKind.IMAGE, "image/jpeg"),
    ".pdf": (AttachmentKind.PDF, "application/pdf"),
    ".docx": (AttachmentKind.DOCUMENT, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".xlsx": (AttachmentKind.DOCUMENT, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".doc": (AttachmentKind.DOCUMENT, "application/msword"),
    ".xls": (AttachmentKind.DOCUMENT, "application/vnd.ms-excel"),
}
ACCEPT = ",".join(FORMATS)


class AttachmentError(Exception):
    def __init__(self, message: str, code: str = "invalid", status: int = 400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


# ================================================================ permisos
def can_attach(action: PersonnelAction, user) -> bool:
    from apps.personnel_actions import services

    if action.status not in OPEN:
        return False
    if services.can_create_type(user, action.action_type):
        return True
    return action.status == Status.PENDING and services.sign_block_reason(action, user) is None


def can_remove(attachment: ActionAttachment, user) -> bool:
    from apps.personnel_actions import services

    if attachment.removed_at or attachment.action.status not in OPEN:
        return False
    return attachment.uploaded_by_id == user.pk or services.can_create_type(user, attachment.action.action_type)


# ================================================================ validación del archivo
def _ooxml_ok(data: bytes, extension: str) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
    except (zipfile.BadZipFile, ValueError):
        return False
    folder = "word/" if extension == ".docx" else "xl/"
    return "[Content_Types].xml" in names and any(n.startswith(folder) for n in names)


def inspect(upload, *, max_bytes: int) -> dict:
    name = _safe_name(getattr(upload, "name", "") or "archivo")
    extension = PurePath(name).suffix.lower()
    if extension not in FORMATS:
        raise AttachmentError(f"«{name}» no es un formato permitido. Adjunte imágenes (PNG, JPG), PDF o documentos de Office "
                              "(DOCX, XLSX, DOC, XLS).", "invalid_extension")
    kind, mime = FORMATS[extension]
    mb = max_bytes // 1_048_576
    if kind == AttachmentKind.IMAGE:
        try:
            image = inspect_image(upload, max_bytes=max_bytes)
        except ImageRejected as exc:
            raise AttachmentError(exc.message, exc.code) from None
        return {"data": image.data, "name": name, "kind": kind, "mime": image.mime_type, "width": image.width, "height": image.height}
    size = getattr(upload, "size", None)
    if size is not None and size > max_bytes:
        raise AttachmentError(f"«{name}» pesa {size / 1_048_576:.1f} MB; el máximo es {mb} MB.", "too_large")
    data = upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise AttachmentError(f"«{name}» supera el máximo de {mb} MB.", "too_large")
    if not data:
        raise AttachmentError("El archivo está vacío.", "empty")
    if extension == ".pdf":
        ok = data[:1024].lstrip().startswith(b"%PDF-")
    elif extension in (".docx", ".xlsx"):
        ok = data.startswith(b"PK\x03\x04") and _ooxml_ok(data, extension)
    else:
        ok = data.startswith(OLE_SIGNATURE)
    if not ok:
        raise AttachmentError(f"El contenido de «{name}» no corresponde a un archivo {extension[1:].upper()} válido.", "invalid_content")
    return {"data": data, "name": name, "kind": kind, "mime": mime, "width": None, "height": None}


# ================================================================ operaciones
@transaction.atomic
def add(action: PersonnelAction, upload, *, user, category: str = "", description: str = "", request=None) -> ActionAttachment:
    if action.status not in OPEN:
        raise AttachmentError(f"La AP {action.folio} está {action.get_status_display().lower()}: ya no admite adjuntos.", "closed", 409)
    if not can_attach(action, user):
        raise AttachmentError("Su rol no puede adjuntar archivos a esta AP (solo quien la elabora o quien firma el paso en curso).",
                              "forbidden", 403)
    category = (category or AttachmentCategory.EVIDENCE).upper()
    if category not in AttachmentCategory.values:
        raise AttachmentError("Categoría de adjunto desconocida.", "invalid_category")
    if action.attachments.filter(removed_at__isnull=True).count() >= MAX_PER_ACTION:
        raise AttachmentError(f"La AP ya tiene {MAX_PER_ACTION} adjuntos vigentes (máximo).", "too_many")
    info = inspect(upload, max_bytes=policy.current().max_attachment_mb * 1_048_576)
    sha = hashlib.sha256(info["data"]).hexdigest()
    if action.attachments.filter(removed_at__isnull=True, sha256_hash=sha).exists():
        raise AttachmentError(f"«{info['name']}» ya está adjunto a la AP (mismo SHA-256).", "duplicate")
    storage = private_storage()
    ext = PurePath(info["name"]).suffix.lower()
    stored = storage.save(f"personnel_actions/{action.employee_id}/{action.folio}/{uuid.uuid4().hex}{ext}", _content(info["data"]))
    try:
        att = ActionAttachment.objects.create(
            action=action, category=category, description=(description or "").strip()[:300], kind=info["kind"],
            original_name=info["name"], storage_path=stored, mime_type=info["mime"], size_bytes=len(info["data"]),
            sha256_hash=sha, image_width=info["width"], image_height=info["height"], status_at_upload=action.status,
            uploaded_by=user if getattr(user, "pk", None) else None, uploaded_by_username=getattr(user, "username", "") or "sistema",
        )
    except Exception:
        storage.delete(stored)  # sin fila en la BD no debe quedar el archivo
        raise
    record("personnel_action_attachment_added", Category.PERSONNEL_ACTIONS,
           f"AP {action.folio}: adjunto «{att.original_name}» ({att.get_category_display().lower()}, {_size(att.size_bytes)}).",
           request=request, actor=user, target=action.employee,
           details={"folio": action.folio, "attachment": att.pk, "sha256": sha, "name": att.original_name, "category": category})
    return att


@transaction.atomic
def remove(att: ActionAttachment, *, user, reason: str, request=None) -> ActionAttachment:
    reason = (reason or "").strip()
    if not reason:
        raise AttachmentError("Indique el motivo para retirar el adjunto.", "reason_required")
    if att.removed_at:
        raise AttachmentError("El adjunto ya fue retirado.", "already_removed")
    if att.action.status not in OPEN:
        raise AttachmentError(f"La AP {att.action.folio} está {att.action.get_status_display().lower()}: sus adjuntos no se retiran.", "closed", 409)
    if not can_remove(att, user):
        raise AttachmentError("Solo quien lo adjuntó o quien elabora este tipo de AP puede retirar el adjunto.", "forbidden", 403)
    att.removed_at = timezone.now()
    att.removed_by_username = getattr(user, "username", "") or "sistema"
    att.removed_reason = reason[:300]
    att.save(update_fields=["removed_at", "removed_by_username", "removed_reason"])
    record("personnel_action_attachment_removed", Category.PERSONNEL_ACTIONS,
           f"AP {att.action.folio}: adjunto «{att.original_name}» retirado: {reason[:200]}",
           request=request, actor=user, target=att.action.employee,
           details={"folio": att.action.folio, "attachment": att.pk, "sha256": att.sha256_hash, "reason": reason[:300]})
    return att


def open_file(att: ActionAttachment):
    return private_storage().open(att.storage_path, "rb")


def _content(data: bytes):
    from django.core.files.base import ContentFile

    return ContentFile(data)


def _size(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB" if n >= 1_048_576 else f"{max(1, round(n / 1024))} KB"


# ================================================================ serialización y expediente de la AP
def attachment_dict(att: ActionAttachment, user) -> dict:
    return {
        "id": att.pk, "category": att.category, "category_label": att.get_category_display(), "kind": att.kind,
        "kind_label": att.get_kind_display(), "description": att.description, "original_name": att.original_name,
        "mime_type": att.mime_type, "size_bytes": att.size_bytes, "size_label": _size(att.size_bytes), "sha256": att.sha256_hash,
        "width": att.image_width, "height": att.image_height, "status_at_upload": att.status_at_upload,
        "uploaded_at": att.uploaded_at, "uploaded_by": att.uploaded_by_username,
        "removed": att.removed_at is not None, "removed_at": att.removed_at, "removed_by": att.removed_by_username or None,
        "removed_reason": att.removed_reason or None,
        "url": f"/api/v1/personnel-actions/attachments/{att.pk}/content/",
        "can_remove": can_remove(att, user),
    }


def audit_trail(action: PersonnelAction) -> list[dict]:
    """Bitácora de la AP: eventos de auditoría (creación, edición, envío, firmas, adjuntos, aplicación, anulación)."""
    from apps.system.models import AuditEvent

    events = AuditEvent.objects.filter(category=Category.PERSONNEL_ACTIONS, target_id=action.employee.employee_code,
                                       occurred_at__gte=action.created_at - timedelta(minutes=1)).order_by("occurred_at", "id")
    out = []
    for ev in events:
        if (ev.details or {}).get("folio") != action.folio:
            continue
        out.append({"at": ev.occurred_at, "action": ev.action, "summary": ev.summary, "actor": ev.actor_username or None,
                    "success": ev.success, "ip": ev.ip_address, "details": {k: v for k, v in (ev.details or {}).items() if k != "folio"}})
    return out


def dossier(action: PersonnelAction, user) -> dict:
    files = list(action.attachments.all().order_by("uploaded_at", "id"))
    return {
        "attachments": [attachment_dict(a, user) for a in files],
        "attachments_current": sum(1 for a in files if not a.removed_at),
        "can_attach": can_attach(action, user),
        "attachment_rules": {"accept": ACCEPT, "max_mb": policy.current().max_attachment_mb, "max_files": MAX_PER_ACTION,
                             "categories": [{"value": v, "label": label} for v, label in AttachmentCategory.choices]},
        "audit": audit_trail(action),
    }
