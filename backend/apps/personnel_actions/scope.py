"""Fase 23 — Alcance jerárquico de las Acciones de Personal: a quién puede elaborarle AP cada usuario.

* Líder en la cadena de mando (dbo.ops_leader): ÚNICAMENTE los colaboradores bajo su jerarquía directa o indirecta
  (función de SQL Server dbo.fn_EmployeesUnderLeader: líderes que le reportan y agentes de sus Team Managers en el roster
  vigente). Nunca a sí mismo.
* Administrador: toda la organización.
* Áreas de soporte sin equipo a cargo (por defecto Generalista de RRHH y WFM): toda la organización. Se ajusta en
  /admin/ › Parámetros de sesión y cliente web › «Roles con alcance global en AP» (vacío = alcance estrictamente
  jerárquico para todos salvo el Administrador).

El selector del formulario solo ofrece ese universo y la validación del servidor rechaza cualquier otro (out_of_scope).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from django.db import connection
from django.db.models import Q
from django.utils import timezone

from apps.accounts.roles import Role
from apps.hcm.models import Employee

MAX_RESULTS = 50


@dataclass
class Scope:
    mode: str  # all | support | hierarchy
    ids: set[int] | None = None  # None = toda la organización
    relation: dict[int, str] = field(default_factory=dict)  # employee_id → DIRECT | INDIRECT
    self_id: int | None = None

    def allows(self, employee: Employee) -> bool:
        if employee.pk == self.self_id and self.mode == "hierarchy":
            return False
        return self.ids is None or employee.pk in self.ids

    @property
    def label(self) -> str:
        return {"all": "Toda la organización (Administrador)",
                "support": "Toda la organización (área de soporte sin equipo a cargo)",
                "hierarchy": "Su jerarquía directa e indirecta"}[self.mode]


def under_leader(employee_id: int, on: date | None = None) -> dict[int, str]:
    on = on or timezone.localdate()
    with connection.cursor() as c:
        c.execute("SELECT employee_id, relation FROM dbo.fn_EmployeesUnderLeader(%s, %s)", [employee_id, on])
        return {int(e): r for e, r in c.fetchall()}


def scope_for(user, on: date | None = None) -> Scope:
    from apps.operations.models import OperationalLeader
    from apps.system import policy

    role = getattr(user, "effective_role", None) or getattr(user, "role", None)
    me = user.employee.pk if getattr(user, "employee_id", None) else None  # employee_id guarda el ID corporativo (to_field)
    if role == Role.ADMIN:
        return Scope("all", self_id=me)
    leads = me is not None and OperationalLeader.objects.filter(employee_id=me, is_active=True).exists()
    if leads:
        rel = under_leader(me, on)
        return Scope("hierarchy", set(rel), rel, me)
    if role in (policy.current().ap_full_scope_roles or []):
        return Scope("support", self_id=me)
    return Scope("hierarchy", set(), {}, me)


def search(user, q: str = "", *, include_terminated: bool = False, limit: int = 20) -> dict:
    scope = scope_for(user)
    qs = Employee.objects.select_related("country", "cost_center").order_by("first_name", "last_name")
    if scope.ids is not None:
        qs = qs.filter(pk__in=scope.ids)
    if not include_terminated:
        qs = qs.exclude(employment_status=Employee.Status.TERMINATED)
    q = (q or "").strip()
    if q:
        cond = Q()
        for term in q.split()[:4]:
            cond &= (Q(employee_code__icontains=term) | Q(first_name__icontains=term) | Q(middle_name__icontains=term)
                     | Q(last_name__icontains=term) | Q(second_last_name__icontains=term) | Q(national_id_number__icontains=term))
        qs = qs.filter(cond)
    total = qs.count()
    rows = list(qs[:min(max(limit, 1), MAX_RESULTS)])
    return {
        "scope": scope.mode, "scope_label": scope.label, "total": total,
        "results": [{"employee_code": e.employee_code, "full_name": e.full_name, "country": e.country.country_code,
                     "status": e.employment_status, "status_label": e.get_employment_status_display(),
                     "cost_center": e.cost_center.code if e.cost_center_id else None, "hire_date": e.hire_date,
                     "relation": scope.relation.get(e.pk)} for e in rows],
    }
