from rest_framework import serializers

from apps.accounts.models import CustomUser
from apps.accounts.permissions import user_permissions
from apps.accounts.roles import ROLES_REQUIRING_EMPLOYEE, Role
from apps.common.models import CostCenter
from apps.hcm.models import Employee
from apps.hcm.services.employee_code import is_valid_employee_code


class CostCenterSummarySerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="cost_center_id")

    class Meta:
        model = CostCenter
        fields = ["id", "code", "name"]


class UserSerializer(serializers.ModelSerializer):
    """Representación de lectura (listados, detalle y respuestas de escritura)."""

    role_label = serializers.CharField(source="get_role_display", read_only=True)
    employee_code = serializers.CharField(source="employee_id", read_only=True)
    employee_name = serializers.CharField(source="employee.full_name", read_only=True, default=None)
    employee_country = serializers.CharField(source="employee.country.country_code", read_only=True, default=None)
    cost_center = CostCenterSummarySerializer(read_only=True)
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = [
            "id",
            "username",
            "display_name",
            "first_name",
            "last_name",
            "email",
            "role",
            "role_label",
            "employee_code",
            "employee_name",
            "employee_country",
            "cost_center",
            "is_active",
            "must_change_password",
            "last_login",
            "date_joined",
            "updated_at",
        ]
        read_only_fields = fields

    def get_display_name(self, obj) -> str:
        return obj.get_full_name() or obj.username


class CurrentUserSerializer(UserSerializer):
    """/auth/me: incluye los permisos efectivos para que el SPA adapte el menú."""

    permissions = serializers.SerializerMethodField()
    is_superuser = serializers.BooleanField(read_only=True)

    class Meta(UserSerializer.Meta):
        fields = [*UserSerializer.Meta.fields, "is_superuser", "permissions"]
        read_only_fields = fields

    def get_permissions(self, obj) -> list[str]:
        return sorted(user_permissions(obj))


class _UserWriteMixin(serializers.Serializer):
    """Vínculo con HCM: ID corporativo del empleado + centro de costos."""

    employee_code = serializers.CharField(max_length=40, required=False, allow_null=True, allow_blank=True)
    cost_center_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_employee_code(self, value):
        if not value:
            return None
        value = value.strip().upper()
        if not is_valid_employee_code(value):
            raise serializers.ValidationError("Formato o dígito verificador inválido (esperado p.ej. SV-2026-000123-7).")
        employee = Employee.objects.select_related("country").filter(employee_code=value).first()
        if employee is None:
            raise serializers.ValidationError("No existe un empleado con ese ID corporativo.")
        if employee.employment_status == Employee.Status.TERMINATED:
            raise serializers.ValidationError("El empleado está retirado.")
        linked = CustomUser.objects.filter(employee_id=value)
        if self.instance is not None:
            linked = linked.exclude(pk=self.instance.pk)
        if linked.exists():
            raise serializers.ValidationError("El empleado ya tiene una cuenta de usuario.")
        return employee

    def validate_cost_center_id(self, value):
        if value is None:
            return None
        cost_center = CostCenter.objects.filter(pk=value, is_active=True).first()
        if cost_center is None:
            raise serializers.ValidationError("Centro de costos inexistente o inactivo.")
        return cost_center

    def validate_employee_links(self, attrs, role: str) -> dict:
        employee = attrs.get("employee_code", getattr(self.instance, "employee", None))
        cost_center = attrs.get("cost_center_id", getattr(self.instance, "cost_center", None))
        if role in ROLES_REQUIRING_EMPLOYEE and employee is None:
            raise serializers.ValidationError(
                {"employee_code": [f"El rol {Role(role).label} requiere un ID corporativo de empleado."]}
            )
        if employee is not None and cost_center is not None and cost_center.country_id != employee.country_id:
            raise serializers.ValidationError(
                {"cost_center_id": ["El centro de costos no pertenece al país del empleado."]}
            )
        return attrs

    def apply_links(self, user: CustomUser, attrs: dict) -> None:
        if "employee_code" in attrs:
            user.employee = attrs["employee_code"]
        if "cost_center_id" in attrs:
            user.cost_center = attrs["cost_center_id"]


class UserCreateSerializer(_UserWriteMixin, serializers.ModelSerializer):
    """Alta de usuario. La contraseña inicial SIEMPRE la genera el servidor (temporal)."""

    role = serializers.ChoiceField(choices=Role.choices, default=Role.EMPLOYEE)

    class Meta:
        model = CustomUser
        fields = ["username", "email", "first_name", "last_name", "role", "employee_code", "cost_center_id"]

    def validate(self, attrs):
        attrs = self.validate_employee_links(attrs, attrs.get("role", Role.EMPLOYEE))
        employee = attrs.get("employee_code")
        if employee is not None:  # valores por defecto desde el expediente
            attrs.setdefault("first_name", employee.first_name)
            attrs.setdefault("last_name", employee.last_name)
            if not attrs.get("email") and employee.work_email:
                attrs["email"] = employee.work_email
        return attrs

    def create(self, validated_data):
        links = {k: validated_data.pop(k) for k in ("employee_code", "cost_center_id") if k in validated_data}
        user = CustomUser(**validated_data, must_change_password=True)
        self.apply_links(user, links)
        user.set_unusable_password()  # la vista asigna la temporal
        user.save()
        return user


class UserUpdateSerializer(_UserWriteMixin, serializers.ModelSerializer):
    """Edición de datos de la cuenta. Rol, estado y contraseña tienen endpoints propios."""

    class Meta:
        model = CustomUser
        fields = ["email", "first_name", "last_name", "employee_code", "cost_center_id"]

    def validate(self, attrs):
        return self.validate_employee_links(attrs, self.instance.role)

    def update(self, instance, validated_data):
        links = {k: validated_data.pop(k) for k in ("employee_code", "cost_center_id") if k in validated_data}
        self.apply_links(instance, links)
        return super().update(instance, validated_data)


class RoleAssignSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=Role.choices)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=128, trim_whitespace=False, style={"input_type": "password"})


class PasswordChangeSerializer(serializers.Serializer):
    """Los validadores de AUTH_PASSWORD_VALIDATORS se aplican en services.change_own_password."""

    current_password = serializers.CharField(max_length=128, trim_whitespace=False)
    new_password = serializers.CharField(max_length=128, trim_whitespace=False)
