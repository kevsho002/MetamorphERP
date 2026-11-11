"""Esquema `core`: catálogos transversales (SQL-first, managed = False)."""

from django.db import models
from django.db.models import Value
from django.db.models.functions import Now

from apps.common.fields import sql_table


class Country(models.Model):
    """core.catCountry — IdPrefix alimenta el ID corporativo del empleado."""

    country_id = models.AutoField(db_column="CountryId", primary_key=True)
    country_code = models.CharField(db_column="CountryCode", max_length=2, unique=True)
    country_name = models.CharField(db_column="CountryName", max_length=200)
    currency_code = models.CharField(db_column="CurrencyCode", max_length=3)
    id_prefix = models.CharField(db_column="IdPrefix", max_length=20)
    effective_start_date = models.DateField(db_column="EffectiveStartDate")
    effective_end_date = models.DateField(db_column="EffectiveEndDate", null=True, blank=True)
    is_active = models.BooleanField(db_column="IsActive", db_default=Value(True))
    created_at = models.DateTimeField(db_column="CreatedAt", db_default=Now(), editable=False)

    class Meta:
        managed = False
        db_table = sql_table("core", "catCountry")
        ordering = ["country_code"]
        verbose_name = "país"
        verbose_name_plural = "países"

    def __str__(self) -> str:
        return f"{self.country_code} - {self.country_name}"


class EmployeeCodeSequence(models.Model):
    """core.EmployeeCodeSequence — correlativo por país y año (lo administra el SP)."""

    pk = models.CompositePrimaryKey("country", "sequence_year")
    country = models.ForeignKey(Country, models.DO_NOTHING, db_column="CountryId")
    sequence_year = models.SmallIntegerField(db_column="SequenceYear")
    last_value = models.IntegerField(db_column="LastValue", db_default=Value(0))
    updated_at = models.DateTimeField(db_column="UpdatedAt", db_default=Now())

    class Meta:
        managed = False
        db_table = sql_table("core", "EmployeeCodeSequence")


class CostCenter(models.Model):
    """core.catCostCenter — centro de costos por país (jerárquico)."""

    cost_center_id = models.AutoField(db_column="CostCenterId", primary_key=True)
    country = models.ForeignKey(Country, models.DO_NOTHING, db_column="CountryId", related_name="cost_centers")
    code = models.CharField(db_column="Code", max_length=20, unique=True)
    name = models.CharField(db_column="Name", max_length=150)
    parent = models.ForeignKey(
        "self", models.DO_NOTHING, db_column="ParentCostCenterId", null=True, blank=True, related_name="children"
    )
    effective_start_date = models.DateField(db_column="EffectiveStartDate", db_default=Now())
    effective_end_date = models.DateField(db_column="EffectiveEndDate", null=True, blank=True)
    is_active = models.BooleanField(db_column="IsActive", db_default=Value(True))
    created_at = models.DateTimeField(db_column="CreatedAt", db_default=Now(), editable=False)
    created_by = models.CharField(db_column="CreatedBy", max_length=100, db_default=Value(""), editable=False)

    class Meta:
        managed = False
        db_table = sql_table("core", "catCostCenter")
        ordering = ["code"]
        verbose_name = "centro de costos"
        verbose_name_plural = "centros de costos"

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"
