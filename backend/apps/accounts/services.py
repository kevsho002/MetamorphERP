"""Reglas de negocio de cuentas: contraseñas temporales, reseteo, roles y activación.

Las vistas solo orquestan; aquí viven las invariantes de seguridad para que se
apliquen igual desde la API, el admin de Django o futuros comandos.
"""

import re
import secrets
import string
import unicodedata
from dataclasses import dataclass, field

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import CustomUser
from apps.accounts.permissions import user_permissions
from apps.accounts.roles import ROLES_REQUIRING_EMPLOYEE, Perm, Role, can_manage_role
from apps.system import sessions
from apps.system.audit import Category, record


_SYMBOLS = "!@#$%*-_+=?"
_ALPHABET = string.ascii_letters + string.digits + _SYMBOLS
TEMP_PASSWORD_LENGTH = 16


class Conflict(ValidationError):
    status_code = 409
    default_code = "conflict"


def generate_temporary_password(user: CustomUser | None = None) -> str:
    """Contraseña aleatoria (CSPRNG) con mayúscula, minúscula, dígito y símbolo; pasa los validadores."""
    while True:
        candidate = "".join(secrets.choice(_ALPHABET) for _ in range(TEMP_PASSWORD_LENGTH))
        if (
            any(c.islower() for c in candidate)
            and any(c.isupper() for c in candidate)
            and any(c.isdigit() for c in candidate)
            and any(c in _SYMBOLS for c in candidate)
        ):
            try:
                validate_password(candidate, user)
            except DjangoValidationError:  # muy improbable; se genera otra
                continue
            return candidate


def _other_active_admins(exclude_pk) -> int:
    """Bloquea (UPDLOCK) las filas de administradores activos para que dos bajas simultáneas no dejen cero."""
    admins = (
        CustomUser.objects.select_for_update()
        .filter(Q(role=Role.ADMIN) | Q(is_superuser=True), is_active=True)
        .exclude(pk=exclude_pk)
    )
    return len(admins.values_list("pk", flat=True))


def _ensure_not_last_admin(target: CustomUser, action: str) -> None:
    if target.effective_role == Role.ADMIN and target.is_active and _other_active_admins(target.pk) == 0:
        raise Conflict({"detail": f"No se puede {action} al último administrador activo."})


def _ensure_not_self(actor: CustomUser, target: CustomUser, action: str) -> None:
    if actor.pk == target.pk:
        raise PermissionDenied(f"No puede {action} su propia cuenta.")


@transaction.atomic
def reset_password(actor: CustomUser, target: CustomUser, request=None) -> str:
    """Reseteo administrativo: genera una contraseña temporal de un solo uso.

    - Nunca se elige la contraseña a mano ni se envía en claro por otro canal:
      la respuesta la muestra UNA vez (Cache-Control: no-store).
    - Fuerza el cambio en el siguiente inicio de sesión.
    - Cambiar el hash invalida todas las sesiones activas del usuario
      (Django verifica el hash de contraseña en cada request).
    """
    _ensure_not_self(actor, target, "resetear la contraseña de")
    temporary = generate_temporary_password(target)
    target.set_password(temporary)
    target.must_change_password = True
    target.password_changed_at = timezone.now()
    target.save(update_fields=["password", "must_change_password", "password_changed_at", "updated_at"])
    sessions.end_user_sessions(target, sessions.Reason.PASSWORD)
    record(
        "password_reset", Category.USERS, f"Reseteo administrativo de contraseña de «{target.username}».",
        request=request, actor=actor, target=target,
    )
    return temporary


@transaction.atomic
def change_own_password(user: CustomUser, current_password: str, new_password: str, request=None) -> None:
    if not user.check_password(current_password):
        raise ValidationError({"current_password": ["La contraseña actual no es correcta."]})
    if current_password == new_password:
        raise ValidationError({"new_password": ["La nueva contraseña debe ser distinta de la actual."]})
    try:
        validate_password(new_password, user)
    except DjangoValidationError as exc:
        raise ValidationError({"new_password": list(exc.messages)}) from exc
    user.set_password(new_password)
    user.must_change_password = False
    user.password_changed_at = timezone.now()
    user.save(update_fields=["password", "must_change_password", "password_changed_at", "updated_at"])
    record("password_changed", Category.USERS, "El usuario cambió su contraseña.", request=request, actor=user, target=user)


@transaction.atomic
def assign_role(actor: CustomUser, target: CustomUser, new_role: str, request=None) -> CustomUser:
    _ensure_not_self(actor, target, "cambiar el rol de")
    if not can_manage_role(actor.effective_role, new_role):
        raise PermissionDenied("No puede otorgar este rol.")
    if new_role == target.role:
        return target
    if new_role in ROLES_REQUIRING_EMPLOYEE and not target.employee_id:
        raise ValidationError({"role": [f"El rol {Role(new_role).label} requiere vincular un ID corporativo de empleado."]})
    if target.role == Role.ADMIN and not target.is_superuser:
        _ensure_not_last_admin(target, "quitar el rol de administrador")
    previous = target.role
    target.role = new_role
    target.save(update_fields=["role", "updated_at"])
    record(
        "role_assigned", Category.USERS,
        f"Rol de «{target.username}»: {Role(previous).label} → {Role(new_role).label}.",
        request=request, actor=actor, target=target, details={"from": previous, "to": new_role},
    )
    return target


