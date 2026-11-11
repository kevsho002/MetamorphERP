"""Reglas de negocio de las Acciones de Personal (AP).

Ciclo de vida:  DRAFT (borrador, editable) -> PENDING (enviada: contenido SELLADO) -> APPROVED | REJECTED
                DRAFT / PENDING -> CANCELLED (anulada, con motivo)
* Al enviar se calcula el sello SHA-256 del contenido (tipo, empleado, fecha efectiva, justificación y valores
  EAV). Desde ese momento los valores no cambian (trigger 50051 en SQL Server).
* Firmas por pasos (cadena del tipo): firma el siguiente paso pendiente un usuario con el ROL del paso (el
  Administrador puede firmar cualquier paso). Cada firma guarda un HMAC-SHA256 (clave del servidor) sobre el
  folio, el paso, el firmante, la decisión, la hora y el sello del contenido: `verify()` detecta cualquier
  alteración posterior. Las firmas son inmutables (trigger 50050).
* Al completar la cadena la AP queda APROBADA y se ejecuta su EFECTO:
    SCHEDULE  aplica el horario atómico por día desde la fecha efectiva. Modo PRINCIPAL: cierra el principal
              vigente el día previo. Modo ADICIONAL (Fase 10): se suma al principal hasta «vigente_hasta»
              (turno partido / doble asignación); los bloques no pueden pedir las mismas horas;
    SALARY    actualiza el salario base (si la fecha efectiva es futura, lo aplica `apply_due_actions`);
    NONE      solo registro.
* AP fundacional: la «Primera AP de asignación de horario» se crea en el alta de cada empleado
  (`create_initial_schedule_action`), con fecha efectiva = fecha de ingreso.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.permissions import user_permissions
from apps.accounts.roles import Role
from apps.hcm.models import Employee
from apps.personnel_actions.models import (
    OPEN_STATUSES, ActionAttribute, ActionSignature, ActionType, ActionValue, DataType, Decision, Effect,
    FolioSequence, PersonnelAction, ScheduleMode, Status,
)
from apps.system.audit import Category, record

END_DATE_KEY = "vigente_hasta"  # campo DATE obligatorio de las AP de asignación ADICIONAL de horario

TRUE = {"1", "true", "si", "sí", "yes", "y", "s", "x"}
FALSE = {"0", "false", "no", "n", ""}


def fmt(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


def parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value).strip(), pattern).date()
        except ValueError:
            continue
    return None


@dataclass
class Check:
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    cleaned: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, field_name, message, code="invalid"):
        self.errors.append({"field": field_name, "message": message, "code": code})

    def warn(self, field_name, message, code="warning"):
        self.warnings.append({"field": field_name, "message": message, "code": code})

    def as_dict(self) -> dict:
        body = {"valid": self.ok, "errors": self.errors, "warnings": self.warnings}
        if self.errors:
            body["detail"] = " ".join(e["message"] for e in self.errors)
        return body


class ActionError(Exception):
    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.message, self.code = message, code


# ================================================================ permisos
def can_view_type(user, t: ActionType) -> bool:
    perms = user_permissions(user)
    return "actions.view" in perms and t.view_permission in perms


def can_create_type(user, t: ActionType) -> bool:
    perms = user_permissions(user)
    return "actions.create" in perms and t.create_permission in perms and can_view_type(user, t)


def visible_type_ids(user) -> list[int]:
    return [t.pk for t in ActionType.objects.all() if can_view_type(user, t)]


def can_sign_role(user, role: str) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return user.effective_role in (role, Role.ADMIN)


# ================================================================ folio
def next_folio(prefix: str, on: date) -> str:
    """Folio único y correlativo por prefijo y año: APH-2026-000001 (bloqueo de fila: sin duplicados)."""
    seq, _ = FolioSequence.objects.select_for_update().get_or_create(prefix=prefix, year=on.year)
    seq.last_value += 1
    seq.save(update_fields=["last_value"])
    return f"{prefix}-{on.year}-{seq.last_value:06d}"


# ================================================================ valores EAV
def _coerce(attr: ActionAttribute, raw: Any, *, employee: Employee, effective_date: date | None, check: Check):
    """Valor tipado del campo o None (vacío). Agrega errores a `check`."""
    from apps.scheduling import services as sch

    where = f"values.{attr.key}"
    empty = raw is None or (isinstance(raw, str) and not raw.strip()) or raw == {}
    if empty:
        if attr.required:
            check.error(where, f"«{attr.label}» es obligatorio.", "required")
        return None
    t = attr.data_type
    if t in (DataType.TEXT, DataType.LONG_TEXT):
        text = str(raw).strip()
        limit = attr.max_length or (300 if t == DataType.TEXT else 2000)
        if len(text) > limit:
            check.error(where, f"«{attr.label}» admite hasta {limit} caracteres.")
        return text
    if t in (DataType.INTEGER, DataType.DECIMAL):
        try:
            number = Decimal(str(raw).replace(",", "").strip())
        except InvalidOperation:
            check.error(where, f"«{attr.label}» debe ser un número.")
            return None
        if t == DataType.INTEGER and number != number.to_integral_value():
            check.error(where, f"«{attr.label}» debe ser un número entero.")
        if attr.min_value is not None and number < attr.min_value:
            check.error(where, f"«{attr.label}» debe ser al menos {attr.min_value.normalize()}.")
        if attr.max_value is not None and number > attr.max_value:
            check.error(where, f"«{attr.label}» debe ser como máximo {attr.max_value.normalize()}.")
        return number
    if t == DataType.DATE:
        d = parse_date(raw)
        if d is None:
            check.error(where, f"«{attr.label}»: fecha inválida (use AAAA-MM-DD).")
        return d
    if t == DataType.BOOLEAN:
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in TRUE:
            return True
        if text in FALSE:
            return False
        check.error(where, f"«{attr.label}» debe ser Sí o No.")
        return None
    if t == DataType.CHOICE:
        text = str(raw).strip()
        for option in attr.option_list():
            if text.lower() in (option["value"].lower(), option["label"].lower()):
                return option["value"]
        check.error(where, f"«{attr.label}»: «{text}» no es una opción válida ({', '.join(o['label'] for o in attr.option_list())}).", "invalid_choice")
        return None
    if t == DataType.SCHEDULE:
        definition, errors = sch.evaluate_schedule(raw, country_id=employee.country_id, on=effective_date or timezone.localdate())
        for e in errors:
            field_name = str(e.get("field") or "").replace("definition", where, 1)
            check.error(field_name or where, e["message"], "schedule")
        return definition
    return raw


def _json_safe(value):
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, date):
        return value.isoformat()
    return value


def display_value(attr: ActionAttribute, value) -> str:
    if value is None:
        return "—"
    if attr.data_type == DataType.BOOLEAN:
        return "Sí" if value else "No"
    if attr.data_type == DataType.DATE:
        return fmt(value)
    if attr.data_type == DataType.CHOICE:
        return next((o["label"] for o in attr.option_list() if o["value"] == value), str(value))
    if attr.data_type in (DataType.INTEGER, DataType.DECIMAL):
        return format(Decimal(value).normalize(), ",f") if attr.data_type == DataType.DECIMAL else str(int(value))
    if attr.data_type == DataType.SCHEDULE:
        return "Horario semanal"
    return str(value)


# ================================================================ validación
def validate(action_type: ActionType | None, employee: Employee | None, data: dict, *, user=None,
             instance: PersonnelAction | None = None, for_initial: bool = False) -> Check:
    from apps.scheduling import services as sch

    check = Check()
    c = check.cleaned
    if action_type is None:
        check.error("action_type", "Seleccione el tipo de acción de personal.", "required")
    elif not action_type.is_active and instance is None:
        check.error("action_type", f"El tipo «{action_type.name}» está inactivo.")
    elif user is not None and not for_initial and not can_create_type(user, action_type):
        check.error("action_type", f"Su rol no puede elaborar acciones de tipo «{action_type.name}».", "forbidden")
    if employee is None:
        check.error("employee_code", "Indique el empleado (ID corporativo).", "required")
    if not check.ok:
        return check

    eff = parse_date(data.get("effective_date"))
    if data.get("effective_date") in (None, ""):
        check.error("effective_date", "Indique la fecha efectiva de aplicación.", "required")
    elif eff is None:
        check.error("effective_date", "Fecha efectiva inválida (use AAAA-MM-DD).")
    justification = str(data.get("justification") or "").strip()
    if not justification:
        check.error("justification", "Escriba las observaciones / justificación de la acción.", "required")
    elif len(justification) > 2000:
        check.error("justification", "La justificación admite hasta 2000 caracteres.")
    c.update(action_type=action_type, employee=employee, effective_date=eff, justification=justification)
    if eff:
        if eff < employee.hire_date:
            check.error("effective_date", f"La fecha efectiva no puede ser anterior al ingreso del empleado ({fmt(employee.hire_date)}).")
        if employee.termination_date and eff > employee.termination_date:
            check.error("effective_date", f"El empleado terminó su relación laboral el {fmt(employee.termination_date)}.")

    # Valores EAV
    raw_values = data.get("values") or {}
    if not isinstance(raw_values, dict):
        check.error("values", "«values» debe ser un objeto {campo: valor}.")
        raw_values = {}
    attributes = list(action_type.attributes.filter(is_active=True))
    known = {a.key for a in attributes}
    for key in raw_values:
        if key not in known:
            check.error(f"values.{key}", f"El campo «{key}» no pertenece al tipo «{action_type.name}».", "unknown_field")
    values = {}
    for attr in attributes:
        values[attr.key] = (attr, _coerce(attr, raw_values.get(attr.key), employee=employee, effective_date=eff, check=check))
    c["values"] = values

    # Reglas por efecto
    if action_type.effect == Effect.SCHEDULE:
        schedule_attr = next((a for a in attributes if a.data_type == DataType.SCHEDULE), None)
        additional = action_type.schedule_mode == ScheduleMode.ADDITIONAL
        end_attr = values.get(END_DATE_KEY)
        if schedule_attr is None:
            check.error(None, f"El tipo «{action_type.name}» asigna horario pero no tiene un campo de tipo «Horario semanal». Corríjalo en /admin/.", "config")
        elif additional and (end_attr is None or end_attr[0].data_type != DataType.DATE):
            check.error(None, f"El tipo «{action_type.name}» es una asignación adicional pero no tiene el campo de fecha «{END_DATE_KEY}». Corríjalo en /admin/.", "config")
        elif eff and check.ok:
            others = PersonnelAction.objects.filter(employee=employee, is_initial=True, status__in=OPEN_STATUSES)
            if instance is not None:
                others = others.exclude(pk=instance.pk)
            if action_type.is_initial_schedule:
                if others.exists():
                    check.error("action_type", f"El empleado ya tiene su Primera AP de asignación de horario ({others.first().folio}).", "initial_exists")
                if eff != employee.hire_date:
                    check.error("effective_date", f"La Primera AP de horario rige desde la fecha de ingreso ({fmt(employee.hire_date)}).")
            elif not others.exists():
                check.error("action_type", (
                    "El empleado no tiene su Primera AP de asignación de horario: elabórela primero (es la AP fundacional "
                    "de su turno)."
                ), "initial_missing")
            if check.ok:
                end_date = end_attr[1] if additional else None
                if additional and end_date is None:
                    check.error(f"values.{END_DATE_KEY}", "Indique hasta cuándo rige la asignación adicional.", "required")
                schedule = values[schedule_attr.key][1]
                for e in sch.check_schedule_application(
                    employee, eff, definition=schedule, mode=action_type.schedule_mode, end_date=end_date,
                ).errors:
                    if not (e["code"] == "required" and additional and end_date is None):
                        check.error(e["field"], e["message"], e["code"])
                pending = PersonnelAction.objects.filter(
                    employee=employee, action_type__effect=Effect.SCHEDULE, status=Status.PENDING
                ).exclude(pk=getattr(instance, "pk", None)).first()
                if pending:
                    check.warn(None, f"El empleado tiene otra AP de horario en aprobación ({pending.folio}, efectiva {fmt(pending.effective_date)}).", "pending_schedule")
    elif action_type.effect == Effect.SALARY:
        amount = values.get("new_base_salary", (None, None))[1]
        if "new_base_salary" not in values:
            check.error(None, f"El tipo «{action_type.name}» ajusta el salario pero no tiene el campo «new_base_salary». Corríjalo en /admin/.", "config")
        elif amount is not None and amount <= 0:
            check.error("values.new_base_salary", "El nuevo salario debe ser mayor que cero.")
        elif amount is not None and amount == employee.base_salary:
            check.warn("values.new_base_salary", "El nuevo salario es igual al salario actual.", "same_salary")
    return check


# ================================================================ sello y firmas
def content_payload(action: PersonnelAction) -> dict:
    values = {v.attribute.key: _json_safe(v.value) for v in action.values.select_related("attribute").all()}
    return {
        "folio": action.folio, "type": action.action_type.code, "employee": action.employee.employee_code,
        "effective_date": action.effective_date.isoformat(), "justification": action.justification,
        "values": dict(sorted(values.items())),
    }


def compute_content_hash(action: PersonnelAction) -> str:
    text = json.dumps(content_payload(action), sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hmac(action: PersonnelAction, sig: ActionSignature) -> str:
    message = "|".join([
        action.folio, str(sig.step_order), str(sig.signer_id or ""), sig.signer_username, sig.signer_role,
        sig.decision, sig.signed_at.isoformat(), sig.content_hash,
    ])
    key = hashlib.sha256(f"metamorph-pa-signature:{settings.SECRET_KEY}".encode()).digest()
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()


def verify(action: PersonnelAction) -> dict:
    """Integridad: el contenido coincide con el sello y cada firma verifica (HMAC)."""
    if action.status == Status.DRAFT:
        return {"sealed": False, "valid": True, "content_ok": True, "signatures": []}
    current = compute_content_hash(action)
    content_ok = current == action.content_hash
    sigs = []
    for sig in action.signatures.all():
        ok = sig.content_hash == current and hmac.compare_digest(sig.signature, _hmac(action, sig))
        sigs.append({"step_order": sig.step_order, "valid": ok})
    return {"sealed": True, "valid": content_ok and all(s["valid"] for s in sigs), "content_ok": content_ok,
            "content_hash": action.content_hash, "signatures": sigs}


def next_step(action: PersonnelAction):
    signed = {s.step_order for s in action.signatures.all()}
    return next((s for s in action.action_type.steps.all() if s.order not in signed), None)


def sign_block_reason(action: PersonnelAction, user) -> str | None:
    if action.status != Status.PENDING:
        return "La AP no está en aprobación."
    step = next_step(action)
    if step is None:
        return "La AP ya no tiene pasos pendientes."
    if not can_view_type(user, action.action_type):
        return "Su rol no puede ver este tipo de AP."
    if not can_sign_role(user, step.role):
        return f"El paso «{step.label}» lo firma el rol {step.get_role_display()}."
    if action.action_type.require_distinct_signers and action.signatures.filter(signer=user).exists():
        return "Este tipo de AP exige firmantes distintos: usted ya firmó un paso."
    return None


# ================================================================ operaciones
def _save_values(action: PersonnelAction, values: dict) -> None:
    action.values.all().delete()
    rows = []
    for attr, value in values.values():
        if value is None:
            continue
        v = ActionValue(action=action, attribute=attr)
        if attr.data_type in (DataType.INTEGER, DataType.DECIMAL):
            v.value_decimal = value
        elif attr.data_type == DataType.DATE:
            v.value_date = value
        elif attr.data_type == DataType.BOOLEAN:
            v.value_bool = value
        elif attr.data_type == DataType.SCHEDULE:
            v.value_json = value
        else:
            v.value_text = value
        rows.append(v)
    ActionValue.objects.bulk_create(rows)


@transaction.atomic
def create(check: Check, *, user=None, request=None, submit_now: bool = False) -> PersonnelAction:
    c = check.cleaned
    t: ActionType = c["action_type"]
    action = PersonnelAction.objects.create(
        folio=next_folio(t.folio_prefix, c["effective_date"] if t.is_initial_schedule else timezone.localdate()),
        action_type=t, employee=c["employee"], effective_date=c["effective_date"], justification=c["justification"],
        is_initial=t.is_initial_schedule, created_by=user if getattr(user, "pk", None) else None,
    )
    _save_values(action, c["values"])
    record("personnel_action_created", Category.PERSONNEL_ACTIONS,
           f"AP {action.folio} «{t.name}» elaborada para {action.employee.employee_code} (efectiva {fmt(action.effective_date)}).",
           request=request, actor=user, target=action.employee, details={"folio": action.folio, "type": t.code})
    if submit_now:
        submit(action, user=user, request=request)
    return action


@transaction.atomic
def update_draft(action: PersonnelAction, check: Check, *, user=None, request=None) -> PersonnelAction:
    if action.status != Status.DRAFT:
        raise ActionError("Solo se editan las AP en borrador.", "not_draft")
    c = check.cleaned
    action.effective_date, action.justification = c["effective_date"], c["justification"]
    action.save(update_fields=["effective_date", "justification", "updated_at"])
    _save_values(action, c["values"])
    record("personnel_action_updated", Category.PERSONNEL_ACTIONS, f"AP {action.folio} (borrador) modificada.",
           request=request, actor=user, target=action.employee, details={"folio": action.folio})
    return action


@transaction.atomic
def submit(action: PersonnelAction, *, user=None, request=None) -> PersonnelAction:
    if action.status != Status.DRAFT:
        raise ActionError("Solo se envían a aprobación las AP en borrador.", "not_draft")
    data = {"effective_date": action.effective_date, "justification": action.justification,
            "values": {v.attribute.key: _json_safe(v.value) for v in action.values.select_related("attribute")}}
    check = validate(action.action_type, action.employee, data, instance=action, for_initial=True)
    if not check.ok:
        raise ActionError("La AP ya no es válida: " + " ".join(e["message"] for e in check.errors), "invalid")
    action.status = Status.PENDING
    action.submitted_at = timezone.now()
    action.content_hash = compute_content_hash(action)
    action.save(update_fields=["status", "submitted_at", "content_hash", "updated_at"])
    record("personnel_action_submitted", Category.PERSONNEL_ACTIONS, f"AP {action.folio} enviada a aprobación.",
           request=request, actor=user, target=action.employee, details={"folio": action.folio, "content_hash": action.content_hash})
    steps = list(action.action_type.steps.all())
    if not steps:
        _approve(action, user=user, request=request)
    elif action.action_type.creator_signs_first_step and user is not None and can_sign_role(user, steps[0].role):
        sign(action, user=user, decision=Decision.APPROVED, comment="Elaborada y enviada a aprobación.", request=request)
    return action


@transaction.atomic
def sign(action: PersonnelAction, *, user, decision: str, comment: str = "", request=None) -> ActionSignature:
    action = PersonnelAction.objects.select_for_update().get(pk=action.pk)
    reason = sign_block_reason(action, user)
    if reason:
        raise ActionError(reason, "cannot_sign")
    if decision not in Decision.values:
        raise ActionError("Decisión inválida (APPROVED o REJECTED).")
    comment = (comment or "").strip()[:500]
    if decision == Decision.REJECTED and not comment:
        raise ActionError("Indique el motivo del rechazo.", "comment_required")
    current = compute_content_hash(action)
    if current != action.content_hash:
        raise ActionError("El contenido de la AP no coincide con su sello: no se puede firmar. Revise el registro de auditoría.", "tampered")
    step = next_step(action)
    sig = ActionSignature(
        action=action, step_order=step.order, step_label=step.label, required_role=step.role, signer=user,
        signer_username=user.username, signer_name=(user.get_full_name() or "")[:200], signer_role=user.effective_role,
        decision=decision, comment=comment, signed_at=timezone.now().replace(microsecond=0), content_hash=current,
    )
    sig.signature = _hmac(action, sig)
    sig.save()
    verb = "aprobó" if decision == Decision.APPROVED else "rechazó"
    record(f"personnel_action_{decision.lower()}_step", Category.PERSONNEL_ACTIONS,
           f"{user.username} ({user.get_effective_role_display() if hasattr(user, 'get_effective_role_display') else user.effective_role}) "
           f"{verb} el paso {step.order} «{step.label}» de la AP {action.folio}.",
           request=request, actor=user, target=action.employee, details={"folio": action.folio, "step": step.order, "decision": decision})
    if decision == Decision.REJECTED:
        action.status, action.decided_at = Status.REJECTED, timezone.now()
        action.save(update_fields=["status", "decided_at", "updated_at"])
    elif next_step(action) is None:
        _approve(action, user=user, request=request)
    return sig


def _approve(action: PersonnelAction, *, user=None, request=None) -> None:
    action.status, action.decided_at = Status.APPROVED, timezone.now()
    action.save(update_fields=["status", "decided_at", "updated_at"])
    record("personnel_action_approved", Category.PERSONNEL_ACTIONS, f"AP {action.folio} aprobada.",
           request=request, actor=user, target=action.employee, details={"folio": action.folio})
    apply_effect(action, user=user, request=request)


def apply_effect(action: PersonnelAction, *, user=None, request=None, today: date | None = None) -> bool:
    """Ejecuta el efecto de una AP aprobada. Devuelve True si quedó aplicada."""
    from apps.scheduling import services as sch

    if action.status != Status.APPROVED or action.applied_at:
        return False
    effect = action.action_type.effect
    values = {v.attribute.key: v for v in action.values.select_related("attribute")}
    today = today or timezone.localdate()
    if effect == Effect.SCHEDULE:
        schedule = next((v.value_json for v in values.values() if v.attribute.data_type == DataType.SCHEDULE), None)
        mode = action.action_type.schedule_mode
        end_date = values[END_DATE_KEY].value_date if mode == ScheduleMode.ADDITIONAL and END_DATE_KEY in values else None
        try:
            assignment = sch.apply_schedule(action.employee, schedule, action.effective_date, action=action, user=user,
                                            mode=mode, end_date=end_date)
        except ValueError as exc:
            raise ActionError(f"No se pudo aplicar el horario de la AP {action.folio}: {exc}", "apply_failed") from None
        summary = (f"Horario de la AP {action.folio} vigente desde el {fmt(assignment.effective_start_date)}"
                   + (f" hasta el {fmt(assignment.effective_end_date)} (asignación adicional)." if mode == ScheduleMode.ADDITIONAL else "."))
    elif effect == Effect.SALARY:
        if action.effective_date > today:
            return False  # se aplica en su fecha (apply_due_actions)
        amount = values["new_base_salary"].value_decimal
        Employee.objects.filter(pk=action.employee_id).update(base_salary=amount)
        summary = f"Salario base de {action.employee.employee_code} actualizado por la AP {action.folio}."
    else:
        summary = f"AP {action.folio} registrada (sin efecto automático)."
    action.applied_at = timezone.now()
    action.save(update_fields=["applied_at", "updated_at"])
    record("personnel_action_applied", Category.PERSONNEL_ACTIONS, summary, request=request, actor=user,
           target=action.employee, details={"folio": action.folio, "effect": effect})
    return True


def apply_due_actions(today: date | None = None) -> list[str]:
    """Aplica las AP aprobadas cuyo efecto esperaba su fecha efectiva (p. ej. ajustes salariales futuros)."""
    today = today or timezone.localdate()
    done = []
    for action in PersonnelAction.objects.filter(status=Status.APPROVED, applied_at__isnull=True, effective_date__lte=today).select_related("action_type", "employee"):
        with transaction.atomic():
            if apply_effect(action, today=today):
                done.append(action.folio)
    return done


@transaction.atomic
def cancel(action: PersonnelAction, *, user, reason: str, request=None) -> PersonnelAction:
    if action.status not in (Status.DRAFT, Status.PENDING):
        raise ActionError("Solo se anulan AP en borrador o en aprobación; una AP aprobada se corrige con otra AP.", "not_cancellable")
    reason = (reason or "").strip()
    if not reason:
        raise ActionError("Indique el motivo de la anulación.", "reason_required")
    action.status, action.cancel_reason, action.decided_at = Status.CANCELLED, reason[:500], timezone.now()
    action.save(update_fields=["status", "cancel_reason", "decided_at", "updated_at"])
    record("personnel_action_cancelled", Category.PERSONNEL_ACTIONS, f"AP {action.folio} anulada: {reason[:200]}",
           request=request, actor=user, target=action.employee, details={"folio": action.folio})
    return action


# ================================================================ alta de empleados
def initial_type() -> ActionType | None:
    return ActionType.objects.filter(is_initial_schedule=True, is_active=True).first()


def validate_initial_schedule(raw, *, country_id: int, hire_date: date) -> tuple[dict | None, list[dict]]:
    """Horario de la Primera AP en el alta (JSON o «L-V 08:00-17:00 60»)."""
    from apps.scheduling import services as sch

    if initial_type() is None:
        return None, [{"field": "schedule", "message": "No hay un tipo de AP fundacional de horario activo: configúrelo en /admin/."}]
    if raw is None or (isinstance(raw, str) and not raw.strip()) or raw == {}:
        return None, [{"field": "schedule", "message": (
            "Falta el horario de la Primera AP de asignación de horario: ningún colaborador queda activo sin su AP "
            "fundacional de turno (p. ej. «L-V 08:00-17:00 60»)."
        )}]
    definition, errors = sch.evaluate_schedule(raw, country_id=country_id, on=hire_date)
    return definition, [{"field": str(e.get("field") or "schedule").replace("definition", "schedule", 1), "message": e["message"]} for e in errors]


def create_initial_schedule_action(employee: Employee, definition: dict, *, user=None, request=None,
                                   justification: str = "") -> PersonnelAction:
    """Primera AP de asignación de horario del alta: se crea, se envía y, si la cadena lo permite, se aprueba."""
    t = initial_type()
    attr = t.attributes.filter(data_type=DataType.SCHEDULE, is_active=True).first()
    data = {
        "effective_date": employee.hire_date,
        "justification": justification or f"Alta del colaborador {employee.full_name}: asignación de horario inicial.",
        "values": {attr.key: definition},
    }
    check = validate(t, employee, data, for_initial=True)
    if not check.ok:
        raise ActionError(" ".join(e["message"] for e in check.errors), "invalid")
    return create(check, user=user, request=request, submit_now=True)


def employees_missing_initial(qs=None):
    """Empleados activos sin Primera AP de horario viva (borrador, en aprobación o aprobada)."""
    qs = qs if qs is not None else Employee.objects.all()
    live = PersonnelAction.objects.filter(is_initial=True, status__in=OPEN_STATUSES).values("employee_id")
    return qs.filter(employment_status=Employee.Status.ACTIVE).exclude(pk__in=live)


# ================================================================ serialización
def action_dict(action: PersonnelAction, user, *, detail: bool = False) -> dict:
    from apps.scheduling import services as sch

    t = action.action_type
    values = {v.attribute_id: v for v in action.values.all()}
    steps, signatures = list(t.steps.all()), {s.step_order: s for s in action.signatures.all()}
    nxt = next((s for s in steps if s.order not in signatures), None) if action.status == Status.PENDING else None
    body = {
        "folio": action.folio, "action_type": t.code, "action_type_name": t.name, "category": t.category,
        "category_label": t.get_category_display(), "effect": t.effect, "is_initial": action.is_initial,
        "schedule_mode": t.schedule_mode if t.effect == Effect.SCHEDULE else None,
        "employee_code": action.employee.employee_code, "full_name": action.employee.full_name,
        "country": action.employee.country.country_code, "effective_date": action.effective_date,
        "justification": action.justification, "status": action.status, "status_label": action.get_status_display(),
        "created_by": action.created_by.username if action.created_by_id and action.created_by else None,
        "created_at": action.created_at, "submitted_at": action.submitted_at, "decided_at": action.decided_at,
        "applied_at": action.applied_at, "cancel_reason": action.cancel_reason,
        "next_step": {"order": nxt.order, "label": nxt.label, "role": nxt.role, "role_label": nxt.get_role_display()} if nxt else None,
        "steps_total": len(steps), "steps_signed": len(signatures),
    }
    if not detail:
        return body
    attrs = list(t.attributes.all())
    out_values = []
    for attr in attrs:
        v = values.get(attr.pk)
        value = v.value if v else None
        item = {"key": attr.key, "label": attr.label, "data_type": attr.data_type, "value": _json_safe(value),
                "display": display_value(attr, value)}
        if attr.data_type == DataType.SCHEDULE and value:
            item["schedule"] = sch.schedule_summary(value)
        out_values.append(item)
    body["values"] = out_values
    body["steps"] = [{
        "order": s.order, "label": s.label, "role": s.role, "role_label": s.get_role_display(),
        "signature": ({
            "signer": sig.signer_username, "signer_name": sig.signer_name, "signer_role": sig.signer_role,
            "decision": sig.decision, "decision_label": sig.get_decision_display(), "comment": sig.comment,
            "signed_at": sig.signed_at, "signature": sig.signature,
        } if (sig := signatures.get(s.order)) else None),
        "is_next": nxt is not None and nxt.order == s.order,
    } for s in steps]
    body["integrity"] = verify(action)
    perms = user_permissions(user)
    body["can_edit"] = action.status == Status.DRAFT and can_create_type(user, t)
    body["can_submit"] = body["can_edit"]
    body["can_cancel"] = action.status in (Status.DRAFT, Status.PENDING) and can_create_type(user, t)
    body["sign_block_reason"] = sign_block_reason(action, user) if action.status == Status.PENDING else None
    body["can_sign"] = action.status == Status.PENDING and body["sign_block_reason"] is None
    body["can_view_employee"] = "hcm.view" in perms
    return body


def type_dict(t: ActionType, user) -> dict:
    return {
        "code": t.code, "name": t.name, "description": t.description, "category": t.category,
        "category_label": t.get_category_display(), "effect": t.effect, "effect_label": t.get_effect_display(),
        "folio_prefix": t.folio_prefix, "is_initial_schedule": t.is_initial_schedule, "is_active": t.is_active,
        "schedule_mode": t.schedule_mode if t.effect == Effect.SCHEDULE else None,
        "schedule_mode_label": t.get_schedule_mode_display() if t.effect == Effect.SCHEDULE else None,
        "can_create": can_create_type(user, t) and t.is_active,
        "attributes": [{
            "key": a.key, "label": a.label, "data_type": a.data_type, "required": a.required, "options": a.option_list(),
            "help_text": a.help_text, "min_value": a.min_value, "max_value": a.max_value, "max_length": a.max_length,
        } for a in t.attributes.all() if a.is_active],
        "steps": [{"order": s.order, "label": s.label, "role": s.role, "role_label": s.get_role_display()} for s in t.steps.all()],
        "creator_signs_first_step": t.creator_signs_first_step, "require_distinct_signers": t.require_distinct_signers,
    }


_FOLIO = re.compile(r"^[A-Z]{2,6}-\d{4}-\d{6}$")


def is_folio(text: str) -> bool:
    return bool(_FOLIO.match(text or ""))


def search_filter(term: str) -> Q:
    return (Q(folio__icontains=term) | Q(employee__employee_code__icontains=term) | Q(employee__first_name__icontains=term)
            | Q(employee__last_name__icontains=term) | Q(justification__icontains=term))
