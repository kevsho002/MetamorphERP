"""Esquema `wfm`: Asistencias, downtimes e ingesta paramétrica (SQL-first, managed = False)."""

from django.db import models
from django.db.models import F, Value
from django.db.models.functions import Now

from apps.common.fields import AuditColumns, RowVersionField, sql_table
from apps.hcm.models import Employee


class IngestionSource(models.Model):
    """wfm.catIngestionSource — origen de datos + Config JSON."""

    source_id = models.AutoField(db_column="SourceId", primary_key=True)
    code = models.CharField(db_column="Code", max_length=30, unique=True)
    name = models.CharField(db_column="Name", max_length=150)
    source_type = models.CharField(db_column="SourceType", max_length=20)
    file_format = models.CharField(db_column="FileFormat", max_length=10, null=True, blank=True)
    time_zone_name = models.CharField(
        db_column="TimeZoneName", max_length=64, db_default=Value("Central America Standard Time")
    )
    config = models.TextField(db_column="Config", null=True, blank=True)
    is_active = models.BooleanField(db_column="IsActive", db_default=Value(True))
    created_at = models.DateTimeField(db_column="CreatedAt", db_default=Now(), editable=False)

    class Meta:
        managed = False
        db_table = sql_table("wfm", "catIngestionSource")


class IngestionFieldMap(models.Model):
    """wfm.IngestionFieldMap — columna origen -> campo canónico."""

    field_map_id = models.AutoField(db_column="FieldMapId", primary_key=True)
    source = models.ForeignKey(IngestionSource, models.DO_NOTHING, db_column="SourceId", related_name="field_maps")
    source_field = models.CharField(db_column="SourceField", max_length=100)
    target_field = models.CharField(db_column="TargetField", max_length=50)
    data_type = models.CharField(db_column="DataType", max_length=20)
    format_pattern = models.CharField(db_column="FormatPattern", max_length=50, null=True, blank=True)
    default_value = models.CharField(db_column="DefaultValue", max_length=100, null=True, blank=True)
    is_required = models.BooleanField(db_column="IsRequired", db_default=Value(True))
    transform_rule = models.CharField(db_column="TransformRule", max_length=100, null=True, blank=True)

    class Meta:
        managed = False
        db_table = sql_table("wfm", "IngestionFieldMap")


class DowntimeType(models.Model):
    """wfm.catDowntimeType."""

    downtime_type_id = models.AutoField(db_column="DowntimeTypeId", primary_key=True)
    code = models.CharField(db_column="Code", max_length=30, unique=True)
    name = models.CharField(db_column="Name", max_length=150)
    is_paid = models.BooleanField(db_column="IsPaid", db_default=Value(True))
    counts_as_worked = models.BooleanField(db_column="CountsAsWorked", db_default=Value(False))
    affects_adherence = models.BooleanField(db_column="AffectsAdherence", db_default=Value(True))
    max_minutes_per_day = models.SmallIntegerField(db_column="MaxMinutesPerDay", null=True, blank=True)
    is_active = models.BooleanField(db_column="IsActive", db_default=Value(True))
    created_at = models.DateTimeField(db_column="CreatedAt", db_default=Now(), editable=False)

    class Meta:
        managed = False
        db_table = sql_table("wfm", "catDowntimeType")


class DowntimeCodeMap(models.Model):
    """wfm.DowntimeCodeMap — código externo del WFM -> tipo interno."""

    pk = models.CompositePrimaryKey("source", "external_code")
    source = models.ForeignKey(IngestionSource, models.DO_NOTHING, db_column="SourceId")
    external_code = models.CharField(db_column="ExternalCode", max_length=50)
    downtime_type = models.ForeignKey(DowntimeType, models.DO_NOTHING, db_column="DowntimeTypeId")

    class Meta:
        managed = False
        db_table = sql_table("wfm", "DowntimeCodeMap")


