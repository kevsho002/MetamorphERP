"""Fase 7 — General IDs: identificadores del empleado en herramientas externas (ACD ID, Payroll Tool ID…).

Módulo independiente del roster y de la ficha. Sirve como LLAVE para cruces (JOINs) en reportes:
dado un valor de una herramienta a una fecha, se obtiene un único empleado, y viceversa.

    gid_source_tool         catálogo de herramientas / software de origen (Avaya, Genesys, ADP…)
    gid_id_type             tipos de ID (ACD_ID, PAYROLL_TOOL_ID…): herramienta, reglas del valor,
                            nivel de registro (global / por cliente / por marca) y cardinalidad
    gid_id_type_client      restricción en cascada: el tipo aplica a estos clientes (y a todas sus marcas)
    gid_id_type_brand       restricción: el tipo aplica solo a estas marcas
    gid_employee_general_id valor del ID de un empleado con vigencia [effective_start, effective_end]
                            (effective_end NULL = «Now»). Varios IDs activos a la vez por empleado
                            (uno por tipo/herramienta, o varios si el tipo lo permite).

Integridad en SQL Server (migración 0002): FK a hcm.Employee, CHECK de fechas y un trigger que
impide (a) que un mismo valor de un tipo identifique a dos registros en fechas que se cruzan y
(b) dos IDs simultáneos del mismo tipo para un empleado cuando el tipo no lo permite.
La vista hcm.vw_EmployeeGeneralId expone todo listo para JOINs.
"""

import re

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q

from apps.common.fields import sql_table
from apps.hcm.models import Employee
from apps.operations.models import Brand, Client

UPPER_CODE = RegexValidator(r"^[A-Z][A-Z0-9_]*$", "Use MAYÚSCULAS, dígitos y guion bajo; debe iniciar con letra.")


class ToolCategory(models.TextChoices):
    TELEPHONY = "TELEPHONY", "Telefonía / ACD"
    PAYROLL = "PAYROLL", "Planilla / nómina"
    WFM = "WFM", "Workforce management"
    HRIS = "HRIS", "Recursos humanos"
    CRM = "CRM", "CRM / ticketing del cliente"
    QA = "QA", "Calidad (QA)"
    ACCESS = "ACCESS", "Accesos / directorio"
    OTHER = "OTHER", "Otra"


class SourceTool(models.Model):
    """Herramienta o software de origen del identificador (catálogo parametrizable)."""

    code = models.CharField("código", max_length=30, unique=True, validators=[UPPER_CODE])
    name = models.CharField("nombre", max_length=120)
    category = models.CharField("categoría", max_length=10, choices=ToolCategory, default=ToolCategory.OTHER)
    vendor = models.CharField("proveedor", max_length=120, blank=True)
    description = models.CharField("descripción", max_length=500, blank=True)
    is_active = models.BooleanField("activa", default=True)
    created_at = models.DateTimeField("creada", auto_now_add=True)
    updated_at = models.DateTimeField("actualizada", auto_now=True)

    class Meta:
        db_table = sql_table("hcm", "gid_source_tool")
        ordering = ["name"]
        verbose_name = "herramienta de origen"
        verbose_name_plural = "herramientas de origen"
        constraints = [models.CheckConstraint(condition=Q(category__in=ToolCategory.values), name="ck_gid_source_tool_category")]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class ScopeLevel(models.TextChoices):
    GLOBAL = "GLOBAL", "Global (no se asocia a cliente ni marca)"
    CLIENT = "CLIENT", "Por cliente (marca opcional)"
    BRAND = "BRAND", "Por marca"


class Transform(models.TextChoices):
    NONE = "NONE", "Sin cambios"
    UPPER = "UPPER", "MAYÚSCULAS"
    LOWER = "LOWER", "minúsculas"


