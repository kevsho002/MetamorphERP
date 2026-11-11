"""Expediente digital (Fase 5): vista dinámica por plantilla/fecha, documentos e imágenes.

* `build_dossier`  arma el expediente con las pestañas/secciones de la plantilla del
  país vigente a una fecha (por defecto la de ingreso) y los valores EAV del empleado.
* `upload_document` guarda una nueva VERSIÓN de un documento (o la foto de perfil):
  imagen validada, almacenamiento privado, hash SHA-256, una sola versión vigente.
* Los documentos sensibles (identidad, tributarios, bancarios, médicos...) solo se
  muestran a quien tiene permiso de planilla, igual que los atributos EAV sensibles.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.db import transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from apps.accounts.permissions import user_permissions
from apps.accounts.roles import Perm
from apps.employees.media import ImageRejected, inspect_image, normalize_profile_photo
from apps.employees.models import EmployeeAttributeValue
from apps.employees.schema import TemplateSpec, is_blank, resolve_template
from apps.employees.validation import ValidationContext
from apps.hcm.models import DigitalFile, DigitalFileDocument, DocumentType, Employee
from apps.system import policy

EXPIRING_DAYS = 30


class DocumentError(Exception):
    def __init__(self, message: str, code: str = "invalid", field: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.field = field


def private_storage() -> FileSystemStorage:
    """Almacenamiento fuera de STATIC/WHITENOISE: el único acceso es la API con permisos."""
    return FileSystemStorage(location=settings.PRIVATE_MEDIA_ROOT, base_url=None)


def can_view_sensitive(user) -> bool:
    return Perm.PAYROLL_VIEW in user_permissions(user)


def can_view_document(user, document_type: DocumentType) -> bool:
    perms = user_permissions(user)
    return Perm.HCM_VIEW in perms and (not document_type.is_sensitive or Perm.PAYROLL_VIEW in perms)


# --------------------------------------------------------------------- tipos y checklist
def document_types_for(country_id: int) -> list[DocumentType]:
    return list(
        DocumentType.objects.filter(Q(country__isnull=True) | Q(country_id=country_id), is_active=True)
        .exclude(code=DocumentType.PROFILE_PHOTO)
        .order_by("name")
    )


@dataclass
class DocumentRequirement:
    type: DocumentType
    label: str
    required: bool
    help: str | None


def requirements(country_id: int, spec: TemplateSpec | None) -> list[DocumentRequirement]:
    """Catálogo del país + reglas de la plantilla (`documents`): obligatoriedad y nombre local."""
    config = spec.documents_config if spec else {}
    result = []
    for doc_type in document_types_for(country_id):
        rules = config.get(doc_type.code, {})
        result.append(
            DocumentRequirement(
                type=doc_type,
                label=rules.get("label") or doc_type.name,
                required=rules.get("required", doc_type.is_mandatory),
                help=rules.get("help"),
            )
        )
    # Obligatorios primero, luego por nombre.
    return sorted(result, key=lambda r: (not r.required, r.label.lower()))


def _doc_status(requirement: DocumentRequirement, current: DigitalFileDocument | None, today: date) -> str:
    if current is None:
        return "MISSING" if requirement.required else "NOT_PROVIDED"
    if current.expiry_date:
        if current.expiry_date < today:
            return "EXPIRED"
        if current.expiry_date <= today + timedelta(days=EXPIRING_DAYS):
            return "EXPIRING"
    return "OK"


STATUS_LABELS = {
    "MISSING": "Pendiente (obligatorio)",
    "NOT_PROVIDED": "No entregado (opcional)",
    "EXPIRED": "Vencido",
    "EXPIRING": f"Vence en {EXPIRING_DAYS} días o menos",
    "OK": "Vigente",
}


def document_payload(doc: DigitalFileDocument, *, viewable: bool) -> dict:
    data = {
        "id": doc.document_id,
        "version": doc.version_number,
        "is_current": doc.is_current,
        "uploaded_at": doc.uploaded_at,
        "uploaded_by": doc.uploaded_by,
        "issue_date": doc.issue_date,
        "expiry_date": doc.expiry_date,
        "viewable": viewable,
    }
    if viewable:  # nombre, tamaño y hash pueden revelar datos: solo para quien puede ver el documento
        data.update(
            {
                "original_name": doc.original_name,
                "mime_type": doc.mime_type,
                "size_bytes": doc.size_bytes,
                "sha256": doc.sha256_hash,
                "width": doc.image_width,
                "height": doc.image_height,
                "content_url": f"/api/v1/hcm/documents/{doc.document_id}/content/",
            }
        )
    return data


def document_checklist(employee: Employee, spec: TemplateSpec | None, user, today: date | None = None) -> dict:
    today = today or timezone.localdate()
    digital_file = DigitalFile.objects.filter(employee=employee).first()
    current: dict[int, DigitalFileDocument] = {}
    versions: dict[int, int] = {}
    if digital_file is not None:
        docs = DigitalFileDocument.objects.filter(digital_file=digital_file)
        current = {d.document_type_id: d for d in docs.filter(is_current=True)}
        versions = dict(docs.values("document_type_id").annotate(n=Count("document_id")).values_list("document_type_id", "n"))
    items = []
    required_total = required_ok = 0
    for req in requirements(employee.country_id, spec):
        doc = current.get(req.type.document_type_id)
        state = _doc_status(req, doc, today)
        viewable = can_view_document(user, req.type)
        if req.required:
            required_total += 1
            required_ok += state in ("OK", "EXPIRING")
        items.append(
            {
                "code": req.type.code,
                "name": req.type.name,
                "label": req.label,
                "help": req.help,
                "required": req.required,
                "requires_expiry": req.type.requires_expiry,
                "is_sensitive": req.type.is_sensitive,
                "retention_years": req.type.retention_years,
                "status": state,
                "status_label": STATUS_LABELS[state],
                "viewable": viewable,
                "versions": versions.get(req.type.document_type_id, 0),
                "current": document_payload(doc, viewable=viewable) if doc else None,
            }
        )
    return {
        "items": items,
        "required_total": required_total,
        "required_ok": required_ok,
        "percent": round(100 * required_ok / required_total) if required_total else 100,
    }


def current_photo(employee: Employee) -> DigitalFileDocument | None:
    return (
        DigitalFileDocument.objects.filter(
            digital_file__employee=employee, document_type__code=DocumentType.PROFILE_PHOTO, is_current=True
        )
        .order_by("-version_number")
        .first()
    )


def photo_payload(employee: Employee) -> dict | None:
    photo = current_photo(employee)
    if photo is None:
        return None
    return {
        "id": photo.document_id,
        "version": photo.version_number,
        "url": f"/api/v1/hcm/employees/{employee.employee_code}/photo/?v={photo.document_id}",
        "width": photo.image_width,
        "height": photo.image_height,
        "uploaded_at": photo.uploaded_at,
        "uploaded_by": photo.uploaded_by,
    }


# --------------------------------------------------------------------- expediente dinámico
def build_dossier(employee: Employee, employee_data: dict, *, user, as_of: date | None) -> dict:
    """Expediente armado con la plantilla del país vigente a `as_of` (por defecto, la fecha de ingreso).

    `employee_data` es la salida de EmployeeSerializer (ya sin datos restringidos por RBAC).
    """
    basis = "hire_date" if as_of is None else "as_of"
    on_date = as_of or employee.hire_date
    ctx = ValidationContext()
    template = ctx.template_for(employee.country, on_date)
    spec = resolve_template(template) if template else None

    restricted = set(employee_data.get("restricted_fields") or [])
    attributes = employee_data.get("attributes") or {}
    meta = {
        v.attribute.code: v
        for v in EmployeeAttributeValue.objects.filter(employee=employee).select_related("attribute", "template")
    }

    def field_entry(key: str) -> dict:
        f = spec.fields[key]
        is_restricted = key in restricted
        value = None if is_restricted else (attributes.get(key) if f.kind == "attribute" else employee_data.get(key))
        entry = {
            "key": key,
            "label": f.label,
            "kind": f.kind,
            "data_type": f.data_type,
            "required": f.required,
            "recommended": f.recommended,
            "help": f.help,
            "value": value,
            "display": f.display(value) if value not in (None, "") and f.choice_labels else None,
            "mask": list(f.mask) or None,
            "restricted": is_restricted,
            "missing": not is_restricted and f.required and is_blank(value),
        }
        record = meta.get(key)
        if record is not None:
            entry["recorded"] = {
                "template_id": record.template_id,
                "template_name": record.template.name,
                "template_effective_date": record.template.effective_date,
                "updated_at": record.updated_at,
                "updated_by": record.updated_by,
            }
        return entry

    tabs = []
    gaps = []
    if spec is not None:
        for tab in spec.layout:
            sections = []
            for section in tab["sections"]:
                entries = [field_entry(k) for k in section["fields"]]
                gaps += [{"key": e["key"], "label": e["label"], "tab": tab["id"]} for e in entries if e["missing"]]
                sections.append({**section, "fields": entries})
            tabs.append({**tab, "sections": sections})
        # Valores registrados con otra versión de la plantilla que la versión consultada ya no usa.
        historic = [code for code in meta if code not in spec.fields and (code in attributes or code in restricted)]
        if historic:
            entries = []
            for code in historic:
                record = meta[code]
                entries.append(
                    {
                        "key": code,
                        "label": record.attribute.name,
                        "kind": "attribute",
                        "data_type": record.attribute.data_type,
                        "required": False,
                        "recommended": False,
                        "help": None,
                        "value": None if code in restricted else attributes.get(code),
                        "restricted": code in restricted,
                        "missing": False,
                        "recorded": {
                            "template_id": record.template_id,
                            "template_name": record.template.name,
                            "template_effective_date": record.template.effective_date,
                            "updated_at": record.updated_at,
                            "updated_by": record.updated_by,
                        },
                    }
                )
            tabs.append(
                {
                    "id": "historic",
                    "label": "Otras versiones",
                    "description": "Datos registrados con otra versión de la plantilla que la versión consultada no solicita.",
                    "sections": [{"id": "historic_values", "title": "Datos de otras versiones de la plantilla", "description": None, "fields": entries}],
                }
            )

    digital_file = DigitalFile.objects.filter(employee=employee).first()
    perms = user_permissions(user)
    return {
        "employee": employee_data,
        "basis": {"mode": basis, "date": on_date},
        "template": (
            {
                "id": template.pk,
                "name": template.name,
                "effective_date": template.effective_date,
                "is_hire_template": ctx.template_for(employee.country, employee.hire_date) == template,
            }
            if template
            else None
        ),
        "template_error": None
        if template
        else f"No existe una plantilla activa de {employee.country.country_name} vigente al {on_date:%d/%m/%Y}.",
        "tabs": tabs,
        "gaps": gaps,
        "photo": photo_payload(employee),
        "documents": document_checklist(employee, spec, user),
        "file": {
            "status": digital_file.file_status if digital_file else None,
            "status_label": DigitalFile.Status(digital_file.file_status).label if digital_file else "Sin expediente",
            "opened_at": digital_file.opened_at if digital_file else None,
        },
        "permissions": {
            "can_upload": Perm.HCM_MANAGE in perms,
            "can_view_sensitive": Perm.PAYROLL_VIEW in perms,
            "can_manage_account": Perm.USERS_CREATE in perms,
        },
    }


# --------------------------------------------------------------------- carga de documentos
def _parse_optional_date(value, field: str) -> date | None:
    from django.utils.dateparse import parse_date

    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    parsed = parse_date(str(value))
    if parsed is None:
        raise DocumentError("Use el formato AAAA-MM-DD.", "invalid_date", field)
    return parsed


@transaction.atomic
def upload_document(
    employee: Employee, document_type: DocumentType, upload, *, issue_date=None, expiry_date=None, actor: str
) -> DigitalFileDocument:
    issue = _parse_optional_date(issue_date, "issue_date")
    expiry = _parse_optional_date(expiry_date, "expiry_date")
    today = timezone.localdate()
    is_photo = document_type.code == DocumentType.PROFILE_PHOTO
    if not document_type.is_active:
        raise DocumentError(f"El tipo de documento «{document_type.name}» está inactivo.", "inactive_type", "document_type")
    if document_type.country_id and document_type.country_id != employee.country_id:
        raise DocumentError("Ese tipo de documento no aplica al país del empleado.", "wrong_country", "document_type")
    if not is_photo:
        if issue and issue > today:
            raise DocumentError("La fecha de emisión no puede ser futura.", "future_issue", "issue_date")
        if expiry and issue and expiry < issue:
            raise DocumentError("La fecha de vencimiento es anterior a la de emisión.", "expiry_before_issue", "expiry_date")
        if document_type.requires_expiry and not expiry:
            raise DocumentError(
                f"«{document_type.name}» requiere fecha de vencimiento.", "expiry_required", "expiry_date"
            )
    else:
        issue = expiry = None

    max_bytes = policy.current().max_document_mb * 1_048_576
    try:
        image = inspect_image(upload, max_bytes=max_bytes)
        if is_photo:
            image = normalize_profile_photo(image)
    except ImageRejected as exc:
        raise DocumentError(exc.message, exc.code, "file") from None

    digital_file = DigitalFile.objects.select_for_update().filter(employee=employee).first()
    if digital_file is None:  # empleados anteriores al expediente 1:1 (no debería ocurrir)
        digital_file = DigitalFile.objects.create(employee=employee, created_by=actor[:100])
    if digital_file.file_status == DigitalFile.Status.ARCHIVED:
        raise DocumentError("El expediente está archivado: no admite documentos nuevos.", "archived")

    sha256 = hashlib.sha256(image.data).hexdigest()
    versions = DigitalFileDocument.objects.select_for_update().filter(digital_file=digital_file, document_type=document_type)
    current = versions.filter(is_current=True).first()
    if current is not None and current.sha256_hash == sha256:
        raise DocumentError(
            "La imagen es idéntica a la versión vigente (mismo SHA-256); no se creó una versión nueva.", "duplicate", "file"
        )
    next_version = (versions.aggregate(m=Max("version_number"))["m"] or 0) + 1

    storage = private_storage()
    name = f"employees/{employee.employee_id}/{document_type.code.lower()}/{uuid.uuid4().hex}{image.extension}"
    stored = storage.save(name, ContentFile(image.data))
    try:
        if current is not None:
            current.is_current = False
            current.save(update_fields=["is_current"])
        document = DigitalFileDocument.objects.create(
            digital_file=digital_file,
            document_type=document_type,
            version_number=next_version,
            is_current=True,
            original_name=image.original_name,
            storage_path=stored,
            mime_type=image.mime_type,
            size_bytes=len(image.data),
            sha256_hash=sha256,
            issue_date=issue,
            expiry_date=expiry,
            uploaded_by=actor[:100],
            image_width=image.width,
            image_height=image.height,
        )
    except Exception:
        storage.delete(stored)  # sin registro en BD no debe quedar el archivo
        raise
    return document


def open_document(document: DigitalFileDocument):
    return private_storage().open(document.storage_path, "rb")
