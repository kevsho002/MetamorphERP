"""Fase 3 — Alta de empleados con modelo dinámico (EAV + plantillas JSON por país).

Tablas administradas por migraciones de Django (esquema dbo, prefijo hcm_):

* AttributeDefinition      catálogo global de atributos dinámicos (la "A" del EAV).
* EmployeeTemplate         plantilla JSON por país y fecha de efectividad: qué campos
                           exige cada país y con qué reglas (patrón, opciones, rangos).
* EmployeeAttributeValue   valores EAV por empleado (la "V"), validados contra la
                           plantilla vigente a la fecha de ingreso del empleado.
* ImportBatch / ImportBatchRow   cargas masivas (CSV / Excel / JSON) y su reporte
                           fila por fila en lenguaje natural.

Las FK hacia tablas SQL-first (core.catCountry, hcm.Employee) se crean en la
migración 0002 con la convención FK_ del proyecto.
"""

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q

from apps.common.fields import sql_table
from apps.common.models import Country
from apps.hcm.models import Employee


class DataType(models.TextChoices):
    STRING = "STRING", "Texto"
    INTEGER = "INTEGER", "Número entero"
    DECIMAL = "DECIMAL", "Número decimal"
    DATE = "DATE", "Fecha"
    BOOLEAN = "BOOLEAN", "Sí / No"
    CHOICE = "CHOICE", "Lista de opciones"
    EMAIL = "EMAIL", "Correo electrónico"


class AttributeDefinition(models.Model):
    """Atributo dinámico reutilizable. Cada plantilla de país decide si lo usa y con qué reglas."""

    code = models.CharField(
        "código",
        max_length=50,
        unique=True,
        validators=[RegexValidator(r"^[a-z][a-z0-9_]*$", "Use minúsculas, dígitos y guion bajo; debe iniciar con letra.")],
        help_text="Identificador estable (snake_case). Es el nombre de columna en las cargas masivas.",
    )
    name = models.CharField("nombre", max_length=150)
    data_type = models.CharField("tipo de dato", max_length=10, choices=DataType, default=DataType.STRING)
    description = models.CharField("descripción", max_length=500, blank=True)
    is_sensitive = models.BooleanField(
        "dato sensible", default=False, help_text="Datos personales protegidos (identificaciones, cuentas bancarias)."
    )
    is_active = models.BooleanField("activo", default=True)
    created_at = models.DateTimeField("creado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        db_table = sql_table("hcm", "hcm_attribute_definition")
        ordering = ["code"]
        verbose_name = "atributo dinámico"
        verbose_name_plural = "atributos dinámicos"
        constraints = [
            models.CheckConstraint(condition=Q(data_type__in=DataType.values), name="ck_attribute_definition_data_type"),
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.get_data_type_display()})"


class EmployeeTemplateQuerySet(models.QuerySet):
    def effective_for(self, country, on_date):
        """Plantilla ACTIVA del país con la mayor fecha de efectividad <= on_date."""
        return self.filter(country=country, is_active=True, effective_date__lte=on_date).order_by("-effective_date").first()


class EmployeeTemplate(models.Model):
    """Plantilla de datos del empleado para un país, vigente desde `effective_date`.

    Versionado por fecha efectiva: un cambio normativo = nueva fila con nueva
    fecha; la plantilla aplicable a un empleado es la última vigente a su fecha
    de ingreso. El contenido (`schema`) se valida con apps.employees.schema.
    """

    country = models.ForeignKey(
        Country,
        on_delete=models.PROTECT,
        db_column="country_id",
        db_constraint=False,  # FK explícita en 0002 (core.catCountry es SQL-first)
        related_name="employee_templates",
        verbose_name="país",
    )
    name = models.CharField("nombre", max_length=150)
    effective_date = models.DateField("vigente desde")
    is_active = models.BooleanField("activa", default=True)
    schema = models.JSONField(
        "definición JSON",
        default=dict,
        help_text="Claves: core_fields, attributes, rules. Ver README (sección Fase 3).",
    )
    notes = models.TextField("notas", blank=True)
    created_by = models.CharField("creado por", max_length=150, blank=True, editable=False)
    created_at = models.DateTimeField("creada", auto_now_add=True)
    updated_at = models.DateTimeField("actualizada", auto_now=True)

    objects = EmployeeTemplateQuerySet.as_manager()

    class Meta:
        db_table = sql_table("hcm", "hcm_employee_template")
        ordering = ["country_id", "-effective_date"]
        verbose_name = "plantilla de empleado por país"
        verbose_name_plural = "plantillas de empleado por país"
        constraints = [
            models.UniqueConstraint(fields=["country", "effective_date"], name="uq_employee_template_country_date"),
        ]
        indexes = [models.Index(fields=["country", "is_active", "effective_date"], name="ix_employee_template_lookup")]

    def __str__(self) -> str:
        return f"{self.name} (desde {self.effective_date:%d/%m/%Y})"

    def clean(self):
        from apps.employees.schema import validate_template_schema

        validate_template_schema(self.schema)

    @property
    def in_use(self) -> bool:
        """Ya validó datos reales: su contenido no debe cambiarse (cree una nueva versión)."""
        return bool(self.pk) and (self.attribute_values.exists() or self.import_rows.filter(employee__isnull=False).exists())


