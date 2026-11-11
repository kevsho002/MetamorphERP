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
    ROSTER_VIEW = "roster.view"  # Fase 6: roster operativo (clientes, marcas, líneas, waves)
    ROSTER_MANAGE = "roster.manage"
    GENERAL_IDS_VIEW = "general_ids.view"  # Fase 7: identificadores para reportería y JOINs (ACD ID, Payroll Tool ID…)
    GENERAL_IDS_MANAGE = "general_ids.manage"
    SCHEDULES_VIEW = "schedules.view"  # Fase 8: turnos, horarios por fechas efectivas, tiempo y horas teóricas vs reales
    SCHEDULES_MANAGE = "schedules.manage"
    ACTIONS_VIEW = "actions.view"  # Fase 9: Acciones de Personal (AP); firmar depende del ROL de cada paso
    ACTIONS_CREATE = "actions.create"
    ACD_AGENT = "acd.agent"  # Fase 11: consola del agente (iniciar sesión, On Queue, auxiliares de su grupo)
    ACD_VIEW = "acd.view"  # tablero de agentes y reporte de estados (formato Genesys Cloud)
    ACD_MANAGE = "acd.manage"  # grupos, acceso a auxiliares, agentes por grupo, cierre de sesión forzado
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
            Perm.ROSTER_VIEW,
            Perm.ROSTER_MANAGE,
            Perm.GENERAL_IDS_VIEW,
            Perm.GENERAL_IDS_MANAGE,
            Perm.SCHEDULES_VIEW,
            Perm.SCHEDULES_MANAGE,
            Perm.ACTIONS_VIEW,
            Perm.ACTIONS_CREATE,
            Perm.ACD_AGENT,
            Perm.ACD_VIEW,
            Perm.ACD_MANAGE,
            Perm.SELF_SERVICE,
            Perm.SYSTEM_STATUS,
        }
    ),
    Role.HR: frozenset(
        _USER_ADMIN
        | {
            Perm.HCM_VIEW, Perm.HCM_MANAGE, Perm.WFM_VIEW, Perm.PAYROLL_VIEW, Perm.PAYROLL_MANAGE,
            Perm.ROSTER_VIEW, Perm.ROSTER_MANAGE, Perm.GENERAL_IDS_VIEW, Perm.GENERAL_IDS_MANAGE,
            Perm.SCHEDULES_VIEW, Perm.SCHEDULES_MANAGE, Perm.ACTIONS_VIEW, Perm.ACTIONS_CREATE, Perm.SELF_SERVICE,
            Perm.ACD_AGENT, Perm.ACD_VIEW,
        }
    ),
    Role.WFM: frozenset({
        Perm.HCM_VIEW, Perm.WFM_VIEW, Perm.WFM_MANAGE, Perm.ROSTER_VIEW, Perm.ROSTER_MANAGE,
        Perm.GENERAL_IDS_VIEW, Perm.GENERAL_IDS_MANAGE, Perm.SCHEDULES_VIEW, Perm.SCHEDULES_MANAGE,
        Perm.ACTIONS_VIEW, Perm.ACTIONS_CREATE, Perm.SELF_SERVICE, Perm.ACD_AGENT, Perm.ACD_VIEW, Perm.ACD_MANAGE,
    }),
    Role.EMPLOYEE: frozenset({Perm.SELF_SERVICE, Perm.ACD_AGENT}),
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
