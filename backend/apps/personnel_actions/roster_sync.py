"""Fase 22 — Automatización del roster mediante AP (ajuste salarial, promoción, cambio organizacional).

Al aplicarse una AP con efecto ROSTER (o SALARY), sus campos actualizan SIN intervención manual:

* el ROSTER temporal (roster_assignment): cada campo de tipo «Dato del roster» cuya clave es el código de un atributo
  (cliente, marca, línea / sub-línea, Team Manager, puesto, tipo de contrato…) se registra vigente desde la fecha
  efectiva, con el folio como motivo y el historial bitemporal del roster (la fila anterior se cierra el día previo);
* el EXPEDIENTE (hcm.Employee): «new_base_salary» → salario base; «cost_center» → centro de costos.

La validación de la AP hace un ensayo del plan del roster (mismas reglas que la pantalla del roster: catálogos,
país, jerarquía Cliente → Marca, etc.) para que los errores aparezcan al elaborar la AP y no al aprobarla.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.hcm.models import Employee
from apps.personnel_actions.dynamic_fields import COST_CENTER_KEY
from apps.personnel_actions.models import DataType

SALARY_KEY = "new_base_salary"


def _items(values: dict) -> list[tuple]:
    """[(attr, valor)] tanto para la validación ({key: (attr, v)}) como para la aplicación ({key: ActionValue})."""
    out = []
    for v in values.values():
        if isinstance(v, tuple):
            out.append(v)
        else:
            out.append((v.attribute, v.value))
    return out


def roster_changes(values: dict) -> dict[str, str]:
    return {attr.key: value for attr, value in _items(values)
            if attr.data_type == DataType.ROSTER and attr.key != COST_CENTER_KEY and value not in (None, "")}


def employee_changes(values: dict) -> dict:
    out = {}
    for attr, value in _items(values):
        if value in (None, ""):
            continue
        if attr.key == SALARY_KEY and attr.data_type == DataType.DECIMAL:
            out["base_salary"] = Decimal(value)
        elif attr.key == COST_CENTER_KEY:
            out["cost_center"] = value
    return out


def plan(employee: Employee, eff: date, values: dict, folio: str = ""):
    from apps.roster import services as roster

    changes = roster_changes(values)
    if not changes:
        return None
    return roster.plan_changes(employee, {"effective_date": eff.isoformat(), "reason": f"AP {folio}".strip() or "AP",
                                          "values": changes})


def validate(check, action_type, employee: Employee, eff: date | None, values: dict) -> None:
    roster = roster_changes(values)
    expediente = employee_changes(values)
    if not roster and not expediente:
        check.error(None, "Indique al menos un cambio (puesto, salario, cuenta, jerarquía o centro de costos).", "required")
        return
    if "base_salary" in expediente:
        amount = expediente["base_salary"]
        if amount <= 0:
            check.error(f"values.{SALARY_KEY}", "El nuevo salario debe ser mayor que cero.")
        elif amount == employee.base_salary:
            check.warn(f"values.{SALARY_KEY}", "El nuevo salario es igual al salario actual.", "same_salary")
    if eff is None or not check.ok:
        return
    p = plan(employee, eff, values)
    if p is not None:
        for e in p.errors:
            key = f"values.{e['field']}" if e.get("field") and e["field"] in roster else None
            check.error(key, f"Roster: {e['message']}", e["code"])
        for w in p.warnings:
            check.warn(None, f"Roster: {w['message']}", w["code"])
        if p.ok and not p.effective_changes and not expediente:
            check.warn(None, "Los valores del roster ya estaban vigentes en esa fecha: la AP no cambiará nada.", "no_changes")


def apply(action, values: dict, *, user=None, today: date) -> str | None:
    """Aplica el cambio en su fecha efectiva (las futuras las aplica `apply_due_actions`). None = aún no."""
    from apps.common.models import CostCenter
    from apps.roster import services as roster

    if action.effective_date > today:
        return None
    employee = Employee.objects.select_for_update().get(pk=action.employee_id)
    parts = []
    p = plan(employee, action.effective_date, values, action.folio)
    if p is not None:
        if not p.ok:
            from apps.personnel_actions.services import ActionError

            raise ActionError(f"No se pudo actualizar el roster con la AP {action.folio}: "
                              + " ".join(e["message"] for e in p.errors), "apply_failed")
        if p.effective_changes:
            roster.apply_plan(p, (getattr(user, "username", "") or "AP automática")[:150])
            parts.append("roster: " + "; ".join(f"{c.attribute.name} → {c.label if c.action == 'set' else 'sin valor'}"
                                                for c in p.effective_changes))
    exp = employee_changes(values)
    update = {}
    if "base_salary" in exp:
        update["base_salary"] = exp["base_salary"]
        parts.append(f"salario base {employee.base_salary} → {exp['base_salary']}")
    if "cost_center" in exp:
        cc = CostCenter.objects.filter(code=exp["cost_center"]).first()
        if cc is not None and cc.pk != employee.cost_center_id:
            update["cost_center_id"] = cc.pk
            parts.append(f"centro de costos → {cc.code}")
    if update:
        Employee.objects.filter(pk=employee.pk).update(**update)
    return (f"AP {action.folio} aplicada a {employee.employee_code} desde el {action.effective_date:%d/%m/%Y}: "
            + (", ".join(parts) if parts else "sin cambios pendientes") + ".")