class EmployeeAttributeValue(models.Model):
    """Valor de un atributo dinámico para un empleado (EAV).

    `value` guarda la forma CANÓNICA del dato (fecha ISO, decimal con punto,
    true/false, opción normalizada), de modo que es comparable y ordenable.
    """

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        db_column="employee_id",
        db_constraint=False,  # FK explícita en 0002 (hcm.Employee es SQL-first)
        related_name="attribute_values",
        verbose_name="empleado",
    )
    attribute = models.ForeignKey(
        AttributeDefinition, on_delete=models.PROTECT, related_name="values", verbose_name="atributo"
    )
    value = models.CharField("valor", max_length=500)
    template = models.ForeignKey(
        EmployeeTemplate,
        on_delete=models.PROTECT,
        related_name="attribute_values",
        verbose_name="plantilla que lo validó",
    )
    updated_at = models.DateTimeField("actualizado", auto_now=True)
    updated_by = models.CharField("actualizado por", max_length=150, blank=True)

    class Meta:
        db_table = sql_table("hcm", "hcm_employee_attribute_value")
        ordering = ["employee_id", "attribute__code"]
        verbose_name = "valor de atributo dinámico"
        verbose_name_plural = "valores de atributos dinámicos"
        constraints = [
            models.UniqueConstraint(fields=["employee", "attribute"], name="uq_employee_attribute_value"),
        ]
        indexes = [models.Index(fields=["attribute", "value"], name="ix_attribute_value_lookup")]

    def __str__(self) -> str:
        return f"{self.attribute.code} = {self.value}"


class SourceFormat(models.TextChoices):
    CSV = "CSV", "CSV"
    XLSX = "XLSX", "Excel (.xlsx)"
    JSON = "JSON", "JSON"


class Atomicity(models.TextChoices):
    COUNTRY = "COUNTRY", "Todo o nada por país"
    ROW = "ROW", "Fila por fila"


class BatchStatus(models.TextChoices):
    COMPLETED = "COMPLETED", "Completada"
    PARTIAL = "PARTIAL", "Completada con errores"
    FAILED = "FAILED", "Sin altas"
    DRY_RUN = "DRY_RUN", "Solo validación"


class RowStatus(models.TextChoices):
    CREATED = "CREATED", "Creado"
    VALID = "VALID", "Válida (solo validación)"
    ERROR = "ERROR", "Con errores"
    NOT_APPLIED = "NOT_APPLIED", "Válida, no aplicada"


class ImportBatch(models.Model):
    """Carga masiva de empleados y su reporte."""

    SourceFormat = SourceFormat
    Atomicity = Atomicity
    Status = BatchStatus

    source_format = models.CharField("formato", max_length=5, choices=SourceFormat)
    file_name = models.CharField("archivo", max_length=255)
    file_sha256 = models.CharField("SHA-256 del archivo", max_length=64, blank=True)
    atomicity = models.CharField("atomicidad", max_length=10, choices=Atomicity, default=Atomicity.COUNTRY)
    dry_run = models.BooleanField("solo validar", default=False)
    status = models.CharField("estado", max_length=10, choices=Status)
    total_rows = models.PositiveIntegerField("filas", default=0)
    created_rows = models.PositiveIntegerField("empleados creados", default=0)
    warning_rows = models.PositiveIntegerField("filas con advertencias", default=0)
    error_rows = models.PositiveIntegerField("filas con errores", default=0)
    skipped_rows = models.PositiveIntegerField("filas válidas no aplicadas", default=0)
    summary = models.TextField("resumen", blank=True)
    notes = models.JSONField("observaciones del archivo", default=list, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_imports",
        verbose_name="ejecutada por",
    )
    started_at = models.DateTimeField("inicio")
    finished_at = models.DateTimeField("fin")

    class Meta:
        db_table = sql_table("hcm", "hcm_import_batch")
        ordering = ["-started_at"]
        verbose_name = "carga masiva de empleados"
        verbose_name_plural = "cargas masivas de empleados"
        constraints = [
            models.CheckConstraint(condition=Q(status__in=BatchStatus.values), name="ck_import_batch_status"),
            models.CheckConstraint(condition=Q(atomicity__in=Atomicity.values), name="ck_import_batch_atomicity"),
        ]

    def __str__(self) -> str:
        return f"Lote #{self.pk} · {self.file_name}"


