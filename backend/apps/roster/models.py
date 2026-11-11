"""Fase 6 — Dominio de ROSTER operativo, independiente de la ficha del empleado.

La ficha (hcm.Employee + EAV de plantillas por país + expediente) describe a la PERSONA.
El roster describe DÓNDE y EN QUÉ trabaja en cada período: cliente, marca, línea y
sub-línea de negocio, wave de training, fechas clave y datos para reportes.

Modelo dinámico (EAV temporal):

* RosterDimension / RosterDimensionItem  catálogos jerárquicos (Cliente → Marca,
                                          Línea de negocio → Sub-línea, Tipo de documento para reportes...).
* RosterAttribute                         qué datos tiene el roster (se configuran en /admin/ y la
                                          interfaz React los muestra y edita sin cambiar código).
* RosterAssignment                        valor de un atributo para un empleado en un rango de fechas
                                          [effective_start, effective_end]; effective_end NULL = «Now».
                                          Nunca se borra: una corrección marca la fila como
                                          reemplazada (superseded_at) y crea la nueva (historial bitemporal).

Integridad en SQL Server (migración 0002): FKs a hcm.Employee/core.catCountry, un solo
intervalo abierto por atributo, y un trigger que impide intervalos superpuestos.
"""

import uuid

from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q

from apps.common.models import Country
from apps.hcm.models import Employee

DIMENSION_CODE = RegexValidator(r"^[A-Z][A-Z0-9_]*$", "Use MAYÚSCULAS, dígitos y guion bajo; debe iniciar con letra.")
ITEM_CODE = RegexValidator(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", "Use letras, dígitos, punto, guion o guion bajo (sin espacios).")
ATTRIBUTE_CODE = RegexValidator(r"^[a-z][a-z0-9_]*$", "Use minúsculas, dígitos y guion bajo; debe iniciar con letra.")

# Fase 7: estas dimensiones las alimentan las tablas de catálogo de apps.operations (ops_client,
# ops_brand, ops_line_of_business, ops_sub_line_of_business); sus elementos no se editan desde el roster.
CATALOG_DIMENSIONS = {"CLIENT": "Clientes", "BRAND": "Marcas (brands)", "LOB": "Líneas de negocio (LOB)",
                      "SUB_LOB": "Sub-líneas de negocio"}


class RosterDimension(models.Model):
    """Catálogo de valores del roster (p. ej. CLIENT). `parent` define la jerarquía (BRAND -> CLIENT)."""

    code = models.CharField("código", max_length=30, unique=True, validators=[DIMENSION_CODE])
    name = models.CharField("nombre", max_length=100)
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children", verbose_name="dimensión padre",
        help_text="Cada elemento debe pertenecer a un elemento de la dimensión padre (p. ej. cada Marca a un Cliente).",
    )
    is_active = models.BooleanField("activa", default=True)

    class Meta:
        db_table = "roster_dimension"
        ordering = ["name"]
        verbose_name = "dimensión del roster"
        verbose_name_plural = "dimensiones del roster"

    def __str__(self) -> str:
        return self.name


