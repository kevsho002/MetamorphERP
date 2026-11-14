"""Fase 17 — Jerarquía operativa: líderes (ops_leader) y su relación temporal con los agentes (roster «team_manager»).

    Operations Director ──< Operations Manager ──< Account Supervisor ──< Team Manager ──< agentes (roster, por fechas)

Los niveles superiores del agente se derivan de la cadena «reporta a» del Team Manager vigente en la fecha.
Fase 18: la gestión vive en el ROSTER (API /roster/hierarchy/…, permisos roster.*, auditoría ROSTER).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from apps.hcm.models import Employee
from apps.operations.models import (
    HIERARCHY_ORDER, TEAM_MANAGER_ATTRIBUTE, Client, HierarchyLevel, OperationalLeader, parent_level,
)
from apps.roster.models import RosterAssignment
from apps.system.audit import Category, record

LEVELS = [lvl.value for lvl in HIERARCHY_ORDER]
# Parámetro de filtro de la API → nivel.
FILTER_PARAMS = {"director": "OPS_DIRECTOR", "manager": "OPS_MANAGER", "supervisor": "ACCOUNT_SUPERVISOR",
                 "team_manager": "TEAM_MANAGER"}


class HierarchyError(Exception):
    def __init__(self, errors: dict):
        super().__init__("; ".join(str(v) for v in errors.values()))
        self.errors = errors


def _qs():
    return OperationalLeader.objects.select_related("employee", "reports_to__employee", "client")


def leader_dict(lead: OperationalLeader, agents: int | None = None) -> dict:
    return {
        "id": lead.pk, "level": lead.level, "level_label": lead.get_level_display(),
        "employee_code": lead.employee.employee_code, "full_name": lead.employee.full_name,
        "reports_to": lead.reports_to.employee.employee_code if lead.reports_to_id else None,
        "reports_to_id": lead.reports_to_id,
        "reports_to_name": lead.reports_to.employee.full_name if lead.reports_to_id else None,
        "client": lead.client.code if lead.client_id else None, "client_name": lead.client.name if lead.client_id else None,
        "is_active": lead.is_active, **({"agents": agents} if agents is not None else {}),
    }


def leaders(*, include_inactive: bool = False) -> list[OperationalLeader]:
    qs = _qs() if include_inactive else _qs().filter(is_active=True)
    order = {lvl: i for i, lvl in enumerate(LEVELS)}
    return sorted(qs, key=lambda x: (order[x.level], x.employee.last_name, x.employee.first_name))


def agent_counts(on: date) -> dict[int, int]:
    """Agentes con Team Manager vigente en la fecha, por id de líder (solo Team Managers)."""
    rows = _assignment_qs(on, on).values_list("item_id", flat=True)
    by_item = defaultdict(int)
    for item_id in rows:
        by_item[item_id] += 1
    return {lead.pk: by_item.get(lead.roster_item_id, 0) for lead in OperationalLeader.objects.filter(level="TEAM_MANAGER")}


@transaction.atomic
def save_leader(data: dict, *, leader: OperationalLeader | None = None, user=None, request=None) -> OperationalLeader:
    errors: dict = {}
    created = leader is None
    if created:
        level = str(data.get("level") or "").strip().upper()
        if level not in LEVELS:
            errors["level"] = "Elija el nivel (Operations Director, Operations Manager, Account Supervisor o Team Manager)."
        code = str(data.get("employee_code") or "").strip().upper()
        employee = Employee.objects.filter(employee_code=code).first() if code else None
        if employee is None:
            errors["employee_code"] = "Indique el ID corporativo de un colaborador existente."
        elif level in LEVELS and OperationalLeader.objects.filter(level=level, employee=employee).exists():
            errors["employee_code"] = f"{employee.full_name} ya es {HierarchyLevel(level).label}."
        if errors:
            raise HierarchyError(errors)
        leader = OperationalLeader(level=level, employee=employee)
    before = leader_dict(leader) if not created else None
    if "reports_to" in data or created:
        boss_id = data.get("reports_to")
        if boss_id in (None, ""):
            leader.reports_to = None
        else:
            boss = _qs().filter(pk=boss_id).first() if str(boss_id).isdigit() else None
            if boss is None:
                errors["reports_to"] = "Líder superior no encontrado."
            leader.reports_to = boss
    if "client" in data:
        client_code = str(data.get("client") or "").strip()
        leader.client = Client.objects.filter(code=client_code).first() if client_code else None
        if client_code and leader.client is None:
            errors["client"] = f"Cliente «{client_code}» no encontrado."
    if "is_active" in data:
        leader.is_active = bool(data["is_active"])
    if errors:
        raise HierarchyError(errors)
    if leader.reports_to_id and leader.reports_to_id == leader.pk:
        raise HierarchyError({"reports_to": "Un líder no puede reportarse a sí mismo."})
    try:
        leader.full_clean(exclude=["employee", "roster_item"])
    except ValidationError as exc:
        raise HierarchyError({k: " ".join(v) for k, v in exc.message_dict.items()}) from None
    leader.save()
    after = leader_dict(_qs().get(pk=leader.pk))
    changed = [k for k in ("reports_to", "client", "is_active") if before and before[k] != after[k]]
    record("ops_leader_created" if created else "ops_leader_updated", Category.ROSTER,
           f"{after['level_label']} {after['full_name']} ({after['employee_code']}) "
           + ("registrado" if created else f"actualizado: {', '.join(changed) or 'sin cambios'}")
           + (f"; reporta a {after['reports_to_name']}" if after["reports_to"] else "") + ".",
           request=request, actor=user, target=leader.employee, details={"level": leader.level, "changed": changed})
    return _qs().get(pk=leader.pk)


# ---------------------------------------------------------------------------- agentes ↔ jerarquía
def _assignment_qs(start: date, end: date):
    return (RosterAssignment.objects.current().filter(attribute__code=TEAM_MANAGER_ATTRIBUTE, item__isnull=False)
            .filter(effective_start__lte=end).filter(Q(effective_end__isnull=True) | Q(effective_end__gte=start)))


def chains() -> dict[int, dict[str, OperationalLeader]]:
    """Por id de elemento del roster del Team Manager: {nivel: líder} de toda su cadena."""
    by_id = {lead.pk: lead for lead in _qs()}
    out = {}
    for lead in by_id.values():
        if lead.level != "TEAM_MANAGER" or not lead.roster_item_id:
            continue
        chain, cur = {}, lead
        while cur is not None and cur.level not in chain:
            chain[cur.level] = cur
            cur = by_id.get(cur.reports_to_id)
        out[lead.roster_item_id] = chain
    return out


def _brief(lead: OperationalLeader | None) -> dict | None:
    return {"id": lead.pk, "employee_code": lead.employee.employee_code, "full_name": lead.employee.full_name} if lead else None


def agent_hierarchy(employee_ids: list[int], on: date) -> dict[int, dict]:
    """Jerarquía vigente de cada agente en la fecha: {employee_id: {TEAM_MANAGER: {...}, ACCOUNT_SUPERVISOR: …}}."""
    links = chains()
    out = {}
    for row in _assignment_qs(on, on).filter(employee_id__in=employee_ids):
        chain = links.get(row.item_id, {})
        out[row.employee_id] = {lvl: _brief(chain.get(lvl)) for lvl in LEVELS}
    return out


def agent_hierarchy_history(employee_id: int) -> list[dict]:
    links = chains()
    rows = (RosterAssignment.objects.current().filter(attribute__code=TEAM_MANAGER_ATTRIBUTE, employee_id=employee_id, item__isnull=False)
            .order_by("effective_start"))
    out = []
    for row in rows:
        chain = links.get(row.item_id, {})
        out.append({"effective_start": row.effective_start.isoformat(),
                    "effective_end": row.effective_end.isoformat() if row.effective_end else None,
                    **{lvl: _brief(chain.get(lvl)) for lvl in LEVELS}})
    return out


def subtree_items(level: str, employee_code: str) -> set[int]:
    """Elementos del roster de los Team Managers bajo el líder (nivel + ID corporativo), incluido él mismo si es TM."""
    root = OperationalLeader.objects.filter(level=level, employee__employee_code=employee_code.upper()).first()
    if root is None:
        return set()
    children = defaultdict(list)
    for lead in OperationalLeader.objects.all().only("id", "reports_to_id", "level", "roster_item_id"):
        children[lead.reports_to_id].append(lead)
    items, stack = set(), [root]
    while stack:
        cur = stack.pop()
        if cur.level == "TEAM_MANAGER" and cur.roster_item_id:
            items.add(cur.roster_item_id)
        stack.extend(children.get(cur.pk, []))
    return items


def employees_under(level: str, employee_code: str, on: date) -> set[int]:
    items = subtree_items(level, employee_code)
    if not items:
        return set()
    return set(_assignment_qs(on, on).filter(item_id__in=items).values_list("employee_id", flat=True))


def employees_under_qs(level: str, employee_code: str, on: date):
    """Como `employees_under`, pero como subconsulta (valores employee_id) para filtrar plantillas grandes en SQL."""
    items = subtree_items(level, employee_code)
    return _assignment_qs(on, on).filter(item_id__in=items or [0]).values("employee_id")


def chain_of_command(employee: Employee, on: date) -> dict:
    """Para la ficha del roster: su cadena vigente como agente (vía Team Manager) y sus roles de líder."""
    as_agent = agent_hierarchy([employee.pk], on).get(employee.pk)
    roles = []
    for lead in _qs().filter(employee=employee).order_by("level"):
        subordinates = OperationalLeader.objects.filter(reports_to=lead, is_active=True).count()
        agents = agent_counts(on).get(lead.pk) if lead.level == "TEAM_MANAGER" else None
        chain, cur = [], lead.reports_to
        while cur is not None and len(chain) < len(LEVELS):
            chain.append({"level": cur.level, "level_label": cur.get_level_display(), **_brief(cur)})
            cur = cur.reports_to
        roles.append({**leader_dict(lead, agents), "subordinates": subordinates, "chain": chain})
    return {"as_of": on.isoformat(), "as_agent": as_agent,
            "levels": [{"value": lvl.value, "label": lvl.label} for lvl in HIERARCHY_ORDER], "roles": roles}


__all__ = ["chain_of_command", "FILTER_PARAMS", "LEVELS", "HierarchyError", "agent_counts", "agent_hierarchy", "agent_hierarchy_history",
           "employees_under", "leader_dict", "leaders", "parent_level", "save_leader"]
