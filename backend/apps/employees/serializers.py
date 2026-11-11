from rest_framework import serializers

from apps.accounts.permissions import user_permissions
from apps.accounts.roles import Perm
from apps.employees.models import AttributeDefinition, EmployeeTemplate, ImportBatch, ImportBatchRow
from apps.employees.schema import resolve_template
from apps.hcm.models import Employee


class EmployeeSerializer(serializers.ModelSerializer):
    country = serializers.CharField(source="country.country_code", read_only=True)
    country_name = serializers.CharField(source="country.country_name", read_only=True)
    currency = serializers.CharField(source="country.currency_code", read_only=True)
    cost_center = serializers.CharField(source="cost_center.code", read_only=True, default=None)
    cost_center_name = serializers.CharField(source="cost_center.name", read_only=True, default=None)
    employment_status_label = serializers.CharField(source="get_employment_status_display", read_only=True)
    row_version = serializers.SerializerMethodField()
    restricted_fields = serializers.SerializerMethodField()
    full_name = serializers.CharField(read_only=True)
    attributes = serializers.SerializerMethodField()
    has_user_account = serializers.SerializerMethodField()
    user_account = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = [
            "employee_code", "full_name", "first_name", "middle_name", "last_name", "second_last_name",
            "country", "country_name", "currency", "cost_center", "cost_center_name", "national_id_type",
            "national_id_number", "birth_date", "gender", "work_email", "personal_email", "phone_number", "hire_date",
            "termination_date", "employment_status", "employment_status_label", "base_salary", "pay_frequency",
            "attributes", "has_user_account", "user_account", "restricted_fields", "row_version", "created_at", "created_by",
            "updated_at", "updated_by",
        ]
        read_only_fields = fields

    def _can_see_payroll(self) -> bool:
        request = self.context.get("request")
        return request is None or Perm.PAYROLL_VIEW in user_permissions(request.user)

    def get_attributes(self, obj) -> dict:
        # Atributos sensibles (identificaciones tributarias, cuentas bancarias...) solo con permiso de planilla.
        show_sensitive = self._can_see_payroll()
        return {v.attribute.code: v.value for v in obj.attribute_values.all() if show_sensitive or not v.attribute.is_sensitive}

    def get_restricted_fields(self, obj) -> list[str]:
        """Campos ocultos por RBAC: el frontend muestra «restringido» en lugar de dejarlos vacíos."""
        if self._can_see_payroll():
            return []
        return ["base_salary"] + sorted(v.attribute.code for v in obj.attribute_values.all() if v.attribute.is_sensitive)

    def get_row_version(self, obj) -> str | None:
        return bytes(obj.row_ver).hex() if obj.row_ver is not None else None

    def get_has_user_account(self, obj) -> bool:
        return hasattr(obj, "user_account")

    def get_user_account(self, obj) -> dict | None:
        """Cuenta Metamorph vinculada (FK por ID corporativo). Solo para quien administra usuarios."""
        request = self.context.get("request")
        if request is not None and Perm.USERS_VIEW not in user_permissions(request.user):
            return None
        account = getattr(obj, "user_account", None) if hasattr(obj, "user_account") else None
        if account is None:
            return None
        return {
            "id": account.pk,
            "username": account.username,
            "email": account.email or None,
            "role": account.role,
            "role_label": account.get_role_display(),
            "is_active": account.is_active,
            "must_change_password": account.must_change_password,
            "last_login": account.last_login,
        }

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Salario: dato de planilla. Quien no tiene payroll.view (p. ej. WFM) no lo ve.
        if not self._can_see_payroll():
            data.pop("base_salary", None)
        return data


class EmployeeListSerializer(EmployeeSerializer):
    """Versión liviana para la tabla (sin atributos EAV)."""

    class Meta(EmployeeSerializer.Meta):
        fields = [
            "employee_code", "full_name", "country", "country_name", "currency", "cost_center", "cost_center_name",
            "national_id_type", "national_id_number", "work_email", "hire_date", "termination_date",
            "employment_status", "employment_status_label", "base_salary", "pay_frequency", "has_user_account",
        ]
        read_only_fields = fields


class AttributeDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttributeDefinition
        fields = ["code", "name", "data_type", "description", "is_sensitive", "is_active"]


class EmployeeTemplateSerializer(serializers.ModelSerializer):
    country = serializers.CharField(source="country.country_code", read_only=True)
    country_name = serializers.CharField(source="country.country_name", read_only=True)

    class Meta:
        model = EmployeeTemplate
        fields = ["id", "country", "country_name", "name", "effective_date", "is_active", "schema", "notes", "updated_at"]


class EmployeeTemplateDetailSerializer(EmployeeTemplateSerializer):
    """Incluye la especificación resuelta (campos base + atributos) para construir el formulario."""

    form = serializers.SerializerMethodField()

    class Meta(EmployeeTemplateSerializer.Meta):
        fields = [*EmployeeTemplateSerializer.Meta.fields, "form"]

    def get_form(self, obj) -> dict:
        return resolve_template(obj).as_dict()


class ImportBatchRowSerializer(serializers.ModelSerializer):
    country = serializers.CharField(source="country.country_code", read_only=True, default=None)

    class Meta:
        model = ImportBatchRow
        fields = ["row_number", "status", "country", "employee_code", "feedback", "errors", "warnings", "raw_data"]


class ImportBatchSerializer(serializers.ModelSerializer):
    created_by = serializers.CharField(source="created_by.username", read_only=True, default=None)

    class Meta:
        model = ImportBatch
        fields = [
            "id", "file_name", "source_format", "file_sha256", "atomicity", "dry_run", "status", "total_rows",
            "created_rows", "warning_rows", "error_rows", "skipped_rows", "summary", "notes", "created_by",
            "started_at", "finished_at",
        ]


class ImportRequestSerializer(serializers.Serializer):
    """Opciones de la carga. El archivo llega como multipart `file`, o las filas como JSON `rows`."""

    atomicity = serializers.ChoiceField(choices=ImportBatch.Atomicity.choices, default=ImportBatch.Atomicity.COUNTRY)
    dry_run = serializers.BooleanField(default=False)
    file_name = serializers.CharField(required=False, max_length=255)
