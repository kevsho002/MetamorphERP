"""Fase 25 — Administración directa de las cuentas de usuario en /admin/.

Las cuentas se siguen CREANDO vinculadas a un empleado desde la aplicación (alta de empleado o ficha del expediente):
aquí no hay «Agregar» ni «Eliminar». Desde el panel se gestionan los atributos de control de acceso: rol, cuenta
activa, bloqueo (con motivo), cambio de contraseña obligatorio y las sesiones abiertas. Se aplican las mismas reglas
que en la API de usuarios: matriz de roles otorgables (sin escalamiento de privilegios), nunca sobre la propia cuenta
y nunca dejar al sistema sin un administrador activo. Cada cambio queda en la auditoría.
"""

from django import forms
from django.contrib import admin, messages
from django.contrib.auth.models import Group
from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts import lockout
from apps.accounts.models import CustomUser
from apps.accounts.roles import ROLES_REQUIRING_EMPLOYEE, Role, can_manage_role
from apps.system import sessions
from apps.system.audit import Category, record

# Los permisos se derivan del rol (apps/accounts/roles.py): los grupos de Django no se usan.
if admin.site.is_registered(Group):
    admin.site.unregister(Group)

_TRACKED = ("first_name", "last_name", "email", "role", "is_active", "must_change_password")


def _other_active_admins(exclude_pk) -> int:
    return (CustomUser.objects.filter(Q(role=Role.ADMIN) | Q(is_superuser=True), is_active=True, locked_at__isnull=True)
            .exclude(pk=exclude_pk).count())


class UserAdminForm(forms.ModelForm):
    locked = forms.BooleanField(label="cuenta bloqueada", required=False,
                                help_text="Bloqueada = no puede iniciar sesión aunque su contraseña sea correcta.")

    class Meta:
        model = CustomUser
        fields = ("first_name", "last_name", "email", "role", "is_active", "must_change_password", "lock_reason")

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.fields["locked"].initial = self.instance.locked_at is not None
        if actor is not None and "role" in self.fields:
            allowed = [(v, label) for v, label in Role.choices if can_manage_role(actor.effective_role, v) or v == self.instance.role]
            self.fields["role"].choices = allowed

    def clean(self):
        data = super().clean()
        user, actor = self.instance, self.actor
        role = data.get("role", user.role)
        removing_admin = user.effective_role == Role.ADMIN and (
            (role != Role.ADMIN and not user.is_superuser) or data.get("is_active") is False or data.get("locked"))
        if actor is not None and actor.pk == user.pk:
            if role != user.role:
                raise forms.ValidationError("No puede cambiar el rol de su propia cuenta.")
            if data.get("is_active") is False and user.is_active:
                raise forms.ValidationError("No puede desactivar su propia cuenta.")
            if data.get("locked") and user.locked_at is None:
                raise forms.ValidationError("No puede bloquear su propia cuenta.")
        if role != user.role:
            if actor is not None and not can_manage_role(actor.effective_role, role):
                self.add_error("role", "Su rol no puede otorgar este rol.")
            if role in ROLES_REQUIRING_EMPLOYEE and not user.employee_id:
                self.add_error("role", f"El rol {Role(role).label} requiere vincular un ID corporativo de empleado.")
        if removing_admin and user.is_active and _other_active_admins(user.pk) == 0:
            raise forms.ValidationError("No se puede dejar al sistema sin un administrador activo y desbloqueado.")
        if data.get("locked") and user.locked_at is None and not (data.get("lock_reason") or "").strip():
            self.add_error("lock_reason", "Indique el motivo del bloqueo.")
        return data


class LockedFilter(admin.SimpleListFilter):
    title = "acceso"
    parameter_name = "acceso"

    def lookups(self, request, model_admin):
        return [("bloqueada", "Bloqueadas"), ("inactiva", "Inactivas"), ("cambio", "Cambio de contraseña pendiente"),
                ("conectada", "Con sesión activa"), ("habilitada", "Habilitadas")]

    def queryset(self, request, qs):
        v = self.value()
        if v == "bloqueada":
            return qs.filter(locked_at__isnull=False)
        if v == "inactiva":
            return qs.filter(is_active=False)
        if v == "cambio":
            return qs.filter(must_change_password=True)
        if v == "conectada":
            return qs.filter(sessions__ended_at__isnull=True).distinct()
        if v == "habilitada":
            return qs.filter(is_active=True, locked_at__isnull=True)
        return qs


