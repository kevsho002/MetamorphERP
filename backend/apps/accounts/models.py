"""Usuario del sistema (CustomUser) — extiende AbstractUser de Django.

Enlace con el dominio HCM:
- `employee`  -> hcm.Employee por su ID corporativo (EmployeeCode, generado por
  país con core.usp_GenerateEmployeeCode). La columna física es
  `employee_code`, con FK real a hcm.Employee(EmployeeCode) (migración 0002).
- `cost_center` -> core.catCostCenter.
- `role`      -> rol RBAC único (ver apps/accounts/roles.py).
"""

from django.contrib.auth.models import AbstractUser, Group, Permission, UserManager
from django.db import models

from apps.accounts.roles import Role
from apps.common.fields import sql_table
from apps.common.models import CostCenter
from apps.hcm.models import Employee


class CustomUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", Role.ADMIN)
        return super().create_superuser(username, email, password, **extra_fields)


class CustomUser(AbstractUser):
    role = models.CharField("rol", max_length=20, choices=Role, default=Role.EMPLOYEE, db_index=True)
    employee = models.OneToOneField(
        Employee,
        on_delete=models.PROTECT,
        to_field="employee_code",
        db_column="employee_code",
        db_constraint=False,  # FK explícita en 0002 (la tabla destino es SQL-first)
        null=True,
        blank=True,
        related_name="user_account",
        verbose_name="ID corporativo del empleado",
    )
    cost_center = models.ForeignKey(
        CostCenter,
        on_delete=models.PROTECT,
        db_column="cost_center_id",
        db_constraint=False,  # FK explícita en 0002
        null=True,
        blank=True,
        related_name="users",
        verbose_name="centro de costos",
    )
    must_change_password = models.BooleanField(
        "debe cambiar la contraseña",
        default=False,
        help_text="Se activa tras un reseteo administrativo; bloquea la API hasta que el usuario la cambie.",
    )
    password_changed_at = models.DateTimeField("último cambio de contraseña", null=True, blank=True)
    # Fase 25: bloqueo de la cuenta (intentos fallidos o decisión administrativa). Una cuenta bloqueada NO supera la
    # autenticación (apps.accounts.backends) aunque la contraseña sea correcta; se desbloquea desde /admin/.
    failed_login_count = models.PositiveSmallIntegerField("intentos fallidos consecutivos", default=0)
    last_failed_login_at = models.DateTimeField("último intento fallido", null=True, blank=True)
    locked_at = models.DateTimeField("bloqueada desde", null=True, blank=True, db_index=True)
    lock_reason = models.CharField("motivo del bloqueo", max_length=200, blank=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    # Fase 25: la cuenta vive en el esquema de seguridad (sec); las tablas M2M heredadas de PermissionsMixin se nombran
    # explícitamente para que también queden en sec (Django las derivaría de db_table).
    groups = models.ManyToManyField(
        Group, verbose_name="groups", blank=True, related_name="user_set", related_query_name="user",
        db_table=sql_table("sec", "accounts_customuser_groups"),
        help_text="The groups this user belongs to. A user will get all permissions granted to each of their groups.",
    )
    user_permissions = models.ManyToManyField(
        Permission, verbose_name="user permissions", blank=True, related_name="user_set", related_query_name="user",
        db_table=sql_table("sec", "accounts_customuser_user_permissions"),
        help_text="Specific permissions for this user.",
    )

    objects = CustomUserManager()

    class Meta:
        db_table = sql_table("sec", "accounts_customuser")
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        ordering = ["username"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=Role.values),
                name="ck_customuser_role",
            ),
            models.CheckConstraint(
                condition=models.Q(locked_at__isnull=True) | ~models.Q(lock_reason=""),
                name="ck_customuser_lock_reason",
            ),
        ]

    @property
    def is_locked(self) -> bool:
        return self.locked_at is not None

    @property
    def employee_code(self) -> str | None:
        return self.employee_id  # to_field: la columna guarda el EmployeeCode

    @property
    def effective_role(self) -> str:
        """Un superusuario de Django siempre opera como Administrador."""
        return Role.ADMIN if self.is_superuser else self.role

    # El rol ADMIN obtiene todos los permisos de modelo del admin de Django (además de is_staff).
    # Las restricciones sobre superusuarios se aplican en CustomUserAdmin.
    def has_perm(self, perm, obj=None):
        if self.is_active and self.role == Role.ADMIN:
            return True
        return super().has_perm(perm, obj)

    def has_module_perms(self, app_label):
        if self.is_active and self.role == Role.ADMIN:
            return True
        return super().has_module_perms(app_label)

    def save(self, *args, **kwargs):
        # El acceso al admin de Django se deriva del rol (no se asigna a mano).
        self.is_staff = self.is_superuser or self.role == Role.ADMIN
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "role" in update_fields:
            kwargs["update_fields"] = {*update_fields, "is_staff"}
        super().save(*args, **kwargs)
