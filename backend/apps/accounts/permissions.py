"""Permisos DRF basados en la matriz RBAC de roles.py."""

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from apps.accounts.roles import can_manage_role, permissions_for


def user_permissions(user) -> frozenset[str]:
    if not user or not user.is_authenticated or not user.is_active:
        return frozenset()
    return permissions_for(user.effective_role)


class PasswordChangeNotRequired(BasePermission):
    """Bloquea la API (salvo las vistas que lo declaran) si hay un cambio de contraseña pendiente."""

    message = "Debe cambiar su contraseña antes de continuar."
    code = "password_change_required"

    def has_permission(self, request, view):
        if getattr(view, "allow_pending_password_change", False):
            return True
        user = request.user
        if user and user.is_authenticated and user.must_change_password:
            raise PermissionDenied(self.message, code=self.code)
        return True


class HasActionPermission(BasePermission):
    """Exige el permiso declarado por la vista para la acción actual.

    La vista define `action_permissions = {"list": Perm.X, ...}`; una acción sin
    entrada se DENIEGA (deny by default).
    """

    message = "Su rol no tiene permiso para esta operación."

    def has_permission(self, request, view):
        required = getattr(view, "action_permissions", {}).get(getattr(view, "action", None))
        return bool(required) and required in user_permissions(request.user)


class CanManageTargetUser(BasePermission):
    """Nivel objeto: el actor solo modifica cuentas cuyo rol puede administrar.

    - Lectura (GET): basta con el permiso de la acción.
    - Escritura: el rol efectivo del destino debe estar en MANAGEABLE_ROLES del actor,
      y solo un superusuario modifica a otro superusuario.
    """

    message = "No puede administrar cuentas con este rol."

    def has_object_permission(self, request, view, obj):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        actor = request.user
        if obj.is_superuser and not actor.is_superuser:
            return False
        return can_manage_role(actor.effective_role, obj.effective_role)