@transaction.atomic
def set_active(actor: CustomUser, target: CustomUser, active: bool, request=None, reason: str = "") -> CustomUser:
    if target.is_active == active:
        return target
    if not active:
        _ensure_not_self(actor, target, "desactivar")
        _ensure_not_last_admin(target, "desactivar")
    target.is_active = active
    target.save(update_fields=["is_active", "updated_at"])
    # Un usuario inactivo no supera la autenticación en su siguiente request
    # (ModelBackend.user_can_authenticate); además se cierran sus sesiones abiertas.
    if not active:
        sessions.end_user_sessions(target, sessions.Reason.DEACTIVATED)
    record(
        "user_activated" if active else "user_deactivated", Category.USERS,
        f"Cuenta «{target.username}» {'reactivada' if active else 'desactivada'}{f' ({reason})' if reason else ''}.",
        request=request, actor=actor, target=target,
    )
    return target


# --------------------------------------------------------------------- cuenta vinculada a un empleado
USERNAME_RE = re.compile(r"^[A-Za-z0-9.@+_-]{3,150}$")


def _ascii_slug(text: str | None) -> str:
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", folded.lower())


def username_taken(username: str) -> bool:
    return CustomUser.objects.filter(username__iexact=username).exists()


def suggest_username(first_name: str | None, last_name: str | None) -> str:
    """nombre.apellido (sin tildes ni espacios); si existe, nombre.apellido2, 3..."""
    first = _ascii_slug((first_name or "").split()[0] if (first_name or "").split() else "")
    last = _ascii_slug((last_name or "").split()[0] if (last_name or "").split() else "")
    base = ".".join(p for p in (first, last) if p)[:140] or "usuario"
    candidate, n = base, 2
    while username_taken(candidate):
        candidate = f"{base}{n}"
        n += 1
    return candidate


@dataclass
class AccountPlan:
    """Resultado de validar la solicitud de cuenta vinculada (antes de crear nada)."""

    role: str = Role.EMPLOYEE
    username: str = ""
    email: str = ""
    errors: list[tuple[str, str, str]] = field(default_factory=list)  # (campo, mensaje, código)
    warnings: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def preview(self) -> dict:
        return {"username": self.username, "role": self.role, "role_label": Role(self.role).label if self.role in Role.values else self.role,
                "email": self.email or None}


def plan_linked_account(
    actor: CustomUser,
    *,
    role: str | None,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    email: str | None,
    employee=None,
) -> AccountPlan:
    plan = AccountPlan(role=(role or Role.EMPLOYEE).strip().upper(), email=(email or "").strip())
    if Perm.USERS_CREATE not in user_permissions(actor):
        plan.errors.append(("user_account", "Su rol no puede crear cuentas de usuario.", "forbidden"))
        return plan
    if plan.role not in Role.values:
        plan.errors.append(("user_account.role", f"Rol inválido. Valores: {', '.join(Role.values)}.", "invalid_role"))
    elif not can_manage_role(actor.effective_role, plan.role):
        plan.errors.append(
            ("user_account.role", f"Su rol no puede otorgar el rol {Role(plan.role).label}.", "role_not_allowed")
        )
    if employee is not None:
        if CustomUser.objects.filter(employee_id=employee.employee_code).exists():
            plan.errors.append(("user_account", "El empleado ya tiene una cuenta de usuario vinculada.", "already_linked"))
        if employee.employment_status == employee.Status.TERMINATED:
            plan.errors.append(("user_account", "El empleado está terminado: no se le crea acceso.", "terminated"))
    requested = (username or "").strip()
    if requested:
        if not USERNAME_RE.match(requested):
            plan.errors.append(
                ("user_account.username", "Use de 3 a 150 caracteres: letras, dígitos y . @ + - _ (sin espacios ni tildes).", "invalid_username")
            )
        elif username_taken(requested):
            plan.errors.append(("user_account.username", f"El usuario «{requested}» ya existe. Elija otro.", "username_taken"))
        plan.username = requested
    else:
        plan.username = suggest_username(first_name, last_name)
    if not plan.email:
        plan.warnings.append(
            ("user_account.email", "El empleado no tiene correo laboral: la cuenta se creará sin correo.", "no_email")
        )
    return plan


