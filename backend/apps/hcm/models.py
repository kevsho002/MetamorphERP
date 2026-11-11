"""Esquema `hcm`: Empleados y Expediente Digital (SQL-first, managed = False)."""

from django.db import models
from django.db.models import Value
from django.db.models.functions import Now

from apps.common.fields import AuditColumns, RowVersionField, sql_table
from apps.common.models import CostCenter, Country


class Employee(AuditColumns):
    """hcm.Employee ("Empleados"). EmployeeCode lo genera core.usp_GenerateEmployeeCode."""

    class Status(models.TextChoices):
        # Ciclo de vida oficial (Fase 7): Activo, Inactivo y Terminado (script 096).
        ACTIVE = "ACTIVE", "Activo"
        INACTIVE = "INACTIVE", "Inactivo"
        TERMINATED = "TERMINATED", "Terminado"

    class PayFrequency(models.TextChoices):
        MONTHLY = "MONTHLY", "Mensual"
        BIWEEKLY = "BIWEEKLY", "Quincenal"
        WEEKLY = "WEEKLY", "Semanal"

    class Gender(models.TextChoices):
        MALE = "M", "Masculino"
        FEMALE = "F", "Femenino"
        OTHER = "X", "No binario / no especificado"

    employee_id = models.AutoField(db_column="EmployeeId", primary_key=True)
    employee_code = models.CharField(db_column="EmployeeCode", max_length=40, unique=True)
    country = models.ForeignKey(Country, models.DO_NOTHING, db_column="CountryId", related_name="employees")
    first_name = models.CharField(db_column="FirstName", max_length=100)
    middle_name = models.CharField(db_column="MiddleName", max_length=100, null=True, blank=True)
    last_name = models.CharField(db_column="LastName", max_length=100)
    second_last_name = models.CharField(db_column="SecondLastName", max_length=100, null=True, blank=True)
    national_id_type = models.CharField(db_column="NationalIdType", max_length=20)
    national_id_number = models.CharField(db_column="NationalIdNumber", max_length=30)
    birth_date = models.DateField(db_column="BirthDate")
    gender = models.CharField(db_column="Gender", max_length=1, choices=Gender, null=True, blank=True)
    work_email = models.EmailField(db_column="WorkEmail", max_length=254, null=True, blank=True)
    personal_email = models.EmailField(db_column="PersonalEmail", max_length=254, null=True, blank=True)
    phone_number = models.CharField(db_column="PhoneNumber", max_length=30, null=True, blank=True)
    hire_date = models.DateField(db_column="HireDate")
    termination_date = models.DateField(db_column="TerminationDate", null=True, blank=True)
    employment_status = models.CharField(
        db_column="EmploymentStatus", max_length=20, choices=Status, db_default=Value(Status.ACTIVE)
    )
    base_salary = models.DecimalField(db_column="BaseSalary", max_digits=18, decimal_places=2)
    pay_frequency = models.CharField(
        db_column="PayFrequency", max_length=15, choices=PayFrequency, db_default=Value(PayFrequency.MONTHLY)
    )
    # FK compuesta (CostCenterId, CountryId) en BD (script 060): el centro de costos
    # siempre pertenece al país del empleado.
    cost_center = models.ForeignKey(
        CostCenter,
        models.DO_NOTHING,
        db_column="CostCenterId",
        null=True,
        blank=True,
        related_name="employees",
        verbose_name="centro de costos",
    )
    row_ver = RowVersionField()

    class Meta:
        managed = False
        db_table = sql_table("hcm", "Employee")
        ordering = ["employee_code"]
        verbose_name = "empleado"

    def __str__(self) -> str:
        return f"{self.employee_code} {self.full_name}"

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.middle_name, self.last_name, self.second_last_name]
        return " ".join(p for p in parts if p)


class DigitalFile(AuditColumns):
    """hcm.DigitalFile ("ExpedientesDigitales"), 1:1 con Employee."""

    class Status(models.TextChoices):
        OPEN = "OPEN", "Abierto"
        ARCHIVED = "ARCHIVED", "Archivado"

    digital_file_id = models.AutoField(db_column="DigitalFileId", primary_key=True)
    employee = models.OneToOneField(Employee, models.DO_NOTHING, db_column="EmployeeId", related_name="digital_file")
    file_status = models.CharField(db_column="FileStatus", max_length=20, db_default=Value("OPEN"))
    opened_at = models.DateTimeField(db_column="OpenedAt", db_default=Now())
    closed_at = models.DateTimeField(db_column="ClosedAt", null=True, blank=True)
    notes = models.CharField(db_column="Notes", max_length=1000, null=True, blank=True)

    class Meta:
        managed = False
        db_table = sql_table("hcm", "DigitalFile")


class DocumentType(models.Model):
    """hcm.catDocumentType."""

    document_type_id = models.AutoField(db_column="DocumentTypeId", primary_key=True)
    code = models.CharField(db_column="Code", max_length=30, unique=True)
    name = models.CharField(db_column="Name", max_length=150)
    country = models.ForeignKey(Country, models.DO_NOTHING, db_column="CountryId", null=True, blank=True)
    is_mandatory = models.BooleanField(db_column="IsMandatory", db_default=Value(False))
    requires_expiry = models.BooleanField(db_column="RequiresExpiry", db_default=Value(False))
    retention_years = models.SmallIntegerField(db_column="RetentionYears", null=True, blank=True)
    is_sensitive = models.BooleanField(db_column="IsSensitive", db_default=Value(False))  # script 095
    is_active = models.BooleanField(db_column="IsActive", db_default=Value(True))
    created_at = models.DateTimeField(db_column="CreatedAt", db_default=Now(), editable=False)

    PROFILE_PHOTO = "PROFILE_PHOTO"

    class Meta:
        managed = False
        db_table = sql_table("hcm", "catDocumentType")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class DigitalFileDocument(models.Model):
    """hcm.DigitalFileDocument — metadatos + hash; el binario va al almacenamiento privado (PRIVATE_MEDIA_ROOT)."""

    document_id = models.BigAutoField(db_column="DocumentId", primary_key=True)
    digital_file = models.ForeignKey(DigitalFile, models.DO_NOTHING, db_column="DigitalFileId", related_name="documents")
    document_type = models.ForeignKey(DocumentType, models.DO_NOTHING, db_column="DocumentTypeId")
    version_number = models.IntegerField(db_column="VersionNumber", db_default=Value(1))
    is_current = models.BooleanField(db_column="IsCurrent", db_default=Value(True))
    original_name = models.CharField(db_column="OriginalName", max_length=255)
    storage_path = models.CharField(db_column="StoragePath", max_length=500)
    mime_type = models.CharField(db_column="MimeType", max_length=100)
    size_bytes = models.BigIntegerField(db_column="SizeBytes")
    sha256_hash = models.CharField(db_column="Sha256Hash", max_length=64)
    issue_date = models.DateField(db_column="IssueDate", null=True, blank=True)
    expiry_date = models.DateField(db_column="ExpiryDate", null=True, blank=True)
    uploaded_at = models.DateTimeField(db_column="UploadedAt", db_default=Now())
    uploaded_by = models.CharField(db_column="UploadedBy", max_length=100, db_default=Value(""))
    image_width = models.IntegerField(db_column="ImageWidth", null=True, blank=True)  # script 095
    image_height = models.IntegerField(db_column="ImageHeight", null=True, blank=True)

    class Meta:
        managed = False
        db_table = sql_table("hcm", "DigitalFileDocument")
