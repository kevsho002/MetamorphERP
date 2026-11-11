"""API de seguridad: sesión (login/logout/me/cambio de contraseña) y CRUD de usuarios con RBAC."""


from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.db.models import Q
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts import services
from apps.accounts.models import CustomUser
from apps.accounts.permissions import CanManageTargetUser, HasActionPermission, PasswordChangeNotRequired
from apps.accounts.roles import Perm, Role, can_manage_role, permissions_for
from apps.system import policy, sessions
from apps.system.audit import Category, record
from apps.accounts.serializers import (
    CurrentUserSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    RoleAssignSerializer,
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer,
)

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


# --------------------------------------------------------------------- sesión
@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    """GET: entrega la cookie CSRF que el SPA debe reenviar en X-CSRFToken."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"detail": "CSRF cookie establecida."})


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = authenticate(request, **data.validated_data)  # un fallo se audita con la señal user_login_failed
        if user is None:  # mensaje genérico: no revela si el usuario existe o está inactivo
            return Response({"detail": "Usuario o contraseña incorrectos."}, status=status.HTTP_400_BAD_REQUEST)
        settings_obj = policy.current()
        if settings_obj.maintenance_mode and user.effective_role != Role.ADMIN:
            record(
                "login_blocked", Category.AUTH, "Ingreso rechazado: el sistema está en modo mantenimiento.",
                request=request, actor=user, target=user, success=False,
            )
            return Response(
                {"detail": settings_obj.maintenance_message, "code": "maintenance"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        login(request, user)  # rota el id de sesión y el token CSRF; la señal registra sesión + auditoría
        return Response(CurrentUserSerializer(user).data, headers=NO_STORE)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]
    allow_pending_password_change = True

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsAuthenticated]  # sin PasswordChangeNotRequired: el SPA debe saber que hay cambio pendiente

    def get(self, request):
        return Response(CurrentUserSerializer(request.user).data, headers=NO_STORE)


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]
    allow_pending_password_change = True

    def post(self, request):
        data = PasswordChangeSerializer(data=request.data, context={"request": request})
        data.is_valid(raise_exception=True)
        services.change_own_password(request.user, **data.validated_data, request=request)
        previous_key = request.session.session_key
        update_session_auth_hash(request, request.user)  # mantiene ESTA sesión (con nueva clave); invalida las demás
        sessions.rekey(previous_key, request.session.session_key)
        sessions.end_user_sessions(request.user, sessions.Reason.PASSWORD, except_key=request.session.session_key)
        return Response(CurrentUserSerializer(request.user).data, headers=NO_STORE)


# ------------------------------------------------------------------- usuarios
class UserViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """CRUD de usuarios bajo RBAC.

    GET    /users/                      listar (filtros: search, role, is_active, cost_center)
    POST   /users/                      crear (devuelve contraseña temporal una sola vez)
    GET    /users/{id}/                 detalle
    PATCH  /users/{id}/                 editar datos / vínculo con empleado y centro de costos
    POST   /users/{id}/role/            asignar rol
    POST   /users/{id}/reset-password/  reseteo seguro (contraseña temporal + cambio obligatorio)
    POST   /users/{id}/activate/        reactivar
    POST   /users/{id}/deactivate/      desactivar (baja lógica; DELETE es equivalente)
    """

    permission_classes = [IsAuthenticated, PasswordChangeNotRequired, HasActionPermission, CanManageTargetUser]
    action_permissions = {
        "list": Perm.USERS_VIEW,
        "retrieve": Perm.USERS_VIEW,
        "create": Perm.USERS_CREATE,
        "update": Perm.USERS_UPDATE,
        "partial_update": Perm.USERS_UPDATE,
        "assign_role": Perm.USERS_ASSIGN_ROLE,
        "reset_password": Perm.USERS_RESET_PASSWORD,
        "activate": Perm.USERS_DEACTIVATE,
        "deactivate": Perm.USERS_DEACTIVATE,
        "destroy": Perm.USERS_DEACTIVATE,
    }

    def get_queryset(self):
        qs = CustomUser.objects.select_related("employee__country", "cost_center").order_by("username")
        params = self.request.query_params
        if search := params.get("search", "").strip():
            qs = qs.filter(
                Q(username__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(email__icontains=search)
                | Q(employee__employee_code__icontains=search)
            )
        if role := params.get("role"):
            qs = qs.filter(role=role.upper())
        if (is_active := params.get("is_active")) is not None:
            qs = qs.filter(is_active=is_active.lower() in {"1", "true", "yes"})
        if (linked := params.get("linked")) is not None:  # Fase 7: cuentas con / sin empleado vinculado
            qs = qs.filter(employee__isnull=linked.lower() not in {"1", "true", "yes"})
        if (cost_center := params.get("cost_center", "")).isdigit():
            qs = qs.filter(cost_center_id=int(cost_center))
        return qs

    def get_serializer_class(self):
        return {"create": UserCreateSerializer, "update": UserUpdateSerializer, "partial_update": UserUpdateSerializer}.get(
            self.action, UserSerializer
        )

    def _detail(self, user, status_code=status.HTTP_200_OK, **extra):
        user = self.get_queryset().get(pk=user.pk)
        return Response({**UserSerializer(user).data, **extra}, status=status_code, headers=NO_STORE)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not can_manage_role(request.user.effective_role, serializer.validated_data.get("role", Role.EMPLOYEE)):
            raise PermissionDenied("No puede crear usuarios con este rol.")
        user = serializer.save()
        temporary = services.generate_temporary_password(user)
        user.set_password(temporary)
        user.save(update_fields=["password"])
        record(
            "user_created", Category.USERS, f"Cuenta «{user.username}» ({user.get_role_display()}) creada.",
            request=request, target=user, details={"role": user.role, "employee_code": user.employee_id},
        )
        return self._detail(user, status.HTTP_201_CREATED, temporary_password=temporary)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        record(
            "user_updated", Category.USERS, f"Datos de la cuenta «{instance.username}» modificados.",
            request=request, target=instance, details={"fields": sorted(serializer.validated_data)},
        )
        return self._detail(instance)

    def destroy(self, request, *args, **kwargs):
        services.set_active(request.user, self.get_object(), active=False, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], url_path="role")
    def assign_role(self, request, pk=None):
        target = self.get_object()
        data = RoleAssignSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return self._detail(services.assign_role(request.user, target, data.validated_data["role"], request=request))

    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        target = self.get_object()
        temporary = services.reset_password(request.user, target, request=request)
        return self._detail(target, temporary_password=temporary)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        return self._detail(services.set_active(request.user, self.get_object(), active=True, request=request))

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        return self._detail(services.set_active(request.user, self.get_object(), active=False, request=request))


class RoleListView(APIView):
    """Catálogo de roles con sus permisos y si el usuario actual puede otorgarlos."""

    permission_classes = [IsAuthenticated, PasswordChangeNotRequired, HasActionPermission]
    action_permissions = {None: Perm.USERS_VIEW}

    def get(self, request):
        return Response(
            [
                {
                    "code": role.value,
                    "label": role.label,
                    "permissions": sorted(permissions_for(role)),
                    "assignable": can_manage_role(request.user.effective_role, role),
                }
                for role in Role
            ]
        )