class ImportBatchRow(models.Model):
    """Resultado de UNA fila del archivo, con retroalimentación en lenguaje natural."""

    Status = RowStatus

    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="rows", verbose_name="lote")
    row_number = models.PositiveIntegerField("fila")
    status = models.CharField("estado", max_length=12, choices=Status)
    country = models.ForeignKey(
        Country,
        on_delete=models.PROTECT,
        db_column="country_id",
        db_constraint=False,  # FK explícita en 0002
        null=True,
        blank=True,
        related_name="+",
        verbose_name="país",
    )
    template = models.ForeignKey(
        EmployeeTemplate,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="import_rows",
        verbose_name="plantilla aplicada",
    )
    employee = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        db_column="employee_id",
        db_constraint=False,  # FK explícita en 0002
        null=True,
        blank=True,
        related_name="+",
        verbose_name="empleado creado",
    )
    employee_code = models.CharField("ID corporativo", max_length=40, blank=True)
    errors = models.JSONField("errores", default=list, blank=True)
    warnings = models.JSONField("advertencias", default=list, blank=True)
    feedback = models.TextField("retroalimentación")
    raw_data = models.JSONField("datos recibidos", default=dict, blank=True)

    class Meta:
        db_table = sql_table("hcm", "hcm_import_batch_row")
        ordering = ["batch_id", "row_number"]
        verbose_name = "fila de carga masiva"
        verbose_name_plural = "filas de carga masiva"
        constraints = [
            models.UniqueConstraint(fields=["batch", "row_number"], name="uq_import_batch_row"),
            models.CheckConstraint(condition=Q(status__in=RowStatus.values), name="ck_import_batch_row_status"),
        ]
        indexes = [models.Index(fields=["batch", "status"], name="ix_import_batch_row_status")]

    def __str__(self) -> str:
        return f"Fila {self.row_number} · {self.get_status_display()}"


class Bank(models.Model):
    """Catálogo de bancos por país (Fase 7). Alimenta la lista desplegable de los campos de
    plantilla con la regla ``"catalog": "BANK"`` (p. ej. «Banco para pago de planilla»).

    El empleado guarda el CÓDIGO del banco (estable); el nombre puede corregirse aquí sin
    tocar los expedientes. Los bancos no se borran: se desactivan.
    """

    country = models.ForeignKey(
        Country,
        on_delete=models.PROTECT,
        db_column="country_id",
        db_constraint=False,  # FK explícita en 0005 (core.catCountry es SQL-first)
        related_name="banks",
        verbose_name="país",
    )
    code = models.CharField(
        "código",
        max_length=20,
        validators=[RegexValidator(r"^[A-Z0-9][A-Z0-9_]*$", "Use MAYÚSCULAS, dígitos y guion bajo.")],
        help_text="Valor que se guarda en el expediente y se acepta en cargas masivas (también se acepta el nombre).",
    )
    name = models.CharField("nombre", max_length=150)
    swift_code = models.CharField(
        "código SWIFT/BIC",
        max_length=11,
        blank=True,
        validators=[RegexValidator(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$", "SWIFT/BIC de 8 u 11 caracteres.")],
    )
    display_order = models.PositiveSmallIntegerField("orden", default=100)
    is_active = models.BooleanField("activo", default=True)
    created_at = models.DateTimeField("creado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        db_table = sql_table("hcm", "hcm_bank")
        ordering = ["country_id", "display_order", "name"]
        verbose_name = "banco"
        verbose_name_plural = "bancos"
        constraints = [models.UniqueConstraint(fields=["country", "code"], name="uq_hcm_bank_country_code")]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"
