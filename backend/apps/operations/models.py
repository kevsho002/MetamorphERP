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

from apps.common.fields import sql_table
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
        db_table = sql_table("org", "ops_client")
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
        db_table = sql_table("org", "ops_brand")
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
        db_table = sql_table("org", "ops_line_of_business")
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
        db_table = sql_table("org", "ops_sub_line_of_business")
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


# ==================================================================== Fase 17: jerarquía operativa
class HierarchyLevel(models.TextChoices):
    """Niveles de la jerarquía operativa, de arriba hacia abajo. Cada nivel reporta al inmediato superior."""

    OPS_DIRECTOR = "OPS_DIRECTOR", "Operations Director"
    OPS_MANAGER = "OPS_MANAGER", "Operations Manager"
    ACCOUNT_SUPERVISOR = "ACCOUNT_SUPERVISOR", "Account Supervisor"
    TEAM_MANAGER = "TEAM_MANAGER", "Team Manager"


HIERARCHY_ORDER = [HierarchyLevel.OPS_DIRECTOR, HierarchyLevel.OPS_MANAGER, HierarchyLevel.ACCOUNT_SUPERVISOR,
                   HierarchyLevel.TEAM_MANAGER]
# Dimensión del roster que alimenta cada nivel (misma clave que el nivel).
HIERARCHY_DIMENSIONS = {lvl.value: lvl.label for lvl in HIERARCHY_ORDER}
TEAM_MANAGER_ATTRIBUTE = "team_manager"  # atributo temporal del roster: Team Manager del agente


def parent_level(level: str) -> str | None:
    i = [lvl.value for lvl in HIERARCHY_ORDER].index(level)
    return HIERARCHY_ORDER[i - 1].value if i else None


class OperationalLeader(models.Model):
    """Puesto de liderazgo de la jerarquía operativa ocupado por un colaborador (Fase 17).

    Operations Director ──< Operations Manager ──< Account Supervisor ──< Team Manager

    Cada líder mantiene sincronizado su elemento en la dimensión del roster de su nivel (OPS_DIRECTOR, OPS_MANAGER,
    ACCOUNT_SUPERVISOR, TEAM_MANAGER) con el elemento de su jefe como padre. Al agente se le asigna su Team Manager
    con el atributo temporal del roster «team_manager» (historial por fechas); los niveles superiores se derivan de
    la cadena «reporta a». Un líder no se borra: se desactiva (no puede tener subordinados activos).
    """

    Level = HierarchyLevel

    level = models.CharField("nivel", max_length=20, choices=HierarchyLevel)
    employee = models.ForeignKey(
        "hcm.Employee", on_delete=models.DO_NOTHING, db_column="employee_id",
        db_constraint=False,  # FK explícita en la migración 0004 (hcm.Employee es SQL-first)
        related_name="leader_roles", verbose_name="colaborador",
    )
    reports_to = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="direct_reports", verbose_name="reporta a",
        help_text="Líder del nivel inmediato superior (vacío solo para Operations Director).",
    )
    client = models.ForeignKey(
        Client, on_delete=models.PROTECT, null=True, blank=True, related_name="leaders", verbose_name="cuenta (cliente)",
        help_text="Opcional: cuenta que lidera (filtra la jerarquía por cliente).",
    )
    is_active = models.BooleanField("activo", default=True)
    roster_item = models.OneToOneField(
        RosterDimensionItem, on_delete=models.PROTECT, null=True, blank=True, editable=False, related_name="leader",
        verbose_name="elemento del roster",
    )
    created_at = models.DateTimeField("creado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        db_table = sql_table("org", "ops_leader")
        ordering = ["level", "employee_id"]
        verbose_name = "líder de la jerarquía operativa"
        verbose_name_plural = "jerarquía operativa (líderes)"
        constraints = [
            models.UniqueConstraint(fields=["level", "employee"], name="uq_ops_leader_level_employee"),
            models.CheckConstraint(condition=models.Q(level__in=HierarchyLevel.values), name="ck_ops_leader_level"),
            models.CheckConstraint(
                condition=(models.Q(level=HierarchyLevel.OPS_DIRECTOR, reports_to__isnull=True)
                           | (~models.Q(level=HierarchyLevel.OPS_DIRECTOR) & models.Q(reports_to__isnull=False))),
                name="ck_ops_leader_reports_to",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_level_display()}: {self.employee}"

    @property
    def code(self) -> str:
        return self.employee.employee_code

    def clean(self):
        errors = {}
        expected = parent_level(self.level) if self.level else None
        boss = self.reports_to if self.reports_to_id else None
        if expected is None and boss is not None:
            errors["reports_to"] = "El Operations Director es el nivel superior: no reporta a otro líder."
        elif expected is not None and boss is None:
            errors["reports_to"] = f"Indique el {HierarchyLevel(expected).label} al que reporta."
        elif boss is not None and boss.level != expected:
            errors["reports_to"] = f"Debe reportar a un {HierarchyLevel(expected).label}."
        elif boss is not None and self.is_active and not boss.is_active:
            errors["reports_to"] = f"{boss} está inactivo."
        if self.pk and not self.is_active and self.direct_reports.filter(is_active=True).exists():
            errors["is_active"] = "Tiene subordinados activos: reasígnelos antes de desactivarlo."
        if errors:
            raise ValidationError(errors)

    def sync_roster_item(self) -> None:
        dimension = RosterDimension.objects.filter(code=self.level).first()
        if dimension is None:
            raise ValidationError(f"Falta la dimensión «{self.level}» del roster (migración operations 0003).")
        item = self.roster_item or RosterDimensionItem.objects.filter(dimension=dimension, code=self.code).first()
        if item is None:
            item = RosterDimensionItem(dimension=dimension)
        item.code = self.code
        item.name = self.employee.full_name
        item.is_active = self.is_active
        item.parent = self.reports_to.roster_item if self.reports_to_id else None
        item.save()
        if self.roster_item_id != item.pk:
            OperationalLeader.objects.filter(pk=self.pk).update(roster_item=item)
            self.roster_item = item

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            self.sync_roster_item()
