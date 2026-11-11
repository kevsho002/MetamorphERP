"""Fase 4 — Edición individual de un empleado (PATCH) con las mismas reglas del alta.

Flujo:
1. Se combina el registro actual (campos base + atributos EAV) con los cambios
   recibidos (semántica PATCH: lo que no se envía se conserva; "" borra un dato opcional).
2. El resultado se valida con `validate_employee_payload` contra la plantilla del
   país vigente a la fecha de ingreso (excluyendo al propio empleado de los
   controles de duplicados).
3. Estado laboral y fecha de terminación se validan aparte (no pertenecen a la plantilla).
4. Si todo es válido se guarda: hcm.Employee + upsert de valores EAV.

Reglas fijas: el país y el ID corporativo no se editan (el ID depende del país);
un traslado de país es una baja + un alta nueva. Concurrencia optimista con
ROWVERSION: si el cliente envía `row_version` y el registro cambió, se responde 409.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.accounts.permissions import user_permissions
from apps.accounts.roles import Perm
from apps.employees.batch import _numbered
from apps.employees.models import EmployeeAttributeValue
from apps.employees.schema import CORE_FIELDS, FieldValueError, is_blank, parse_date
from apps.employees.services import _CORE_MODEL_FIELDS
from apps.employees.validation import KEY_ALIASES, ValidatedRow, ValidationContext, normalize_key, validate_employee_payload
from apps.hcm.models import Employee

audit = logging.getLogger("apps.employees.audit")

STATUS_FIELDS = ("employment_status", "termination_date")
STATUS_SYNONYMS = {
    "ACTIVO": Employee.Status.ACTIVE,
    "INACTIVO": Employee.Status.INACTIVE,
    "SUSPENDIDO": Employee.Status.INACTIVE,
    "SUSPENDED": Employee.Status.INACTIVE,
    "TERMINADO": Employee.Status.TERMINATED,
    "RETIRADO": Employee.Status.TERMINATED,
}
_IGNORED_KEYS = {"employee_code", "row_version", "full_name", "country_name", "currency", "has_user_account"}


class StaleEmployeeError(Exception):
    """El empleado fue modificado por otra persona desde que se cargó el formulario."""


@dataclass
class UpdateOutcome:
    employee: Employee
    row: ValidatedRow
    saved: bool = False
    changes: list[str] = field(default_factory=list)  # etiquetas de los campos modificados
    status_values: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.row.ok


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    return str(value)


def employee_snapshot(employee: Employee) -> dict[str, Any]:
    """Datos actuales del empleado en la misma forma que acepta el formulario."""
    data = {key: _text(getattr(employee, key)) for key in _CORE_MODEL_FIELDS}
    data["cost_center"] = employee.cost_center.code if employee.cost_center_id else ""
    data["country"] = employee.country.country_code
    data["attributes"] = {v.attribute.code: v.value for v in employee.attribute_values.select_related("attribute")}
    return data


def _merge(employee: Employee, payload: dict, can_see_salary: bool) -> tuple[dict, set[str], list[tuple[str, str, str]]]:
    """Devuelve (payload combinado, atributos enviados por el usuario, errores previos [code, msg, field])."""
    merged = employee_snapshot(employee)
    attributes = dict(merged.pop("attributes"))
    sent_attributes: set[str] = set()
    problems: list[tuple[str, str, str]] = []
    for key, value in payload.items():
        nk = normalize_key(key)
        if nk in {"attributes", "atributos"} and isinstance(value, dict):
            for code, attr_value in value.items():
                attributes[normalize_key(code)] = attr_value
                sent_attributes.add(normalize_key(code))
            continue
        nk = KEY_ALIASES.get(nk, nk)
        if nk in _IGNORED_KEYS:
            continue
        if nk == "country":
            if not is_blank(value) and str(value).strip().upper() not in {
                employee.country.country_code.upper(), employee.country.country_name.upper()
            }:
                problems.append((
                    "country_immutable",
                    f"El país no se puede cambiar ({employee.country.country_name}): el ID corporativo "
                    f"{employee.employee_code} pertenece a ese país. Para un traslado, registre la terminación y cree un alta nueva.",
                    "country",
                ))
            continue
        if nk == "base_salary" and not can_see_salary:
            continue  # sin permiso de planilla el salario no se ve ni se modifica
        if nk in CORE_FIELDS or nk in STATUS_FIELDS:
            merged[nk] = value
        else:
            attributes[nk] = value
            sent_attributes.add(nk)
    merged["attributes"] = attributes
    return merged, sent_attributes, problems


def _validate_status(employee: Employee, merged: dict, row: ValidatedRow) -> dict[str, Any]:
    raw_status = merged.pop("employment_status", None)
    raw_termination = merged.pop("termination_date", None) if "termination_date" in merged else _text(employee.termination_date)
    status = employee.employment_status
    if not is_blank(raw_status):
        candidate = str(raw_status).strip().upper()
        candidate = STATUS_SYNONYMS.get(candidate, candidate)
        if candidate not in Employee.Status.values:
            labels = ", ".join(f"{c.label} ({c.value})" for c in Employee.Status)
            row.error("invalid_choice", f"«Estado laboral» con valor «{raw_status}» no es válido. Opciones: {labels}.", "employment_status")
        else:
            status = candidate
    termination = None
    if not is_blank(raw_termination):
        try:
            termination = parse_date(raw_termination)
        except FieldValueError as exc:
            row.error(exc.code, f"«Fecha de terminación»: {exc.message}", "termination_date")
            return {}
    hire = row.core.get("hire_date")
    if status == Employee.Status.TERMINATED and termination is None and not row.has_field_error("termination_date"):
        row.error("required", "Para marcar al empleado como Terminado indique la «Fecha de terminación».", "termination_date")
    elif status != Employee.Status.TERMINATED and termination is not None:
        row.error(
            "invalid_date",
            "Solo un empleado con estado «Terminado» puede tener fecha de terminación: borre la fecha o cambie el estado.",
            "termination_date",
        )
    elif termination and hire and termination < hire:
        row.error(
            "invalid_date",
            f"La fecha de terminación {termination:%d/%m/%Y} es anterior a la fecha de ingreso {hire:%d/%m/%Y}.",
            "termination_date",
        )
    account = getattr(employee, "user_account", None) if hasattr(employee, "user_account") else None
    if status == Employee.Status.TERMINATED and employee.employment_status != status and account is not None and account.is_active:
        row.warn(
            "linked_account",
            f"Al guardar la terminación se desactivará la cuenta de usuario vinculada «{account.username}» y se cerrarán sus sesiones.",
            "employment_status",
        )
    return {"employment_status": status, "termination_date": termination}


def _deactivate_linked_account(employee: Employee, user, row: ValidatedRow, request=None) -> None:
    """Terminación -> la cuenta vinculada deja de tener acceso (vínculo limpio empleado <-> usuario)."""
    from apps.accounts import services as account_services
    from apps.accounts.roles import can_manage_role

    account = getattr(employee, "user_account", None) if hasattr(employee, "user_account") else None
    if account is None or not account.is_active:
        return
    row.messages = [m for m in row.messages if m.code != "linked_account"]
    if account.pk == getattr(user, "pk", None):
        row.warn("linked_account", "La cuenta vinculada es la suya: no se desactivó. Pida a otro administrador hacerlo.", "employment_status")
        return
    if account.is_superuser or not can_manage_role(user.effective_role, account.effective_role):
        row.warn(
            "linked_account",
            f"La cuenta vinculada «{account.username}» tiene un rol que usted no administra: pida a un administrador desactivarla.",
            "employment_status",
        )
        return
    try:
        with transaction.atomic():
            account_services.set_active(user, account, active=False, request=request, reason="empleado terminado")
    except Exception as exc:  # p. ej. último administrador activo
        detail = getattr(exc, "detail", None) or str(exc)
        if isinstance(detail, dict):
            detail = detail.get("detail", detail)
        row.warn("linked_account", f"No se desactivó la cuenta «{account.username}»: {detail}", "employment_status")
        return
    row.warn("linked_account", f"Se desactivó la cuenta de usuario vinculada «{account.username}» y se cerraron sus sesiones.", "employment_status")


def _changes(employee: Employee, row: ValidatedRow, status_values: dict, before: dict) -> list[str]:
    labels = {k: f.label for k, f in (row.spec.fields.items() if row.spec else [])}
    changed: list[str] = []
    for key in _CORE_MODEL_FIELDS:
        if _text(row.core.get(key)) != before.get(key, ""):
            changed.append(labels.get(key, CORE_FIELDS[key].label))
    new_cc = row.cost_center.code if row.cost_center else ""
    if new_cc != before.get("cost_center", ""):
        changed.append(labels.get("cost_center", "Centro de costos"))
    new_attrs = {spec.key: canonical for spec, canonical in row.attributes}
    spec_attrs = row.spec.attributes if row.spec else {}
    for code, spec in spec_attrs.items():
        if new_attrs.get(code, "") != before["attributes"].get(code, ""):
            changed.append(spec.label)
    if status_values.get("employment_status") != employee.employment_status:
        changed.append("Estado laboral")
    if status_values.get("termination_date") != employee.termination_date:
        changed.append("Fecha de terminación")
    return changed


def process_update(
    employee: Employee, payload: dict, *, user, dry_run: bool = False, row_version: str | None = None, request=None
) -> UpdateOutcome:
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("process_update requiere una transacción activa (transaction.atomic)")
    if row_version and employee.row_ver is not None and bytes(employee.row_ver).hex() != str(row_version).lower():
        raise StaleEmployeeError
    can_see_salary = Perm.PAYROLL_VIEW in user_permissions(user)
    before = employee_snapshot(employee)
    merged, sent_attributes, problems = _merge(employee, payload, can_see_salary)
    status_raw = {k: merged.pop(k) for k in STATUS_FIELDS if k in merged}

    ctx = ValidationContext()
    row = validate_employee_payload(merged, ctx, existing=employee)
    for code, message, field_name in problems:
        row.error(code, message, field_name)
    # Atributos actuales que ya no usa la plantilla: se conservan sin advertir (no los envió el usuario).
    row.messages = [
        m for m in row.messages
        if not (m.code == "unknown_field" and m.field and m.field.startswith("attributes.")
                and m.field.split(".", 1)[1] not in sent_attributes)
    ]
    status_values = _validate_status(employee, {**status_raw}, row)
    outcome = UpdateOutcome(employee=employee, row=row, status_values=status_values)
    if not row.ok:
        return outcome
    outcome.changes = _changes(employee, row, status_values, before)
    if dry_run or not outcome.changes:
        return outcome

    actor = (getattr(user, "username", None) or "sistema")
    for key in _CORE_MODEL_FIELDS:
        setattr(employee, key, row.core.get(key))  # opcional borrado -> NULL
    employee.cost_center = row.cost_center
    employee.employment_status = status_values["employment_status"]
    employee.termination_date = status_values["termination_date"]
    employee.updated_at = timezone.now()
    employee.updated_by = actor[:100]
    employee.save(
        update_fields=[*_CORE_MODEL_FIELDS, "cost_center", "employment_status", "termination_date", "updated_at", "updated_by"]
    )
    kept = []
    for spec, canonical in row.attributes:
        EmployeeAttributeValue.objects.update_or_create(
            employee=employee,
            attribute=spec.attribute,
            defaults={"value": canonical, "template": row.template, "updated_by": actor[:150]},
        )
        kept.append(spec.attribute.pk)
    cleared = [spec.attribute.pk for spec in row.spec.attributes.values() if spec.attribute.pk not in kept]
    if cleared:
        EmployeeAttributeValue.objects.filter(employee=employee, attribute_id__in=cleared).delete()
    outcome.saved = True
    if employee.employment_status == Employee.Status.TERMINATED and "Estado laboral" in outcome.changes:
        _deactivate_linked_account(employee, user, row, request=request)
    audit.info(
        "employee_updated code=%s fields=%s by=%s", employee.employee_code, ",".join(outcome.changes), actor
    )
    return outcome


def update_feedback(outcome: UpdateOutcome, dry_run: bool) -> str:
    code = outcome.employee.employee_code
    row = outcome.row
    if not row.ok:
        n = len(row.errors)
        text = f"No se guardaron los cambios de {code} por {n} error{'es' if n != 1 else ''}: {_numbered(row.errors)}"
    elif not outcome.changes:
        text = f"No hay cambios que guardar en {code}."
    else:
        n = len(outcome.changes)
        fields = ", ".join(outcome.changes)
        if dry_run:
            text = (
                f"Los cambios son válidos ({n} campo{'s' if n != 1 else ''}: {fields}); "
                "no se guardaron porque es una validación previa."
            )
        else:
            text = f"Se actualizó el empleado {code}: {n} campo{'s' if n != 1 else ''} modificado{'s' if n != 1 else ''} ({fields})."
    if row.warnings:
        text += f" Advertencia{'s' if len(row.warnings) != 1 else ''}: {_numbered(row.warnings)}"
    return text
