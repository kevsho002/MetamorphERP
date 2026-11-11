"""Roles y matriz RBAC de Metamorph ERP.

Cada usuario tiene UN rol. Los permisos se derivan del rol mediante esta
matriz (fuente única de verdad, la consumen permissions.py y /auth/me).
"""

from django.db import models


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Administrador"
    HR = "HR", "Recursos Humanos"
    WFM = "WFM", "Workforce Management"
    EMPLOYEE = "EMPLOYEE", "Empleado"


class Perm:
    """Permisos de aplicación (granularidad módulo.acción)."""

    USERS_VIEW = "users.view"
    USERS_CREATE = "users.create"
    USERS_UPDATE = "users.update"
    USERS_ASSIGN_ROLE = "users.assign_role"
    USERS_RESET_PASSWORD = "users.reset_password"
    USERS_DEACTIVATE = "users.deactivate"
    HCM_VIEW = "hcm.view"
    HCM_MANAGE = "hcm.manage"
    WFM_VIEW = "wfm.view"
    WFM_MANAGE = "wfm.manage"
    PAYROLL_VIEW = "payroll.view"
    PAYROLL_MANAGE = "payroll.manage"
    SELF_SERVICE = "self.view"
    SYSTEM_STATUS = "system.status"


_USER_ADMIN = {
    Perm.USERS_VIEW,
    Perm.USERS_CREATE,
    Perm.USERS_UPDATE,
    Perm.USERS_ASSIGN_ROLE,
    Perm.USERS_RESET_PASSWORD,
    Perm.USERS_DEACTIVATE,
}

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    Role.ADMIN: frozenset(
        _USER_ADMIN
        | {
            Perm.HCM_VIEW,
            Perm.HCM_MANAGE,
            Perm.WFM_VIEW,
            Perm.WFM_MANAGE,
            Perm.PAYROLL_VIEW,
            Perm.PAYROLL_MANAGE,
            Perm.SELF_SERVICE,
            Perm.SYSTEM_STATUS,
        }
    ),
    Role.HR: frozenset(
        _USER_ADMIN | {Perm.HCM_VIEW, Perm.HCM_MANAGE, Perm.WFM_VIEW, Perm.PAYROLL_VIEW, Perm.PAYROLL_MANAGE, Perm.SELF_SERVICE}
    ),
    Role.WFM: frozenset({Perm.HCM_VIEW, Perm.WFM_VIEW, Perm.WFM_MANAGE, Perm.SELF_SERVICE}),
    Role.EMPLOYEE: frozenset({Perm.SELF_SERVICE}),
}

# Qué roles puede otorgar/administrar cada rol (prevención de escalamiento de privilegios):
# RRHH gestiona cuentas operativas, pero nunca crea, edita ni resetea Administradores.
MANAGEABLE_ROLES: dict[str, frozenset[str]] = {
    Role.ADMIN: frozenset(Role.values),
    Role.HR: frozenset({Role.HR, Role.WFM, Role.EMPLOYEE}),
    Role.WFM: frozenset(),
    Role.EMPLOYEE: frozenset(),
}

# Roles que deben estar vinculados a un empleado (ID corporativo). Un
# Administrador puede ser una cuenta técnica sin expediente.
ROLES_REQUIRING_EMPLOYEE = frozenset({Role.HR, Role.WFM, Role.EMPLOYEE})


def permissions_for(role: str) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(role, frozenset())


def can_manage_role(actor_role: str, target_role: str) -> bool:
    return target_role in MANAGEABLE_ROLES.get(actor_role, frozenset())
