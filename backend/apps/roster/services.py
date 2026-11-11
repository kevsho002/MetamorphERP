"""Reglas del roster temporal: validar y aplicar cambios con fecha efectiva.

Semántica de un cambio «atributo = valor desde D»:
* Si hay un intervalo vigente que cubre D, se corta en D-1 y el nuevo valor ocupa
  desde D hasta el fin que tenía ese intervalo (o «Now»).
* Si en D no había valor, el nuevo valor dura hasta el siguiente cambio programado
  (o «Now»): así se pueden registrar cambios futuros y retroactivos sin pisarlos.
* Quitar un valor desde D cierra el intervalo que cubre D en D-1.
* Nada se borra: la fila anterior queda marcada como reemplazada (superseded_at)
  y se crean las filas nuevas. Así los reportes de WFM, RRHH y QA son reproducibles.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.hcm.models import Employee
from apps.roster.models import DataType, RosterAssignment, RosterAttribute, RosterDimensionItem

ONE_DAY = timedelta(days=1)
TRUE_WORDS = {"true", "1", "si", "sí", "s", "yes", "y", "verdadero", "x"}
FALSE_WORDS = {"false", "0", "no", "n", "falso"}


def fmt(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "Now"


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().strip().upper()


def parse_any_date(value) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    parsed = parse_date(text)
    if parsed is None and re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", text):
        d, m, y = (int(p) for p in text.split("/"))
        try:
            parsed = date(y, m, d)
        except ValueError:
            return None
    return parsed


class RosterValueError(Exception):
    def __init__(self, message: str, code: str = "invalid_value"):
        super().__init__(message)
        self.message = message
        self.code = code


# --------------------------------------------------------------------- definiciones
def active_attributes() -> list[RosterAttribute]:
    return list(
        RosterAttribute.objects.filter(is_active=True).select_related("dimension", "dimension__parent", "depends_on")
    )


def coerce(attribute: RosterAttribute, raw, *, country_id: int | None) -> tuple[str, RosterDimensionItem | None, str]:
    """Valor recibido -> (forma canónica, elemento de dimensión, etiqueta legible)."""
    rules = attribute.rules or {}
    text = str(raw).strip() if raw is not None else ""
    kind = attribute.data_type
    if kind == DataType.DIMENSION:
        items = RosterDimensionItem.objects.filter(dimension_id=attribute.dimension_id).select_related("parent", "country")
        item = items.filter(code__iexact=text).first()
        if item is None:
            folded = _fold(text)
            item = next((i for i in items if _fold(i.name) == folded), None)
        if item is None:
            raise RosterValueError(f"«{text}» no existe en {attribute.dimension.name}.", "unknown_item")
        if not item.is_active:
            raise RosterValueError(f"«{item.name}» está inactivo en {attribute.dimension.name}.", "inactive_item")
        if item.country_id and country_id and item.country_id != country_id:
            raise RosterValueError(
                f"«{item.name}» es de {item.country.country_name} y no aplica al país del empleado.", "wrong_country"
            )
        return item.code, item, item.name
    if kind == DataType.DATE:
        parsed = parse_any_date(text)
        if parsed is None:
            raise RosterValueError(f"«{text}» no es una fecha válida (use AAAA-MM-DD o DD/MM/AAAA).", "invalid_date")
        return parsed.isoformat(), None, fmt(parsed)
    if kind == DataType.INTEGER:
        if not re.fullmatch(r"-?\d+", text):
            raise RosterValueError(f"«{text}» no es un número entero.", "invalid_integer")
        number = int(text)
        if "min" in rules and number < int(rules["min"]):
            raise RosterValueError(f"El mínimo es {rules['min']}.", "min")
        if "max" in rules and number > int(rules["max"]):
            raise RosterValueError(f"El máximo es {rules['max']}.", "max")
        return str(number), None, str(number)
    if kind == DataType.BOOLEAN:
        lowered = text.lower()
        if lowered in TRUE_WORDS:
            return "true", None, "Sí"
        if lowered in FALSE_WORDS:
            return "false", None, "No"
        raise RosterValueError(f"«{text}» no es Sí/No.", "invalid_boolean")
    if kind == DataType.CHOICE:
        match = next((c for c in attribute.choices if _fold(c) == _fold(text)), None)
        if match is None:
            raise RosterValueError(f"«{text}» no es una opción válida. Opciones: {', '.join(attribute.choices)}.", "invalid_choice")
        return match, None, match
    # STRING
    max_length = int(rules.get("max_length", 500))
    if len(text) > max_length:
        raise RosterValueError(f"Máximo {max_length} caracteres.", "max_length")
    if rules.get("pattern") and not re.fullmatch(rules["pattern"], text):
        hint = f" ({rules['pattern_message']})" if rules.get("pattern_message") else ""
        example = f" Ejemplo válido: {rules['example']}." if rules.get("example") else ""
        raise RosterValueError(f"Formato inválido{hint}.{example}", "invalid_format")
    return text, None, text


def label_of(row: RosterAssignment) -> str:
    attribute = row.attribute
    if attribute.data_type == DataType.DIMENSION:
        return row.item.name if row.item_id else row.value
    if attribute.data_type == DataType.DATE:
        return fmt(parse_date(row.value))
    if attribute.data_type == DataType.BOOLEAN:
        return "Sí" if row.value == "true" else "No"
    return row.value


# --------------------------------------------------------------------- lectura temporal
def current_rows(employee: Employee, attribute_ids=None) -> list[RosterAssignment]:
    qs = RosterAssignment.objects.current().filter(employee=employee).select_related("attribute", "item", "item__parent")
    if attribute_ids is not None:
        qs = qs.filter(attribute_id__in=attribute_ids)
    return list(qs.order_by("attribute_id", "effective_start"))


def covering(rows, attribute_id: int, on: date) -> RosterAssignment | None:
    for row in rows:
        if row.attribute_id == attribute_id and row.effective_start <= on and (row.effective_end is None or row.effective_end >= on):
            return row
    return None


def next_after(rows, attribute_id: int, on: date) -> RosterAssignment | None:
    later = [r for r in rows if r.attribute_id == attribute_id and r.effective_start > on]
    return min(later, key=lambda r: r.effective_start) if later else None


def interval_payload(row: RosterAssignment) -> dict:
    return {
        "id": row.pk,
        "value": row.value,
        "label": label_of(row),
        "item_parent": row.item.parent.code if row.item_id and row.item.parent_id else None,
        "effective_start": row.effective_start,
        "effective_end": row.effective_end,
        "is_now": row.effective_end is None,
        "reason": row.reason,
        "recorded_at": row.recorded_at,
        "recorded_by": row.recorded_by,
        "superseded_at": row.superseded_at,
        "superseded_by": row.superseded_by or None,
    }


def snapshot(employee: Employee, on: date, attributes: list[RosterAttribute] | None = None) -> list[dict]:
    attributes = attributes if attributes is not None else active_attributes()
    rows = current_rows(employee)
    result = []
    for attribute in attributes:
        row = covering(rows, attribute.pk, on)
        upcoming = next_after(rows, attribute.pk, on)
        result.append(
            {
                "code": attribute.code,
                "current": interval_payload(row) if row else None,
                "next": interval_payload(upcoming) if upcoming else None,
                "intervals": sum(1 for r in rows if r.attribute_id == attribute.pk),
            }
        )
    return result


# --------------------------------------------------------------------- plan de cambios
@dataclass
class Change:
    attribute: RosterAttribute
    action: str  # set | clear | unchanged
    value: str | None = None
    item: RosterDimensionItem | None = None
    label: str | None = None
    previous: RosterAssignment | None = None

    def as_dict(self) -> dict:
        return {
            "attribute": self.attribute.code,
            "attribute_name": self.attribute.name,
            "action": self.action,
            "value": self.value,
            "label": self.label,
            "previous": label_of(self.previous) if self.previous else None,
            "previous_since": self.previous.effective_start if self.previous else None,
        }


@dataclass
class RosterPlan:
    employee: Employee
    effective_date: date | None
    reason: str
    changes: list[Change] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def effective_changes(self) -> list[Change]:
        return [c for c in self.changes if c.action in ("set", "clear")]

    def error(self, code: str, message: str, field_name: str | None = None) -> None:
        self.errors.append({"field": field_name, "code": code, "message": message})

    def warn(self, code: str, message: str, field_name: str | None = None) -> None:
        self.warnings.append({"field": field_name, "code": code, "message": message})


def _numbered(messages: list[dict]) -> str:
    return " ".join(f"{i}) {m['message']}" for i, m in enumerate(messages, 1))


def feedback(plan: RosterPlan, *, dry_run: bool) -> str:
    code = plan.employee.employee_code
    if not plan.ok:
        n = len(plan.errors)
        return f"No se guardaron los cambios del roster de {code} por {n} error{'es' if n != 1 else ''}: {_numbered(plan.errors)}"
    changes = plan.effective_changes
    if not changes:
        text = f"No hay cambios que registrar en el roster de {code}: los valores ya estaban vigentes."
    else:
        parts = []
        for c in changes:
            before = f" (antes: {label_of(c.previous)})" if c.previous else ""
            parts.append(f"{c.attribute.name}: {c.label if c.action == 'set' else 'sin valor'}{before}")
        n = len(changes)
        verb = "son válidos" if dry_run else "se registraron"
        text = (
            f"{n} cambio{'s' if n != 1 else ''} del roster de {code} {verb}, vigente{'s' if n != 1 else ''} desde "
            f"{fmt(plan.effective_date)}: {'; '.join(parts)}."
        )
        if dry_run:
            text += " No se guardaron porque es una validación previa."
    if plan.warnings:
        text += f" Advertencia{'s' if len(plan.warnings) != 1 else ''}: {_numbered(plan.warnings)}"
    return text


def plan_changes(employee: Employee, data: dict) -> RosterPlan:
    """Valida {effective_date, reason, values: {código: valor | null}} sin escribir nada."""
    effective = parse_any_date(data.get("effective_date"))
    reason = str(data.get("reason") or "").strip()
    plan = RosterPlan(employee=employee, effective_date=effective, reason=reason[:300])
    if effective is None:
        plan.error("required", "Indique la fecha efectiva del cambio (AAAA-MM-DD).", "effective_date")
    if len(reason) > 300:
        plan.error("max_length", "El motivo admite 300 caracteres.", "reason")
    values = data.get("values")
    if not isinstance(values, dict) or not values:
        plan.error("required", "Envíe al menos un atributo en «values» ({código: valor}).", "values")
        return plan
    if effective is not None:
        if effective < employee.hire_date:
            plan.error(
                "before_hire",
                f"La fecha efectiva {fmt(effective)} es anterior al ingreso del empleado ({fmt(employee.hire_date)}).",
                "effective_date",
            )
        if employee.termination_date and effective > employee.termination_date:
            plan.error(
                "after_termination",
                f"El empleado se retiró el {fmt(employee.termination_date)}: no se registran asignaciones posteriores.",
                "effective_date",
            )
    if not plan.ok:
        return plan

    attributes = {a.code: a for a in active_attributes()}
    rows = current_rows(employee)
    for code, raw in values.items():
        attribute = attributes.get(code)
        if attribute is None:
            exists = RosterAttribute.objects.filter(code=code).exists()
            plan.error("unknown_attribute", f"«{code}» {'está inactivo' if exists else 'no es un atributo del roster'}.", code)
            continue
        previous = covering(rows, attribute.pk, effective)
        if raw is None or str(raw).strip() == "":
            if previous is None:
                plan.warn("nothing_to_clear", f"«{attribute.name}» no tenía valor al {fmt(effective)}.", code)
                plan.changes.append(Change(attribute, "unchanged"))
            else:
                plan.changes.append(Change(attribute, "clear", previous=previous))
            continue
        try:
            canonical, item, label = coerce(attribute, raw, country_id=employee.country_id)
        except RosterValueError as exc:
            plan.error(exc.code, f"«{attribute.name}»: {exc.message}", code)
            continue
        action = "unchanged" if previous is not None and previous.value == canonical else "set"
        plan.changes.append(Change(attribute, action, canonical, item, label, previous))

    if plan.ok:
        _check_consistency(plan, attributes, rows)
    return plan


def _state_after(plan: RosterPlan, rows) -> dict[str, tuple[str | None, RosterDimensionItem | None]]:
    """Valores de cada atributo en la fecha efectiva tras aplicar el plan."""
    state = {}
    for row in rows:
        if row.effective_start <= plan.effective_date and (row.effective_end is None or row.effective_end >= plan.effective_date):
            state[row.attribute.code] = (row.value, row.item)
    for change in plan.changes:
        if change.action == "set":
            state[change.attribute.code] = (change.value, change.item)
        elif change.action == "clear":
            state.pop(change.attribute.code, None)
    return state


def _check_consistency(plan: RosterPlan, attributes: dict[str, RosterAttribute], rows) -> None:
    state = _state_after(plan, rows)
    touched = {c.attribute.code for c in plan.effective_changes}
    for attribute in attributes.values():
        # Jerarquía: la marca debe pertenecer al cliente vigente, la sub-línea a su línea...
        parent = attribute.depends_on
        if parent is not None and (attribute.code in touched or parent.code in touched):
            value, item = state.get(attribute.code, (None, None))
            if value is not None:
                parent_value, parent_item = state.get(parent.code, (None, None))
                if parent_item is None:
                    plan.error(
                        "missing_parent",
                        f"Para asignar «{attribute.name}» primero debe tener «{parent.name}» vigente al {fmt(plan.effective_date)}.",
                        attribute.code,
                    )
                elif item is not None and item.parent_id != parent_item.pk:
                    plan.error(
                        "parent_mismatch",
                        f"«{item.name}» no pertenece a {parent.name.lower()} «{parent_item.name}». "
                        f"Actualice o quite «{attribute.name}» en el mismo cambio.",
                        attribute.code,
                    )
        # Secuencia de fechas clave (Inicio de training <= Nesting <= Fin de nesting <= Operaciones).
        rules = attribute.rules or {}
        for key, op in (("not_before", "before"), ("not_after", "after")):
            ref_code = rules.get(key)
            if not ref_code or (attribute.code not in touched and ref_code not in touched):
                continue
            mine, ref = state.get(attribute.code, (None, None))[0], state.get(ref_code, (None, None))[0]
            if mine and ref:
                ref_attr = attributes.get(ref_code)
                ref_name = ref_attr.name if ref_attr else ref_code
                if op == "before" and mine < ref:
                    plan.error(
                        "date_order",
                        f"«{attribute.name}» ({fmt(parse_date(mine))}) no puede ser anterior a «{ref_name}» ({fmt(parse_date(ref))}).",
                        attribute.code,
                    )
                if op == "after" and mine > ref:
                    plan.error(
                        "date_order",
                        f"«{attribute.name}» ({fmt(parse_date(mine))}) no puede ser posterior a «{ref_name}» ({fmt(parse_date(ref))}).",
                        attribute.code,
                    )


# --------------------------------------------------------------------- aplicación
def _supersede(row: RosterAssignment, actor: str, now) -> None:
    row.superseded_at = now
    row.superseded_by = actor[:150]
    row.save(update_fields=["superseded_at", "superseded_by"])


def _copy(row: RosterAssignment, *, end: date, change_id, actor: str) -> RosterAssignment:
    return RosterAssignment.objects.create(
        employee_id=row.employee_id, attribute_id=row.attribute_id, value=row.value, item_id=row.item_id,
        effective_start=row.effective_start, effective_end=end, reason=row.reason, change_id=change_id,
        recorded_by=actor[:150],
    )


@transaction.atomic
def apply_plan(plan: RosterPlan, actor: str) -> uuid.UUID:
    """Escribe el plan validado. El llamador debe haber bloqueado al empleado (select_for_update)."""
    if not plan.ok:
        raise ValueError("apply_plan requiere un plan sin errores")
    change_id = uuid.uuid4()
    now = timezone.now()
    on = plan.effective_date
    for change in plan.effective_changes:
        rows = current_rows(plan.employee, [change.attribute.pk])
        cov = covering(rows, change.attribute.pk, on)
        upcoming = next_after(rows, change.attribute.pk, on)
        if cov is not None:
            new_end = cov.effective_end
            _supersede(cov, actor, now)
            if cov.effective_start < on:
                _copy(cov, end=on - ONE_DAY, change_id=change_id, actor=actor)
        else:
            new_end = upcoming.effective_start - ONE_DAY if upcoming else None
        if change.action == "set":
            RosterAssignment.objects.create(
                employee=plan.employee, attribute=change.attribute, value=change.value, item=change.item,
                effective_start=on, effective_end=new_end, reason=plan.reason, change_id=change_id,
                recorded_by=actor[:150],
            )
    return change_id