@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    form = UserAdminForm
    list_display = ("username", "full_name", "role", "is_active", "locked", "must_change_password", "active_sessions",
                    "failed_login_count", "last_login")
    list_filter = (LockedFilter, "role", "is_active", "must_change_password", "is_superuser")
    search_fields = ("username", "first_name", "last_name", "email", "employee__employee_code")
    ordering = ("username",)
    list_per_page = 50
    actions = ["unlock_accounts", "lock_accounts", "force_password_change", "close_user_sessions", "activate_accounts",
               "deactivate_accounts"]
    fieldsets = (
        ("Cuenta", {"fields": ("username", "employee", "first_name", "last_name", "email")}),
        ("Control de acceso", {"fields": ("role", "is_active", "must_change_password", "locked", "lock_reason")}),
        ("Seguridad (solo lectura)", {"fields": ("is_superuser", "failed_login_count", "last_failed_login_at", "locked_at",
                                                 "password_changed_at", "last_login", "date_joined", "active_sessions")}),
    )
    readonly_fields = ("username", "employee", "is_superuser", "failed_login_count", "last_failed_login_at", "locked_at",
                       "password_changed_at", "last_login", "date_joined", "active_sessions")

    def get_queryset(self, request):
        sessions.sweep_expired()
        return super().get_queryset(request).annotate(
            _active=Count("sessions", filter=Q(sessions__ended_at__isnull=True), distinct=True))

    def get_form(self, request, obj=None, change=False, **kwargs):
        base = super().get_form(request, obj, change=change, **kwargs)

        class Form(base):
            def __init__(self, *a, **kw):
                kw["actor"] = request.user
                super().__init__(*a, **kw)

        return Form

    @admin.display(description="nombre")
    def full_name(self, obj):
        return obj.get_full_name() or "—"

    @admin.display(description="bloqueada", boolean=True)
    def locked(self, obj):
        return obj.locked_at is not None

    @admin.display(description="sesiones activas")
    def active_sessions(self, obj):
        n = getattr(obj, "_active", None)
        return n if n is not None else obj.sessions.filter(ended_at__isnull=True).count()

    # ---------------------------------------------------------------- permisos
    def has_add_permission(self, request):
        return False  # las cuentas se crean vinculadas a un empleado desde la aplicación

    def has_delete_permission(self, request, obj=None):
        return False  # nunca se borran: se desactivan o bloquean (auditoría)

    def has_change_permission(self, request, obj=None):
        if not super().has_change_permission(request, obj):
            return False
        if obj is None:
            return True
        if obj.is_superuser and not request.user.is_superuser:
            return False  # solo un superusuario gestiona otro superusuario
        return obj.pk == request.user.pk or can_manage_role(request.user.effective_role, obj.role)

    # ---------------------------------------------------------------- guardado auditado
    def save_model(self, request, obj, form, change):
        before = CustomUser.objects.filter(pk=obj.pk).values(*_TRACKED, "locked_at").first() or {}
        want_lock = form.cleaned_data.get("locked")
        if not want_lock and obj.locked_at is None:
            obj.lock_reason = ""
        super().save_model(request, obj, form, change)
        diff = {f: {"antes": before.get(f), "despues": getattr(obj, f)} for f in _TRACKED if before.get(f) != getattr(obj, f)}
        if diff:
            record("user_updated_admin", Category.USERS,
                   f"Cuenta «{obj.username}» modificada desde el panel: {', '.join(diff)}.", request=request, target=obj,
                   details=diff)
        if before.get("is_active") and not obj.is_active:
            sessions.end_user_sessions(obj, sessions.Reason.DEACTIVATED)
        if want_lock and obj.locked_at is None:
            lockout.lock(obj, form.cleaned_data.get("lock_reason") or "", actor=request.user, request=request)
        elif not want_lock and before.get("locked_at"):
            lockout.unlock(obj, actor=request.user, request=request)

    # ---------------------------------------------------------------- acciones masivas
    def _manageable(self, request, queryset):
        out, skipped = [], 0
        for u in queryset:
            if u.pk == request.user.pk or not self.has_change_permission(request, u):
                skipped += 1
            else:
                out.append(u)
        if skipped:
            self.message_user(request, f"{skipped} cuenta(s) omitida(s): la propia o fuera de su alcance de roles.", messages.WARNING)
        return out

    @admin.action(description="Desbloquear las cuentas seleccionadas")
    def unlock_accounts(self, request, queryset):
        n = sum(lockout.unlock(u, actor=request.user, request=request) for u in self._manageable(request, queryset))
        self.message_user(request, f"Cuentas desbloqueadas: {n}.", messages.SUCCESS if n else messages.INFO)

    @admin.action(description="Bloquear las cuentas seleccionadas (bloqueo administrativo)")
    def lock_accounts(self, request, queryset):
        users = self._manageable(request, queryset)
        if any(u.effective_role == Role.ADMIN for u in users) and _other_active_admins(None) - sum(
                u.effective_role == Role.ADMIN and u.is_active and u.locked_at is None for u in users) < 1:
            self.message_user(request, "No se puede dejar al sistema sin un administrador activo y desbloqueado.", messages.ERROR)
            return
        n = sum(lockout.lock(u, "Bloqueo administrativo desde el panel.", actor=request.user, request=request) for u in users)
        self.message_user(request, f"Cuentas bloqueadas: {n} (sus sesiones se cerraron).", messages.SUCCESS if n else messages.INFO)

    @admin.action(description="Exigir cambio de contraseña en el próximo ingreso")
    def force_password_change(self, request, queryset):
        users = [u for u in self._manageable(request, queryset) if not u.must_change_password]
        CustomUser.objects.filter(pk__in=[u.pk for u in users]).update(must_change_password=True, updated_at=timezone.now())
        for u in users:
            record("password_change_required", Category.USERS, f"Se exige a «{u.username}» cambiar su contraseña.",
                   request=request, target=u)
        self.message_user(request, f"Cuentas marcadas: {len(users)}.", messages.SUCCESS if users else messages.INFO)

    @admin.action(description="Cerrar las sesiones activas de las cuentas seleccionadas")
    def close_user_sessions(self, request, queryset):
        n = sum(sessions.end_user_sessions(u, sessions.Reason.ADMIN) for u in self._manageable(request, queryset))
        if n:
            record("sessions_closed", Category.AUTH, f"Se cerraron {n} sesión(es) desde Usuarios del panel.", request=request,
                   target_type="user_session", details={"cantidad": n})
        self.message_user(request, f"Sesiones cerradas: {n}.", messages.SUCCESS if n else messages.INFO)

    @admin.action(description="Activar las cuentas seleccionadas")
    def activate_accounts(self, request, queryset):
        users = [u for u in self._manageable(request, queryset) if not u.is_active]
        for u in users:
            u.is_active = True
            u.save(update_fields=["is_active", "updated_at"])
            record("user_activated", Category.USERS, f"Cuenta «{u.username}» reactivada desde el panel.", request=request, target=u)
        self.message_user(request, f"Cuentas activadas: {len(users)}.", messages.SUCCESS if users else messages.INFO)

    @admin.action(description="Desactivar las cuentas seleccionadas")
    def deactivate_accounts(self, request, queryset):
        users = [u for u in self._manageable(request, queryset) if u.is_active]
        admins = sum(u.effective_role == Role.ADMIN and u.locked_at is None for u in users)
        if admins and _other_active_admins(None) - admins < 1:
            self.message_user(request, "No se puede dejar al sistema sin un administrador activo y desbloqueado.", messages.ERROR)
            return
        for u in users:
            u.is_active = False
            u.save(update_fields=["is_active", "updated_at"])
            sessions.end_user_sessions(u, sessions.Reason.DEACTIVATED)
            record("user_deactivated", Category.USERS, f"Cuenta «{u.username}» desactivada desde el panel.", request=request, target=u)
        self.message_user(request, f"Cuentas desactivadas: {len(users)}.", messages.SUCCESS if users else messages.INFO)
