"""Acciones de Personal (AP): eventos operativos con folio, fecha efectiva, firmas y datos EAV.

    pa_action_type        tipo de AP parametrizable: categoría, EFECTO al aprobarse (asignar horario, ajustar
                          salario o solo registro), prefijo del folio, permisos para verla / crearla, AP fundacional
    pa_action_attribute   campos EAV del tipo (texto, número, fecha, lista, horario semanal…), con reglas
    pa_approval_step      cadena de firmas del tipo: orden + rol que firma (jerarquía por roles)
    pa_action             la AP: folio único, empleado, fecha efectiva, justificación, estado de aprobación
    pa_action_value       valores EAV de la AP (una fila por campo, columna según el tipo de dato)
    pa_action_signature   firma digital de cada paso: quién, con qué rol, decisión, fecha y HMAC-SHA256 sobre
                          el contenido sellado de la AP (si el contenido cambia, la firma deja de verificar)
    pa_folio_sequence     correlativo de folios por prefijo y año

En SQL Server (migración 0002): FK a hcm.Employee, firmas inmutables (50050) y valores congelados cuando la AP
deja de ser borrador (50051); vista dbo.vw_PersonnelAction.
"""

from __future__ import annotations

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q

from apps.accounts.roles import Role
from apps.hcm.models import Employee

UPPER_CODE = RegexValidator(r"^[A-Z][A-Z0-9_]*$", "Use MAYÚSCULAS, dígitos y guion bajo; debe iniciar con letra.")
LOWER_KEY = RegexValidator(r"^[a-z][a-z0-9_]*$", "Use minúsculas, dígitos y guion bajo; debe iniciar con letra.")
PERMISSION_CHOICES = [
    ("actions.view", "Acciones de personal: ver"),
    ("actions.create", "Acciones de personal: crear"),
    ("hcm.view", "Empleados: ver"),
    ("hcm.manage", "Empleados: administrar"),
    ("payroll.view", "Planillas: ver (datos salariales)"),
    ("payroll.manage", "Planillas: administrar"),
    ("schedules.view", "Horarios: ver"),
    ("schedules.manage", "Horarios: administrar"),
]


class Category(models.TextChoices):
    SCHEDULE = "SCHEDULE", "Horario"
    COMPENSATION = "COMPENSATION", "Compensación"
    POSITION = "POSITION", "Puesto / ubicación"
    STATUS = "STATUS", "Estado laboral"
    OTHER = "OTHER", "Otra"


class Effect(models.TextChoices):
    NONE = "NONE", "Solo registro (sin efecto automático)"
    SCHEDULE = "SCHEDULE", "Asigna el horario desde la fecha efectiva"
    SALARY = "SALARY", "Actualiza el salario base en la fecha efectiva"
    PAYROLL = "PAYROLL", "Concepto de planilla (se paga o descuenta en la planilla del periodo)"
    # Fase 21: ciclo de vida del colaborador
    SUSPENSION = "SUSPENSION", "Suspensión disciplinaria (inactivo por N días; congela la antigüedad)"
    TERMINATION = "TERMINATION", "Terminación / renuncia (estado Terminado; indicador de recontratación)"
    REHIRE = "REHIRE", "Reingreso (reactiva al colaborador; la antigüedad corre desde la nueva fecha)"
    # Fase 22: justificaciones y permisos dentro del módulo regular de AP; roster automático
    JUSTIFY = "JUSTIFY", "Justificación de tiempo (segmento en la grilla + justificación de adherencia)"
    LEAVE = "LEAVE", "Permiso con / sin goce (justifica el día laborable completo o por horas)"
    ROSTER = "ROSTER", "Actualiza el roster y el expediente (promoción, cambio organizacional)"


class ScheduleMode(models.TextChoices):
    PRIMARY = "PRIMARY", "Reemplaza el horario principal"
    ADDITIONAL = "ADDITIONAL", "Asignación adicional (turno partido / doble, con fecha de fin)"