class GeneralIdType(models.Model):
    """Tipo de identificador (ACD ID, Payroll Tool ID…) y sus reglas."""

    ScopeLevel = ScopeLevel
    Transform = Transform

    code = models.CharField("código", max_length=30, unique=True, validators=[UPPER_CODE])
    name = models.CharField("nombre", max_length=120)
    tool = models.ForeignKey(SourceTool, on_delete=models.PROTECT, related_name="id_types", verbose_name="herramienta de origen")
    description = models.CharField("descripción", max_length=500, blank=True)
    scope_level = models.CharField(
        "nivel de registro", max_length=6, choices=ScopeLevel, default=ScopeLevel.GLOBAL,
        help_text="Por cliente / por marca: cada ID se registra indicando a qué cliente o marca corresponde.",
    )
    allow_multiple_active = models.BooleanField(
        "varios activos por empleado", default=False,
        help_text="Permite que un empleado tenga varios IDs de este tipo vigentes a la vez (p. ej. un ACD ID por marca).",
    )
    unique_value = models.BooleanField(
        "valor único", default=True,
        help_text="Un valor identifica a un solo registro a la vez (necesario para usarlo como llave de JOIN).",
    )
    pattern = models.CharField("patrón (regex)", max_length=200, blank=True, help_text="Ej.: ^\\d{4,8}$")
    pattern_message = models.CharField("mensaje del patrón", max_length=200, blank=True)
    example = models.CharField("ejemplo", max_length=60, blank=True)
    max_length = models.PositiveSmallIntegerField("longitud máxima", default=60)
    transform = models.CharField("normalización", max_length=5, choices=Transform, default=Transform.NONE)
    display_order = models.PositiveSmallIntegerField("orden", default=100)
    is_active = models.BooleanField("activo", default=True)
    created_at = models.DateTimeField("creado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    clients = models.ManyToManyField(Client, through="GeneralIdTypeClient", related_name="general_id_types", blank=True)
    brands = models.ManyToManyField(Brand, through="GeneralIdTypeBrand", related_name="general_id_types", blank=True)

    class Meta:
        db_table = sql_table("hcm", "gid_id_type")
        ordering = ["display_order", "name"]
        verbose_name = "tipo de General ID"
        verbose_name_plural = "tipos de General ID"
        constraints = [
            models.CheckConstraint(condition=Q(scope_level__in=ScopeLevel.values), name="ck_gid_id_type_scope"),
            models.CheckConstraint(condition=Q(transform__in=Transform.values), name="ck_gid_id_type_transform"),
            models.CheckConstraint(condition=Q(max_length__gte=1, max_length__lte=100), name="ck_gid_id_type_max_length"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    def clean(self):
        if self.pattern:
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValidationError({"pattern": f"Expresión regular inválida: {exc}."}) from None
        if self.pk and self.scope_level == ScopeLevel.GLOBAL and (self.client_scopes.exists() or self.brand_scopes.exists()):
            raise ValidationError(
                {"scope_level": "Tiene restricciones por cliente/marca: use «Por cliente» o «Por marca» (o quite las restricciones)."}
            )


class GeneralIdTypeClient(models.Model):
    """El tipo aplica a este cliente y, en cascada, a todas sus marcas."""

    id_type = models.ForeignKey(GeneralIdType, on_delete=models.CASCADE, related_name="client_scopes", verbose_name="tipo de ID")
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="general_id_scopes", verbose_name="cliente")

    class Meta:
        db_table = sql_table("hcm", "gid_id_type_client")
        verbose_name = "General ID que aplica al cliente"
        verbose_name_plural = "General IDs que aplican al cliente (y a todas sus marcas)"
        constraints = [models.UniqueConstraint(fields=["id_type", "client"], name="uq_gid_id_type_client")]

    def __str__(self) -> str:
        return f"{self.id_type.code} → {self.client.code}"

    def clean(self):
        if self.id_type_id and self.id_type.scope_level == ScopeLevel.GLOBAL:
            raise ValidationError({"id_type": "Este tipo es Global: cámbielo a «Por cliente» o «Por marca» para restringirlo."})


class GeneralIdTypeBrand(models.Model):
    """El tipo aplica SOLO a esta marca (si el cliente completo no está habilitado)."""

    id_type = models.ForeignKey(GeneralIdType, on_delete=models.CASCADE, related_name="brand_scopes", verbose_name="tipo de ID")
    brand = models.ForeignKey(Brand, on_delete=models.CASCADE, related_name="general_id_scopes", verbose_name="marca")

    class Meta:
        db_table = sql_table("hcm", "gid_id_type_brand")
        verbose_name = "General ID que aplica a la marca"
        verbose_name_plural = "General IDs que aplican a la marca"
        constraints = [models.UniqueConstraint(fields=["id_type", "brand"], name="uq_gid_id_type_brand")]

    def __str__(self) -> str:
        return f"{self.id_type.code} → {self.brand.code}"

    def clean(self):
        if self.id_type_id and self.id_type.scope_level == ScopeLevel.GLOBAL:
            raise ValidationError({"id_type": "Este tipo es Global: cámbielo a «Por cliente» o «Por marca» para restringirlo."})


class EmployeeGeneralIdQuerySet(models.QuerySet):
    def overlapping(self, start, end):
        """Intervalos que se cruzan con [start, end] (end None = sin límite)."""
        qs = self.filter(Q(effective_end__isnull=True) | Q(effective_end__gte=start))
        return qs if end is None else qs.filter(effective_start__lte=end)

    def as_of(self, on_date):
        return self.overlapping(on_date, on_date)


class EmployeeGeneralId(models.Model):
    """Un ID de un empleado en una herramienta, vigente en [effective_start, effective_end] (NULL = Now)."""

    employee = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        db_column="employee_id",
        db_constraint=False,  # FK explícita en 0002 (hcm.Employee es SQL-first)
        related_name="general_ids",
        verbose_name="empleado",
    )
    id_type = models.ForeignKey(GeneralIdType, on_delete=models.PROTECT, related_name="assignments", verbose_name="tipo de ID")
    value = models.CharField("valor", max_length=100)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name="cliente")
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name="marca")
    effective_start = models.DateField("vigente desde")
    effective_end = models.DateField("vigente hasta", null=True, blank=True)
    notes = models.CharField("notas", max_length=300, blank=True)
    created_at = models.DateTimeField("registrado", auto_now_add=True)
    created_by = models.CharField("registrado por", max_length=150, blank=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)
    updated_by = models.CharField("actualizado por", max_length=150, blank=True)

    objects = EmployeeGeneralIdQuerySet.as_manager()

    class Meta:
        db_table = sql_table("hcm", "gid_employee_general_id")
        ordering = ["employee_id", "id_type__display_order", "effective_start"]
        verbose_name = "General ID del empleado"
        verbose_name_plural = "General IDs de empleados"
        constraints = [
            models.CheckConstraint(
                condition=Q(effective_end__isnull=True) | Q(effective_end__gte=models.F("effective_start")),
                name="ck_gid_employee_general_id_dates",
            ),
            models.CheckConstraint(condition=Q(brand__isnull=True) | Q(client__isnull=False), name="ck_gid_employee_general_id_brand"),
        ]
        indexes = [
            models.Index(fields=["id_type", "value", "effective_start"], name="ix_gid_type_value"),
            models.Index(fields=["employee", "id_type", "effective_start"], name="ix_gid_employee_type"),
        ]

    def __str__(self) -> str:
        return f"{self.id_type.code}={self.value} [{self.effective_start}..{self.effective_end or 'Now'}]"

    @property
    def is_now(self) -> bool:
        return self.effective_end is None