@transaction.atomic
def create_linked_account(actor: CustomUser, employee, plan: AccountPlan, request=None) -> tuple[CustomUser, str]:
    """Crea la cuenta ya validada por plan_linked_account, enlazada por FK al ID corporativo."""
    if not plan.ok:
        raise ValueError("create_linked_account requiere un plan sin errores")
    user = CustomUser(
        username=plan.username,
        email=plan.email,
        first_name=employee.first_name[:150],
        last_name=employee.last_name[:150],
        role=plan.role,
        employee=employee,
        cost_center=employee.cost_center,
        must_change_password=True,
    )
    temporary = generate_temporary_password(user)
    user.set_password(temporary)
    user.password_changed_at = timezone.now()
    user.save()
    record(
        "user_created", Category.USERS,
        f"Cuenta «{user.username}» ({Role(user.role).label}) creada y vinculada al empleado {employee.employee_code}.",
        request=request, actor=actor, target=user,
        details={"role": user.role, "employee_code": employee.employee_code, "linked": True},
    )
    return user, temporary


# --------------------------------------------------------------------- vincular una cuenta EXISTENTE (Fase 7)
@dataclass
class LinkPlan:
    """Validación de «vincular el usuario X al empleado Y» (antes de escribir nada)."""

    user: CustomUser | None = None
    errors: list[tuple[str, str, str]] = field(default_factory=list)  # (campo, mensaje, código)
    warnings: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def preview(self) -> dict | None:
        if self.user is None:
            return None
        return {
            "id": self.user.pk, "username": self.user.username, "role": self.user.role,
            "role_label": self.user.get_role_display(), "is_active": self.user.is_active, "linked": True,
        }


def link_candidates(actor: CustomUser):
    """Cuentas sin empleado vinculado que el actor puede administrar (para buscarlas en la interfaz)."""
    qs = CustomUser.objects.filter(employee__isnull=True).order_by("username")
    manageable = [r for r in Role.values if can_manage_role(actor.effective_role, r)]
    qs = qs.filter(role__in=manageable)
    if not actor.is_superuser:
        qs = qs.filter(is_superuser=False)
    return qs


def plan_link_existing(actor: CustomUser, *, user_id, employee=None) -> LinkPlan:
    """Reglas: el actor puede editar cuentas y administrar el rol de la cuenta; la cuenta no tiene
    empleado; el empleado no tiene cuenta y no está Terminado. `employee=None` = alta en curso."""
    plan = LinkPlan()
    if Perm.USERS_UPDATE not in user_permissions(actor):
        plan.errors.append(("user_account", "Su rol no puede vincular cuentas de usuario.", "forbidden"))
        return plan
    try:
        user = CustomUser.objects.select_related("cost_center").get(pk=int(user_id))
    except (TypeError, ValueError, CustomUser.DoesNotExist):
        plan.errors.append(("user_account.user_id", "Seleccione una cuenta de usuario existente.", "unknown_user"))
        return plan
    plan.user = user
    if user.employee_id:
        plan.errors.append(
            ("user_account.user_id", f"La cuenta «{user.username}» ya está vinculada al empleado {user.employee_id}.", "user_linked")
        )
    if user.is_superuser and not actor.is_superuser:
        plan.errors.append(("user_account.user_id", "Solo un superusuario puede vincular otra cuenta de superusuario.", "forbidden"))
    elif not can_manage_role(actor.effective_role, user.effective_role):
        plan.errors.append(
            ("user_account.user_id", f"Su rol no administra cuentas con rol {Role(user.effective_role).label}.", "role_not_allowed")
        )
    if employee is not None:
        if CustomUser.objects.filter(employee_id=employee.employee_code).exists():
            plan.errors.append(("user_account", "El empleado ya tiene una cuenta de usuario vinculada.", "already_linked"))
        if employee.employment_status == employee.Status.TERMINATED:
            plan.errors.append(("user_account", "El empleado está terminado: no se le vincula acceso.", "terminated"))
    if not user.is_active:
        plan.warnings.append(
            ("user_account.user_id", f"La cuenta «{user.username}» está desactivada: reactívela para que pueda ingresar.", "inactive_user")
        )
    return plan


@transaction.atomic
def link_existing_account(actor: CustomUser, employee, plan: LinkPlan, request=None) -> CustomUser:
    """Enlaza por FK (ID corporativo) una cuenta ya existente con el empleado y alinea su centro de costos."""
    if not plan.ok or plan.user is None:
        raise ValueError("link_existing_account requiere un plan sin errores")
    user = CustomUser.objects.select_for_update().get(pk=plan.user.pk)
    if user.employee_id:  # carrera: alguien la vinculó entre la validación y la escritura
        raise Conflict({"detail": f"La cuenta «{user.username}» acaba de ser vinculada a otro empleado."})
    previous_cc = user.cost_center_id
    user.employee = employee
    user.cost_center = employee.cost_center
    user.save(update_fields=["employee", "cost_center", "updated_at"])
    record(
        "user_linked", Category.USERS,
        f"Cuenta «{user.username}» ({Role(user.role).label}) vinculada al empleado {employee.employee_code}.",
        request=request, actor=actor, target=user,
        details={"employee_code": employee.employee_code, "cost_center_from": previous_cc, "cost_center_to": user.cost_center_id},
    )
    return user