class ActionType(models.Model):
    code = models.CharField("código", max_length=40, unique=True, validators=[UPPER_CODE])
    name = models.CharField("nombre", max_length=150)
    description = models.CharField("descripción", max_length=500, blank=True)
    category = models.CharField("categoría", max_length=12, choices=Category, default=Category.OTHER)
    effect = models.CharField("efecto al aprobarse", max_length=12, choices=Effect, default=Effect.NONE)
    folio_prefix = models.CharField("prefijo del folio", max_length=6, validators=[RegexValidator(r"^[A-Z]{2,6}$", "2 a 6 letras MAYÚSCULAS.")])
    is_initial_schedule = models.BooleanField(
        "AP fundacional de horario", default=False,
        help_text="Es la «Primera AP de asignación de horario» que se crea en el alta de cada empleado (solo un tipo).",
    )
    schedule_mode = models.CharField(
        "asignación de horario", max_length=10, choices=ScheduleMode, default=ScheduleMode.PRIMARY,
        help_text="Solo para tipos que asignan horario. «Adicional» convive con el horario principal (varias AP el mismo "
                  "día) y necesita el campo de fecha «vigente_hasta».",
    )
    view_permission = models.CharField("permiso para verla", max_length=30, choices=PERMISSION_CHOICES, default="actions.view")
    create_permission = models.CharField("permiso para crearla", max_length=30, choices=PERMISSION_CHOICES, default="actions.create")
    creator_signs_first_step = models.BooleanField(
        "quien la envía firma el primer paso", default=False,
        help_text="Si el rol de quien envía la AP corresponde al primer paso, su envío cuenta como esa firma.",
    )
    require_distinct_signers = models.BooleanField(
        "firmantes distintos", default=False,
        help_text="Cada paso debe firmarlo una persona distinta (segregación de funciones).",
    )
    # Fase 21: control estricto por rol (Generalista de RRHH, WFM, Administrador).
    creator_roles = models.JSONField(
        "roles que la crean", default=list, blank=True,
        help_text='Lista de roles que pueden elaborar este tipo (p. ej. ["HR", "ADMIN"]). Vacía = cualquier rol con el permiso.',
    )
    admin_signs_any_step = models.BooleanField(
        "el Administrador firma cualquier paso", default=True,
        help_text="Si se desmarca, cada paso lo firma ÚNICAMENTE el rol indicado en la cadena.",
    )
    display_order = models.PositiveSmallIntegerField("orden", default=100)
    is_active = models.BooleanField("activo", default=True)
    created_at = models.DateTimeField("creado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        db_table = "pa_action_type"
        ordering = ["display_order", "name"]
        verbose_name = "tipo de acción de personal"
        verbose_name_plural = "tipos de acción de personal"
        constraints = [
            models.UniqueConstraint(fields=["is_initial_schedule"], condition=Q(is_initial_schedule=True), name="uq_pa_type_initial"),
            models.CheckConstraint(condition=~Q(is_initial_schedule=True) | Q(effect="SCHEDULE"), name="ck_pa_type_initial_effect"),
            models.CheckConstraint(condition=~Q(is_initial_schedule=True) | Q(schedule_mode="PRIMARY"), name="ck_pa_type_initial_mode"),
            models.CheckConstraint(condition=Q(schedule_mode__in=["PRIMARY", "ADDITIONAL"]), name="ck_pa_type_schedule_mode"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class DataType(models.TextChoices):
    TEXT = "TEXT", "Texto corto"
    LONG_TEXT = "LONG_TEXT", "Texto largo"
    INTEGER = "INTEGER", "Número entero"
    DECIMAL = "DECIMAL", "Número decimal / monto"
    DATE = "DATE", "Fecha"
    BOOLEAN = "BOOLEAN", "Sí / No"
    CHOICE = "CHOICE", "Lista de opciones"
    SCHEDULE = "SCHEDULE", "Horario semanal (por día)"
    # Fase 22
    TIME = "TIME", "Hora (HH:MM[:SS])"
    ACTIVITY = "ACTIVITY", "Actividad de la grilla (segmento)"
    ROSTER = "ROSTER", "Dato del roster / expediente (la clave es el código del atributo)"


class ActionAttribute(models.Model):
    action_type = models.ForeignKey(ActionType, on_delete=models.CASCADE, related_name="attributes", verbose_name="tipo")
    key = models.CharField("clave", max_length=40, validators=[LOWER_KEY])
    label = models.CharField("etiqueta", max_length=150)
    data_type = models.CharField("tipo de dato", max_length=10, choices=DataType)
    required = models.BooleanField("obligatorio", default=False)
    choices = models.JSONField("opciones", default=list, blank=True, help_text='Para listas: ["Mérito", "Promoción"] o [{"value": "M", "label": "Mérito"}].')
    help_text = models.CharField("ayuda", max_length=300, blank=True)
    min_value = models.DecimalField("mínimo", max_digits=18, decimal_places=4, null=True, blank=True)
    max_value = models.DecimalField("máximo", max_digits=18, decimal_places=4, null=True, blank=True)
    max_length = models.PositiveIntegerField("longitud máxima", null=True, blank=True)
    display_order = models.PositiveSmallIntegerField("orden", default=100)
    is_active = models.BooleanField("activo", default=True)

    class Meta:
        db_table = "pa_action_attribute"
        ordering = ["action_type_id", "display_order", "id"]
        verbose_name = "campo de la AP"
        verbose_name_plural = "campos de la AP (EAV)"
        constraints = [models.UniqueConstraint(fields=["action_type", "key"], name="uq_pa_attribute_key")]

    def __str__(self) -> str:
        return f"{self.label} ({self.key})"

    def option_list(self) -> list[dict]:
        out = []
        for item in self.choices or []:
            if isinstance(item, dict):
                out.append({"value": str(item.get("value")), "label": str(item.get("label") or item.get("value"))})
            else:
                out.append({"value": str(item), "label": str(item)})
        return out


class ApprovalStep(models.Model):
    action_type = models.ForeignKey(ActionType, on_delete=models.CASCADE, related_name="steps", verbose_name="tipo")
    order = models.PositiveSmallIntegerField("orden")
    label = models.CharField("nombre del paso", max_length=100, help_text="Ej.: Visto bueno WFM, Autorización RRHH, Gerencia.")
    role = models.CharField("rol que firma", max_length=10, choices=Role)

    class Meta:
        db_table = "pa_approval_step"
        ordering = ["action_type_id", "order"]
        verbose_name = "paso de aprobación"
        verbose_name_plural = "cadena de aprobación (firmas)"
        constraints = [models.UniqueConstraint(fields=["action_type", "order"], name="uq_pa_step_order")]

    def __str__(self) -> str:
        return f"{self.order}. {self.label} ({self.get_role_display()})"


class Status(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    PENDING = "PENDING", "En aprobación"
    APPROVED = "APPROVED", "Aprobada"
    REJECTED = "REJECTED", "Rechazada"
    CANCELLED = "CANCELLED", "Anulada"


OPEN_STATUSES = [Status.DRAFT, Status.PENDING, Status.APPROVED]


class PersonnelAction(models.Model):
    Status = Status

    folio = models.CharField("folio", max_length=30, unique=True)
    action_type = models.ForeignKey(ActionType, on_delete=models.PROTECT, related_name="actions", verbose_name="tipo")
    employee = models.ForeignKey(Employee, on_delete=models.DO_NOTHING, db_column="employee_id", db_constraint=False,
                                 related_name="personnel_actions", verbose_name="empleado")
    effective_date = models.DateField("fecha efectiva")
    justification = models.TextField("observaciones / justificación", max_length=2000)
    status = models.CharField("estado", max_length=9, choices=Status, default=Status.DRAFT)
    is_initial = models.BooleanField("AP fundacional", default=False)
    content_hash = models.CharField("sello del contenido (SHA-256)", max_length=64, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="elaborada por")
    created_at = models.DateTimeField("elaborada", auto_now_add=True)
    updated_at = models.DateTimeField("actualizada", auto_now=True)
    submitted_at = models.DateTimeField("enviada", null=True, blank=True)
    decided_at = models.DateTimeField("resuelta", null=True, blank=True)
    applied_at = models.DateTimeField("aplicada", null=True, blank=True, help_text="Cuándo se ejecutó su efecto (horario / salario).")
    cancel_reason = models.CharField("motivo de anulación", max_length=500, blank=True)

    class Meta:
        db_table = "pa_action"
        ordering = ["-created_at", "-id"]
        verbose_name = "acción de personal"
        verbose_name_plural = "acciones de personal"
        indexes = [
            models.Index(fields=["employee", "effective_date"], name="ix_pa_action_emp_date"),
            models.Index(fields=["status", "action_type"], name="ix_pa_action_status"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=Status.values), name="ck_pa_action_status"),
            # Una sola AP fundacional viva por empleado (las rechazadas o anuladas no cuentan).
            models.UniqueConstraint(fields=["employee"], condition=Q(is_initial=True, status__in=["DRAFT", "PENDING", "APPROVED"]),
                                    name="uq_pa_action_initial"),
        ]

    def __str__(self) -> str:
        return self.folio


class ActionValue(models.Model):
    action = models.ForeignKey(PersonnelAction, on_delete=models.CASCADE, related_name="values", verbose_name="AP")
    attribute = models.ForeignKey(ActionAttribute, on_delete=models.PROTECT, related_name="+", verbose_name="campo")
    value_text = models.TextField("texto", null=True, blank=True)
    value_decimal = models.DecimalField("número", max_digits=18, decimal_places=4, null=True, blank=True)
    value_date = models.DateField("fecha", null=True, blank=True)
    value_bool = models.BooleanField("sí/no", null=True, blank=True)
    value_json = models.JSONField("JSON", null=True, blank=True)

    class Meta:
        db_table = "pa_action_value"
        verbose_name = "valor de la AP"
        verbose_name_plural = "valores de la AP"
        constraints = [models.UniqueConstraint(fields=["action", "attribute"], name="uq_pa_value_attribute")]

    @property
    def value(self):
        t = self.attribute.data_type
        if t in (DataType.INTEGER, DataType.DECIMAL):
            return self.value_decimal
        if t == DataType.DATE:
            return self.value_date
        if t == DataType.BOOLEAN:
            return self.value_bool
        if t == DataType.SCHEDULE:
            return self.value_json
        return self.value_text


class Decision(models.TextChoices):
    APPROVED = "APPROVED", "Aprobó"
    REJECTED = "REJECTED", "Rechazó"


class ActionSignature(models.Model):
    action = models.ForeignKey(PersonnelAction, on_delete=models.CASCADE, related_name="signatures", verbose_name="AP")
    step_order = models.PositiveSmallIntegerField("paso")
    step_label = models.CharField("nombre del paso", max_length=100)
    required_role = models.CharField("rol requerido", max_length=10, choices=Role)
    signer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="firmante")
    signer_username = models.CharField("usuario", max_length=150)
    signer_name = models.CharField("nombre", max_length=200, blank=True)
    signer_role = models.CharField("rol del firmante", max_length=10, choices=Role)
    decision = models.CharField("decisión", max_length=8, choices=Decision)
    comment = models.CharField("comentario", max_length=500, blank=True)
    signed_at = models.DateTimeField("fecha y hora")
    content_hash = models.CharField("contenido firmado (SHA-256)", max_length=64)
    signature = models.CharField("firma (HMAC-SHA256)", max_length=64)

    class Meta:
        db_table = "pa_action_signature"
        ordering = ["action_id", "step_order"]
        verbose_name = "firma de la AP"
        verbose_name_plural = "firmas de la AP"
        constraints = [
            models.UniqueConstraint(fields=["action", "step_order"], name="uq_pa_signature_step"),
            models.CheckConstraint(condition=Q(decision__in=Decision.values), name="ck_pa_signature_decision"),
        ]


class FolioSequence(models.Model):
    prefix = models.CharField(max_length=6)
    year = models.PositiveSmallIntegerField()
    last_value = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "pa_folio_sequence"
        constraints = [models.UniqueConstraint(fields=["prefix", "year"], name="uq_pa_folio_sequence")]


# ============================================================== Fase 21: ciclo de vida del colaborador
class TerminationReason(models.TextChoices):
    RESIGNATION = "RENUNCIA", "Renuncia voluntaria"
    DISMISSAL_NO_CAUSE = "DESPIDO_SIN_CAUSA", "Despido sin causa justificada"
    DISMISSAL_CAUSE = "DESPIDO_CON_CAUSA", "Despido con causa justificada"
    END_OF_CONTRACT = "FIN_CONTRATO", "Fin de contrato a plazo"
    MUTUAL = "MUTUO_ACUERDO", "Mutuo acuerdo"
    ABANDONMENT = "ABANDONO", "Abandono de labores"


class EmploymentEvent(models.Model):
    """Historial laboral: ingreso, suspensiones, terminaciones y reingresos. La antigüedad (tenure) se calcula desde la
    fecha de ingreso VIGENTE (el reingreso la reinicia) menos los días suspendidos (la suspensión la congela)."""

    class Kind(models.TextChoices):
        HIRE = "HIRE", "Ingreso"
        SUSPENSION = "SUSPENSION", "Suspensión disciplinaria"
        TERMINATION = "TERMINATION", "Terminación"
        REHIRE = "REHIRE", "Reingreso"

    employee = models.ForeignKey(Employee, on_delete=models.DO_NOTHING, db_column="employee_id", db_constraint=False,
                                 related_name="employment_events", verbose_name="empleado")
    kind = models.CharField("evento", max_length=12, choices=Kind)
    start_date = models.DateField("desde")
    end_date = models.DateField("hasta", null=True, blank=True, help_text="Último día de la suspensión.")
    action = models.ForeignKey(PersonnelAction, on_delete=models.PROTECT, null=True, blank=True, related_name="employment_events",
                               verbose_name="AP")
    termination_reason = models.CharField("motivo de terminación", max_length=20, choices=TerminationReason, blank=True)
    rehire_eligible = models.BooleanField("recomendable para recontratación", null=True, blank=True)
    hr_notes = models.TextField("observaciones internas de RRHH", max_length=2000, blank=True)
    previous_hire_date = models.DateField("ingreso anterior", null=True, blank=True)
    previous_termination_date = models.DateField("terminación anterior", null=True, blank=True)
    rehire_acknowledged = models.BooleanField("alerta de recontratación reconocida", default=False)
    reactivated_at = models.DateTimeField("reactivado al terminar la suspensión", null=True, blank=True)
    created_at = models.DateTimeField("registrado", auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        db_table = "pa_employment_event"
        ordering = ["employee_id", "start_date", "id"]
        verbose_name = "evento laboral"
        verbose_name_plural = "historial laboral"
        indexes = [models.Index(fields=["employee", "kind", "start_date"], name="ix_pa_emp_event")]
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=["HIRE", "SUSPENSION", "TERMINATION", "REHIRE"]), name="ck_pa_emp_event_kind"),
            models.CheckConstraint(condition=Q(end_date__isnull=True) | Q(end_date__gte=models.F("start_date")), name="ck_pa_emp_event_dates"),
            models.CheckConstraint(condition=~Q(kind="SUSPENSION") | Q(end_date__isnull=False), name="ck_pa_emp_event_susp_end"),
            models.CheckConstraint(condition=~Q(kind="TERMINATION") | Q(rehire_eligible__isnull=False), name="ck_pa_emp_event_rehire"),
            models.UniqueConstraint(fields=["action"], condition=Q(action__isnull=False), name="uq_pa_emp_event_action"),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.start_date}"