class IngestionBatch(models.Model):
    """wfm.IngestionBatch — cada carga, deduplicada por (SourceId, Sha256Hash)."""

    batch_id = models.BigAutoField(db_column="BatchId", primary_key=True)
    source = models.ForeignKey(IngestionSource, models.DO_NOTHING, db_column="SourceId", related_name="batches")
    original_name = models.CharField(db_column="OriginalName", max_length=255, null=True, blank=True)
    sha256_hash = models.CharField(db_column="Sha256Hash", max_length=64)
    period_start = models.DateField(db_column="PeriodStart", null=True, blank=True)
    period_end = models.DateField(db_column="PeriodEnd", null=True, blank=True)
    batch_status = models.CharField(db_column="BatchStatus", max_length=20, db_default=Value("RECEIVED"))
    total_rows = models.IntegerField(db_column="TotalRows", db_default=Value(0))
    valid_rows = models.IntegerField(db_column="ValidRows", db_default=Value(0))
    error_rows = models.IntegerField(db_column="ErrorRows", db_default=Value(0))
    received_at = models.DateTimeField(db_column="ReceivedAt", db_default=Now())
    processed_at = models.DateTimeField(db_column="ProcessedAt", null=True, blank=True)
    created_by = models.CharField(db_column="CreatedBy", max_length=100, db_default=Value(""), editable=False)

    class Meta:
        managed = False
        db_table = sql_table("wfm", "IngestionBatch")


class IngestionBatchError(models.Model):
    """wfm.IngestionBatchError — error por fila para reproceso."""

    batch_error_id = models.BigAutoField(db_column="BatchErrorId", primary_key=True)
    batch = models.ForeignKey(IngestionBatch, models.DO_NOTHING, db_column="BatchId", related_name="errors")
    row_number = models.IntegerField(db_column="RowNumber")
    field_name = models.CharField(db_column="FieldName", max_length=100, null=True, blank=True)
    error_code = models.CharField(db_column="ErrorCode", max_length=50)
    error_message = models.CharField(db_column="ErrorMessage", max_length=500)
    raw_data = models.TextField(db_column="RawData", null=True, blank=True)

    class Meta:
        managed = False
        db_table = sql_table("wfm", "IngestionBatchError")


class Attendance(AuditColumns):
    """wfm.Attendance ("Asistencias") — un registro por empleado y día."""

    attendance_id = models.BigAutoField(db_column="AttendanceId", primary_key=True)
    employee = models.ForeignKey(Employee, models.DO_NOTHING, db_column="EmployeeId", related_name="attendances")
    work_date = models.DateField(db_column="WorkDate")
    scheduled_start = models.DateTimeField(db_column="ScheduledStart", null=True, blank=True)
    scheduled_end = models.DateTimeField(db_column="ScheduledEnd", null=True, blank=True)
    actual_start = models.DateTimeField(db_column="ActualStart", null=True, blank=True)
    actual_end = models.DateTimeField(db_column="ActualEnd", null=True, blank=True)
    scheduled_minutes = models.IntegerField(db_column="ScheduledMinutes", db_default=Value(0))
    worked_minutes = models.IntegerField(db_column="WorkedMinutes", db_default=Value(0))
    attendance_status = models.CharField(db_column="AttendanceStatus", max_length=20)
    source = models.ForeignKey(IngestionSource, models.DO_NOTHING, db_column="SourceId")
    batch = models.ForeignKey(IngestionBatch, models.DO_NOTHING, db_column="BatchId", null=True, blank=True)
    is_manual_adjustment = models.BooleanField(db_column="IsManualAdjustment", db_default=Value(False))
    notes = models.CharField(db_column="Notes", max_length=500, null=True, blank=True)
    row_ver = RowVersionField()

    class Meta:
        managed = False
        db_table = sql_table("wfm", "Attendance")


class AttendanceDowntime(models.Model):
    """wfm.AttendanceDowntime — DurationMinutes es columna calculada persistida en la BD."""

    attendance_downtime_id = models.BigAutoField(db_column="AttendanceDowntimeId", primary_key=True)
    attendance = models.ForeignKey(Attendance, models.DO_NOTHING, db_column="AttendanceId", related_name="downtimes")
    downtime_type = models.ForeignKey(DowntimeType, models.DO_NOTHING, db_column="DowntimeTypeId")
    start_at = models.DateTimeField(db_column="StartAt")
    end_at = models.DateTimeField(db_column="EndAt")
    duration_minutes = models.GeneratedField(
        expression=F("end_at") - F("start_at"),  # marcador; el cálculo real: DATEDIFF(MINUTE, StartAt, EndAt)
        output_field=models.IntegerField(null=True),
        db_persist=True,
        db_column="DurationMinutes",
    )
    external_code = models.CharField(db_column="ExternalCode", max_length=50, null=True, blank=True)
    batch = models.ForeignKey(IngestionBatch, models.DO_NOTHING, db_column="BatchId", null=True, blank=True)
    created_at = models.DateTimeField(db_column="CreatedAt", db_default=Now(), editable=False)

    class Meta:
        managed = False
        db_table = sql_table("wfm", "AttendanceDowntime")
