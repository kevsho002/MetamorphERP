"""Usuario del sistema (CustomUser) — extiende AbstractUser de Django.

Enlace con el dominio HCM:
- `employee`  -> hcm.Employee por su ID corporativo (EmployeeCode, generado por
  país con core.usp_GenerateEmployeeCode). La columna física es
  `employee_code`, con FK real a hcm.Employee(EmployeeCode) (migración 0002).
- `cost_center` -> core.catCostCenter.
- `role`      -> rol RBAC único (ver apps/accounts/roles.py).
"""

from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models

from apps.accounts.roles import Role
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
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    objects = CustomUserManager()

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        ordering = ["username"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=Role.values),
                name="ck_customuser_role",
            ),
        ]

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
