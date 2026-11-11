"""Fase 7 — Catálogos operativos: Clientes, Marcas (brand), Líneas de negocio (LOB) y Sub-líneas.

Son tablas de catálogo propias (esquema dbo, prefijo ops_), parametrizables en /admin/ ›
Catálogos operativos, y son la FUENTE DE VERDAD de esos valores:

    ops_client ──< ops_brand                (cada marca pertenece a un cliente)
    ops_line_of_business ──< ops_sub_line_of_business

Integración con el roster (Fase 6): el roster usa dimensiones genéricas (EAV temporal). Cada
registro de estos catálogos mantiene sincronizado su elemento en `roster_dimension_item`
(dimensiones CLIENT, BRAND, LOB y SUB_LOB) mediante `roster_item`; por eso esas cuatro
dimensiones ya no se editan desde el admin del roster. Las asignaciones históricas del roster
siguen apuntando al mismo elemento aunque el catálogo cambie de nombre.

Las restricciones de los General IDs por cliente / marca (Fase 7) se configuran también aquí,
en la ficha de cada cliente y de cada marca (tablas gid_id_type_client / gid_id_type_brand).
"""

from django.core.exceptions import ValidationError
from django.db import models, transaction

from apps.common.models import Country
from apps.roster.models import ITEM_CODE, RosterDimension, RosterDimensionItem


class CatalogEntry(models.Model):
    """Base común de los catálogos operativos."""

    ROSTER_DIMENSION = ""  # código de la dimensión del roster que este catálogo alimenta

    code = models.CharField(
        "código", max_length=40, unique=True, validators=[ITEM_CODE],
        help_text="Identificador estable (sin espacios). No cambia después de creado: lo usan el roster y los reportes.",
    )
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
        help_text="Vacío = opera en todos los países.",
    )
    description = models.CharField("descripción", max_length=500, blank=True)
    is_active = models.BooleanField("activo", default=True)
    created_at = models.DateTimeField("creado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)
    roster_item = models.OneToOneField(
        RosterDimensionItem,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        editable=False,
        related_name="+",
        verbose_name="elemento del roster",
    )

    class Meta:
        abstract = True
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    # ------------------------------------------------------------ sincronización con el roster
    def roster_parent(self) -> RosterDimensionItem | None:
        return None

    def sync_roster_item(self) -> None:
        dimension = RosterDimension.objects.filter(code=self.ROSTER_DIMENSION).first()
        if dimension is None:
            raise ValidationError(
                f"Falta la dimensión «{self.ROSTER_DIMENSION}» del roster (migración roster 0003)."
            )
        item = self.roster_item or RosterDimensionItem.objects.filter(dimension=dimension, code=self.code).first()
        if item is None:
            item = RosterDimensionItem(dimension=dimension)
        item.code = self.code
        item.name = self.name
        item.country_id = self.country_id
        item.is_active = self.is_active
        item.parent = self.roster_parent()
        item.save()
        if self.roster_item_id != item.pk:
            type(self).objects.filter(pk=self.pk).update(roster_item=item)
            self.roster_item = item

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            self.sync_roster_item()


class Client(CatalogEntry):
    ROSTER_DIMENSION = "CLIENT"

    legal_name = models.CharField("razón social", max_length=200, blank=True)

    class Meta(CatalogEntry.Meta):
        db_table = "ops_client"
        verbose_name = "cliente"
        verbose_name_plural = "clientes"

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.is_active:  # cascada: un cliente inactivo no deja marcas activas
                for brand in self.brands.filter(is_active=True):
                    brand.is_active = False
                    brand.save()


class Brand(CatalogEntry):
    ROSTER_DIMENSION = "BRAND"

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="brands", verbose_name="cliente")

    class Meta(CatalogEntry.Meta):
        db_table = "ops_brand"
        ordering = ["client__name", "name"]
        verbose_name = "marca (brand)"
        verbose_name_plural = "marcas (brands)"

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"

    def clean(self):
        errors = {}
        client = self.client if self.client_id else None
        if client is not None:
            if client.country_id and self.country_id and client.country_id != self.country_id:
                errors["country"] = f"El cliente «{client.name}» opera solo en {client.country}: use ese país o déjelo vacío."
            if self.is_active and not client.is_active:
                errors["is_active"] = f"El cliente «{client.name}» está inactivo: no puede tener marcas activas."
        if errors:
            raise ValidationError(errors)

    def roster_parent(self):
        return self.client.roster_item


class LineOfBusiness(CatalogEntry):
    ROSTER_DIMENSION = "LOB"

    class Meta(CatalogEntry.Meta):
        db_table = "ops_line_of_business"
        verbose_name = "línea de negocio (LOB)"
        verbose_name_plural = "líneas de negocio (LOB)"

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not self.is_active:
                for sub in self.sub_lines.filter(is_active=True):
                    sub.is_active = False
                    sub.save()


class SubLineOfBusiness(CatalogEntry):
    ROSTER_DIMENSION = "SUB_LOB"

    line = models.ForeignKey(
        LineOfBusiness, on_delete=models.PROTECT, related_name="sub_lines", verbose_name="línea de negocio"
    )

    class Meta(CatalogEntry.Meta):
        db_table = "ops_sub_line_of_business"
        ordering = ["line__name", "name"]
        verbose_name = "sub-línea de negocio"
        verbose_name_plural = "sub-líneas de negocio"

    def clean(self):
        line = self.line if self.line_id else None
        if line is not None and self.is_active and not line.is_active:
            raise ValidationError({"is_active": f"La línea «{line.name}» está inactiva: no puede tener sub-líneas activas."})

    def roster_parent(self):
        return self.line.roster_item


CATALOG_MODELS = (Client, Brand, LineOfBusiness, SubLineOfBusiness)