class RosterDimensionItem(models.Model):
    """Elemento de una dimensión (un cliente, una marca, una línea de negocio...)."""

    dimension = models.ForeignKey(RosterDimension, on_delete=models.PROTECT, related_name="items", verbose_name="dimensión")
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children", verbose_name="pertenece a"
    )
    code = models.CharField("código", max_length=40, validators=[ITEM_CODE])
    name = models.CharField("nombre", max_length=150)
    country = models.ForeignKey(
        Country,
        on_delete=models.PROTECT,
        db_column="country_id",
        db_constraint=False,  # FK explícita en 0002 (core.catCountry es SQL-first)
        null=True,
        blank=True,
        related_name="+",
        verbose_name="país",
        help_text="Vacío = aplica a todos los países.",
    )
    is_active = models.BooleanField("activo", default=True)
    created_at = models.DateTimeField("creado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        db_table = "roster_dimension_item"
        ordering = ["dimension__name", "name"]
        verbose_name = "elemento de dimensión"
        verbose_name_plural = "elementos de dimensiones (clientes, marcas, líneas...)"
        constraints = [models.UniqueConstraint(fields=["dimension", "code"], name="uq_roster_dimension_item_code")]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    def clean(self):
        from django.core.exceptions import ValidationError

        dimension = self.dimension if self.dimension_id else None
        if dimension is None:
            return
        if dimension.parent_id and self.parent is None:
            raise ValidationError({"parent": f"Indique a qué {dimension.parent.name.lower()} pertenece."})
        if not dimension.parent_id and self.parent is not None:
            raise ValidationError({"parent": f"La dimensión «{dimension.name}» no es jerárquica: deje vacío este campo."})
        if self.parent is not None and self.parent.dimension_id != dimension.parent_id:
            raise ValidationError({"parent": f"Debe ser un elemento de «{dimension.parent.name}»."})


class DataType(models.TextChoices):
    STRING = "STRING", "Texto"
    INTEGER = "INTEGER", "Número entero"
    DATE = "DATE", "Fecha"
    BOOLEAN = "BOOLEAN", "Sí / No"
    CHOICE = "CHOICE", "Lista de opciones"
    DIMENSION = "DIMENSION", "Elemento de una dimensión"


RULE_KEYS = {"pattern", "pattern_message", "example", "max_length", "min", "max", "not_before", "not_after"}


class RosterAttribute(models.Model):
    """Dato configurable del roster. Lo que se active aquí aparece en la sección Roster de React."""

    DataType = DataType

    code = models.CharField("código", max_length=50, unique=True, validators=[ATTRIBUTE_CODE])
    name = models.CharField("nombre", max_length=120)
    group = models.CharField("grupo", max_length=60, default="Asignación", help_text="Agrupa los campos en la interfaz.")
    display_order = models.PositiveSmallIntegerField("orden", default=100)
    data_type = models.CharField("tipo de dato", max_length=10, choices=DataType, default=DataType.STRING)
    dimension = models.ForeignKey(
        RosterDimension, on_delete=models.PROTECT, null=True, blank=True, related_name="attributes", verbose_name="dimensión"
    )
    depends_on = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="dependents", verbose_name="depende de",
        help_text="Atributo de la dimensión padre (p. ej. Marca depende de Cliente): el valor debe pertenecer al vigente.",
    )
    choices = models.JSONField("opciones", default=list, blank=True, help_text='Solo para «Lista de opciones»: ["A", "B"].')
    rules = models.JSONField(
        "reglas",
        default=dict,
        blank=True,
        help_text='Opcional: {"pattern", "pattern_message", "example", "max_length", "min", "max", '
        '"not_before": "código_fecha", "not_after": "código_fecha"}.',
    )
    help = models.CharField("ayuda", max_length=300, blank=True)
    is_active = models.BooleanField("activo", default=True)
    created_at = models.DateTimeField("creado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        db_table = "roster_attribute"
        ordering = ["display_order", "name"]
        verbose_name = "atributo del roster"
        verbose_name_plural = "atributos del roster"
        constraints = [
            models.CheckConstraint(condition=Q(data_type__in=DataType.values), name="ck_roster_attribute_data_type"),
            models.CheckConstraint(
                condition=Q(data_type="DIMENSION", dimension__isnull=False) | (~Q(data_type="DIMENSION") & Q(dimension__isnull=True)),
                name="ck_roster_attribute_dimension",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    def clean(self):
        from django.core.exceptions import ValidationError

        errors = {}
        if self.data_type == DataType.DIMENSION and not self.dimension_id:
            errors["dimension"] = "Seleccione la dimensión."
        if self.data_type != DataType.DIMENSION and self.dimension_id:
            errors["dimension"] = "Solo los atributos de tipo «Elemento de una dimensión» usan dimensión."
        if self.data_type == DataType.CHOICE and (
            not isinstance(self.choices, list) or not self.choices or not all(isinstance(c, str) and c.strip() for c in self.choices)
        ):
            errors["choices"] = "Indique una lista no vacía de opciones de texto."
        if self.depends_on_id:
            parent_dim = self.dimension.parent_id if self.dimension_id else None
            if self.depends_on_id == self.pk:
                errors["depends_on"] = "Un atributo no puede depender de sí mismo."
            elif not parent_dim or self.depends_on.dimension_id != parent_dim:
                errors["depends_on"] = "Debe ser un atributo de la dimensión padre de esta dimensión."
        if not isinstance(self.rules, dict):
            errors["rules"] = "Debe ser un objeto JSON."
        else:
            unknown = set(self.rules) - RULE_KEYS
            if unknown:
                errors["rules"] = f"Reglas desconocidas: {', '.join(sorted(unknown))}. Válidas: {', '.join(sorted(RULE_KEYS))}."
            for key in ("not_before", "not_after"):
                ref = self.rules.get(key)
                if ref is not None and (
                    self.data_type != DataType.DATE
                    or not RosterAttribute.objects.filter(code=ref, data_type=DataType.DATE).exclude(pk=self.pk).exists()
                ):
                    errors["rules"] = f"«{key}» solo aplica a fechas y debe nombrar otro atributo de tipo Fecha."
        if errors:
            raise ValidationError(errors)


class RosterAssignmentQuerySet(models.QuerySet):
    def current(self):
        """Filas vigentes en el conocimiento actual (excluye las reemplazadas por correcciones)."""
        return self.filter(superseded_at__isnull=True)

    def overlapping(self, start, end):
        """Intervalos que se cruzan con [start, end] (end None = sin límite)."""
        qs = self.filter(Q(effective_end__isnull=True) | Q(effective_end__gte=start))
        return qs if end is None else qs.filter(effective_start__lte=end)


class RosterAssignment(models.Model):
    """Valor de un atributo del roster para un empleado en [effective_start, effective_end] (NULL = Now)."""

    employee = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        db_column="employee_id",
        db_constraint=False,  # FK explícita en 0002 (hcm.Employee es SQL-first)
        related_name="roster_assignments",
        verbose_name="empleado",
    )
    attribute = models.ForeignKey(RosterAttribute, on_delete=models.PROTECT, related_name="assignments", verbose_name="atributo")
    value = models.CharField("valor", max_length=500)
    item = models.ForeignKey(
        RosterDimensionItem, on_delete=models.PROTECT, null=True, blank=True, related_name="assignments", verbose_name="elemento"
    )
    effective_start = models.DateField("vigente desde")
    effective_end = models.DateField("vigente hasta", null=True, blank=True)
    reason = models.CharField("motivo", max_length=300, blank=True)
    change_id = models.UUIDField("lote de cambio", default=uuid.uuid4, db_index=True)
    recorded_at = models.DateTimeField("registrado", auto_now_add=True)
    recorded_by = models.CharField("registrado por", max_length=150, blank=True)
    superseded_at = models.DateTimeField("reemplazado", null=True, blank=True)
    superseded_by = models.CharField("reemplazado por", max_length=150, blank=True)

    objects = RosterAssignmentQuerySet.as_manager()

    class Meta:
        db_table = "roster_assignment"
        ordering = ["employee_id", "attribute_id", "effective_start"]
        verbose_name = "asignación de roster"
        verbose_name_plural = "asignaciones de roster"
        constraints = [
            models.CheckConstraint(
                condition=Q(effective_end__isnull=True) | Q(effective_end__gte=models.F("effective_start")),
                name="ck_roster_assignment_dates",
            ),
        ]
        indexes = [
            models.Index(fields=["employee", "attribute", "effective_start"], name="ix_roster_emp_attr_start"),
            models.Index(fields=["attribute", "value", "effective_start"], name="ix_roster_attr_value"),
        ]

    def __str__(self) -> str:
        end = self.effective_end.isoformat() if self.effective_end else "Now"
        return f"{self.attribute.code}={self.value} [{self.effective_start}..{end}]"

    @property
    def is_now(self) -> bool:
        return self.effective_end is None
