"""Fase 16 — Segmentos de actividad, validación de pago y adherencia (WFM).

    adh_activity_type        actividades PRECONFIGURADAS que WFM inserta en el turno (Producción / Calls, Break,
                             Almuerzo, Capacitación, Coaching, Back Office…): pagada, facturable (billing), color y la
                             actividad PREDETERMINADA que rellena el contenedor donde no hay segmentos (una sola)
    adh_activity_status      estados / auxiliares ACD que CUMPLEN cada actividad, con su rol: PRIMARIO (trabajo
                             principal: llamadas, chats, tickets, back office) o SECUNDARIO (auxiliar pagado según el
                             diseño del segmento, p. ej. ACW o coaching dentro de producción)
    adh_schedule_segment     segmento programado (inicio, fin, actividad) dentro del CONTENEDOR del turno: el bloque
                             entrada-salida del horario vigente que creó la AP (sch_schedule_assignment). Sin traslapes
                             por agente (50070); siempre dentro de un contenedor (lo valida el servicio)
    adh_exception            JUSTIFICACIÓN respaldada por una AP APROBADA del mismo empleado (50071): la ventana no se
                             marca como Out of Adherence ni Unpaid Excess Login; se paga si así se indica
    adh_adherence_day        resultado guardado del cálculo por agente y fecha de turno (para nómina y calidad)
    adh_deviation            desviaciones guardadas: OUT_OF_ADHERENCE y UNPAID_EXCESS_LOGIN

Las horas del plan son hora LOCAL de la operación (como los horarios y marcaciones). Las FKs a hcm.Employee
(SQL-first) se crean en la migración 0002.
"""

from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q

from apps.common.fields import sql_table
from apps.acd.models import AuxCode, PrimaryStatus
from apps.hcm.models import Employee
from apps.scheduling.fields import WallClockDateTimeField

UPPER_CODE = RegexValidator(r"^[A-Z][A-Z0-9_\-]*$", "Use MAYÚSCULAS, dígitos, guion o guion bajo; debe iniciar con letra.")
COLOR = RegexValidator(r"^#[0-9a-fA-F]{6}$", "Color hexadecimal (#RRGGBB).")


# Fase 17: iconos disponibles para los cuadros de la barra de segmentos (los dibuja el frontend).
ICONS = [
    ("headset", "Auriculares (producción)"), ("inbox", "Bandeja (back office)"), ("coffee", "Café (break)"),
    ("utensils", "Cubiertos (almuerzo)"), ("school", "Birrete (capacitación)"), ("chat", "Conversación (coaching)"),
    ("users", "Personas (reunión)"), ("clock", "Reloj (otra)"), ("star", "Estrella"), ("flag", "Bandera"),
    # Fase 19: categorías del Time Utilization (RRHH, sistemas, trabajo fuera del teléfono) y asistencia automática.
    ("heart", "Corazón (tiempo libre RRHH)"), ("laptop", "Laptop (fallas de sistema / IT)"),
    ("briefcase", "Maletín (trabajo fuera del teléfono)"), ("alarm", "Alarma (lateness)"), ("user-x", "Persona tachada (ausencia)"),
]

# Fase 19: áreas que revisan cada sub-segmento (columnas «… Reviewal» del Time Utilization Project).
REVIEW_AREAS = [
    ("ECD", "ECD"), ("WFM", "Workforce Management"), ("IT", "Information Technologies"), ("HR", "Human Resources"),
    ("FIN", "Finance"), ("OM", "Operations Management (OM y abajo)"), ("UM", "Upper Management (Directores y arriba)"),
]


class UtilizationCategory(models.Model):
    """Fase 19 — «Segmento principal» del Time Utilization Project (Departamento → Segmento principal → Sub segmento).

    Agrupa las actividades en el desplegable de la barra de segmentos: al elegir una categoría la barra muestra solo
    sus actividades.
    """

    class Department(models.TextChoices):
        WFM = "WFM", "Workforce Management"
        HR = "HR", "Human Resources"
        IT = "IT", "Information Technologies"
        TD = "TD", "Training & Development"
        OPS = "OPS", "Operations"
        SYSTEM = "SYSTEM", "Sistema (asistencia automática)"

    code = models.CharField("código", max_length=30, unique=True, validators=[UPPER_CODE])
    name = models.CharField("segmento principal", max_length=80)
    department = models.CharField("departamento", max_length=6, choices=Department, default=Department.WFM)
    description = models.CharField("descripción", max_length=300, blank=True)
    sort_order = models.PositiveSmallIntegerField("orden", default=100)
    is_active = models.BooleanField("activa", default=True)

    class Meta:
        db_table = sql_table("wfm", "adh_activity_category")
        ordering = ["sort_order", "name"]
        verbose_name = "categoría de utilización"
        verbose_name_plural = "categorías de utilización (Time Utilization)"

    def __str__(self) -> str:
        return f"{self.get_department_display()} › {self.name}"


def _employee_fk(related_name: str):
    return models.ForeignKey(
        Employee, on_delete=models.DO_NOTHING, db_column="employee_id", db_constraint=False,
        related_name=related_name, verbose_name="agente",
    )


class ActivityType(models.Model):
    class Category(models.TextChoices):
        PRODUCTION = "PRODUCTION", "Producción (calls / chats / tickets)"
        BACK_OFFICE = "BACK_OFFICE", "Back Office"
        BREAK = "BREAK", "Break programado"
        MEAL = "MEAL", "Almuerzo"
        TRAINING = "TRAINING", "Capacitación"
        COACHING = "COACHING", "Coaching"
        MEETING = "MEETING", "Reunión"
        TIME_OFF = "TIME_OFF", "Tiempo libre / permiso (RRHH)"
        SYSTEM_ISSUE = "SYSTEM_ISSUE", "Falla de sistema (IT)"
        ATTENDANCE = "ATTENDANCE", "Asistencia (lateness / ausencia)"
        OTHER = "OTHER", "Otra"

    class ClientPaid(models.TextChoices):
        NONE = "NONE", "No lo paga el cliente"
        MANDATORY = "MANDATORY", "Pagado por el cliente (obligatorio)"
        OPTIONAL = "OPTIONAL", "Pagado por el cliente (opcional)"

    class SystemRole(models.TextChoices):
        LATENESS = "LATENESS", "Lateness (llegada tarde)"
        ABSENCE = "ABSENCE", "Unjustified Absence (no-show)"
        LEGAL_LUNCH = "LEGAL_LUNCH", "Legal Benefit Lunch (día de ausencia)"

    code = models.CharField("código", max_length=30, unique=True, validators=[UPPER_CODE])
    name = models.CharField("nombre", max_length=80)
    category = models.CharField("categoría", max_length=12, choices=Category, default=Category.OTHER)
    description = models.CharField("descripción", max_length=300, blank=True)
    color = models.CharField("color", max_length=7, default="#64748b", validators=[COLOR])
    is_paid = models.BooleanField("tiempo pagado", default=True, help_text="Almuerzo: no pagado.")
    is_billable = models.BooleanField("facturable (billing)", default=False,
                                      help_text="El tiempo en adherencia se factura al cliente (producción, back office).")
    is_default = models.BooleanField(
        "actividad predeterminada del contenedor", default=False,
        help_text="Rellena el tiempo del turno que no cubre ningún segmento (normalmente Producción). Solo una.",
    )
    # Fase 18: granularidad al segundo (antes default_minutes).
    default_seconds = models.PositiveIntegerField("duración sugerida (s)", null=True, blank=True,
                                                  validators=[MinValueValidator(60), MaxValueValidator(43200)],
                                                  help_text="Segundos (60 = 1 min; máx. 12 h).")
    sort_order = models.PositiveSmallIntegerField("orden", default=100)
    # Fase 17: icono de la caja de herramientas (toolbox) y cuentas donde se ofrece.
    icon = models.CharField("icono", max_length=20, choices=ICONS, default="clock",
                            help_text="Icono del cuadro de la barra de segmentos (planificación estilo IEX).")
    clients = models.ManyToManyField(
        "operations.Client", through="ActivityClient", related_name="activity_types", blank=True,
        verbose_name="cuentas (clientes)", help_text="Vacío = disponible en todas las cuentas.",
    )
    # Fase 19: matriz del Time Utilization Project (una fila = un sub segmento).
    utilization_category = models.ForeignKey(
        UtilizationCategory, on_delete=models.PROTECT, null=True, blank=True, related_name="activities",
        verbose_name="categoría (segmento principal)", help_text="Agrupa la actividad en el desplegable de la barra de segmentos.",
    )
    requires_acd_login = models.BooleanField(
        "requiere sesión en el ACD", default=True,
        help_text="No: el tiempo se cumple sin sesión (permiso, falla de sistema, capacitación presencial, almuerzo legal).",
    )
    allows_full_day = models.BooleanField("puede cubrir el día completo", default=False)
    allows_partial = models.BooleanField("puede ser parcial (parte del turno)", default=True)
    requires_ap = models.BooleanField(
        "requiere AP aprobada", default=False,
        help_text="Respaldo legal (Ministerio de Trabajo): el segmento solo se coloca con el folio de una AP aprobada del agente.",
    )
    client_paid = models.CharField("pagado por el cliente", max_length=9, choices=ClientPaid, default=ClientPaid.NONE)
    review_areas = models.CharField("áreas que revisan", max_length=40, blank=True,
                                    help_text="Códigos separados por coma: ECD, WFM, IT, HR, FIN, OM, UM.")
    system_role = models.CharField(
        "actividad del sistema", max_length=12, choices=SystemRole, blank=True,
        help_text="La inserta el sistema (lateness / ausencia / almuerzo legal); no se coloca desde la barra.",
    )
    is_active = models.BooleanField("activa", default=True)
    created_at = models.DateTimeField("creada", auto_now_add=True)
    updated_at = models.DateTimeField("actualizada", auto_now=True)

    class Meta:
        db_table = sql_table("wfm", "adh_activity_type")
        ordering = ["sort_order", "name"]
        verbose_name = "tipo de actividad"
        verbose_name_plural = "tipos de actividad (segmentos)"
        constraints = [
            models.UniqueConstraint(fields=["is_default"], condition=Q(is_default=True), name="uq_adh_activity_default"),
            models.CheckConstraint(condition=~Q(is_default=True) | Q(is_active=True), name="ck_adh_activity_default_active"),
            models.UniqueConstraint(fields=["system_role"], condition=Q(system_role__in=["LATENESS", "ABSENCE", "LEGAL_LUNCH"]),
                                    name="uq_adh_activity_system_role"),
            models.CheckConstraint(condition=Q(allows_full_day=True) | Q(allows_partial=True), name="ck_adh_activity_duration_kind"),
            models.CheckConstraint(condition=Q(client_paid__in=["NONE", "MANDATORY", "OPTIONAL"]), name="ck_adh_activity_client_paid"),
        ]

    @property
    def review_list(self) -> list[str]:
        return [x for x in (self.review_areas or "").split(",") if x]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class ActivityClient(models.Model):
    """Cuenta (cliente) en la que se ofrece una actividad en la barra de segmentos (Fase 17)."""

    activity = models.ForeignKey(ActivityType, on_delete=models.CASCADE, related_name="client_scope", verbose_name="actividad")
    client = models.ForeignKey("operations.Client", on_delete=models.PROTECT, related_name="+", verbose_name="cliente")

    class Meta:
        db_table = sql_table("wfm", "adh_activity_client")
        verbose_name = "cuenta de la actividad"
        verbose_name_plural = "cuentas de la actividad"
        constraints = [models.UniqueConstraint(fields=["activity", "client"], name="uq_adh_activity_client")]

    def __str__(self) -> str:
        return f"{self.activity_id} → {self.client_id}"


class GridSetting(models.Model):
    """Metadatos de la grilla de planificación (Fase 17): tamaño del intervalo y del ajuste al arrastrar.

    Una fila global (group NULL) y, opcionalmente, una por Management Unit (grupo de agentes ACD) que la reemplaza.
    """

    INTERVALS = [(15, "15 min"), (30, "30 min"), (60, "60 min")]
    # Fase 18: el ajuste al soltar se guarda en SEGUNDOS (1 s = sin redondeo práctico).
    SNAPS = [(1, "1 s"), (15, "15 s"), (30, "30 s"), (60, "1 min"), (300, "5 min"), (900, "15 min"), (1800, "30 min")]

    group = models.OneToOneField("acd.AgentGroup", on_delete=models.CASCADE, null=True, blank=True, related_name="grid_setting",
                                 verbose_name="management unit", help_text="Vacío = configuración global.")
    interval_minutes = models.PositiveSmallIntegerField("intervalo de la grilla (min)", choices=INTERVALS, default=15)
    snap_seconds = models.PositiveSmallIntegerField("ajuste al soltar (s)", choices=SNAPS, default=300)
    margin_hours = models.PositiveSmallIntegerField("margen alrededor del turno (h)", default=1,
                                                    validators=[MaxValueValidator(6)])
    # Fase 19: reglas de asistencia y de respaldo por AP.
    lateness_grace_seconds = models.PositiveIntegerField(
        "tolerancia de llegada (s)", default=60, validators=[MaxValueValidator(3600)],
        help_text="Un inicio de sesión ACD posterior a la entrada + tolerancia inserta el segmento Lateness.",
    )
    ap_required_seconds = models.PositiveIntegerField(
        "duración que exige AP (s)", default=4 * 3600, validators=[MaxValueValidator(86400)],
        help_text="Cambio mayor: un segmento de esta duración o más exige AP aprobada (0 = solo el día completo y las "
                  "actividades marcadas «requiere AP»).",
    )
    updated_at = models.DateTimeField("actualizada", auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+", verbose_name="actualizada por")

    class Meta:
        db_table = sql_table("wfm", "adh_grid_setting")
        verbose_name = "configuración de la grilla"
        verbose_name_plural = "configuración de la grilla (planificación)"
        constraints = [
            models.UniqueConstraint(fields=["group"], condition=Q(group__isnull=True), name="uq_adh_grid_global"),
            models.CheckConstraint(condition=Q(interval_minutes__in=[15, 30, 60]), name="ck_adh_grid_interval"),
            models.CheckConstraint(condition=Q(snap_seconds__in=[1, 15, 30, 60, 300, 900, 1800]), name="ck_adh_grid_snap_seconds"),
            models.CheckConstraint(condition=Q(margin_hours__lte=6), name="ck_adh_grid_margin"),
            models.CheckConstraint(condition=Q(lateness_grace_seconds__lte=3600), name="ck_adh_grid_grace"),
            models.CheckConstraint(condition=Q(ap_required_seconds__lte=86400), name="ck_adh_grid_ap_seconds"),
        ]

    def __str__(self) -> str:
        return f"{self.group_id or 'global'}: {self.interval_minutes} min / {self.snap_seconds} s"


class ActivityStatusRule(models.Model):
    class Role(models.TextChoices):
        PRIMARY = "PRIMARY", "Auxiliar primario (trabajo principal)"
        SECONDARY = "SECONDARY", "Auxiliar secundario pagado (según diseño del segmento)"

    activity = models.ForeignKey(ActivityType, on_delete=models.CASCADE, related_name="status_rules", verbose_name="actividad")
    primary_status = models.ForeignKey(PrimaryStatus, on_delete=models.PROTECT, related_name="+", verbose_name="estado primario")
    aux_code = models.ForeignKey(AuxCode, on_delete=models.PROTECT, null=True, blank=True, related_name="+", verbose_name="auxiliar",
                                 help_text="Vacío = cualquier auxiliar del estado (o sin auxiliar). Un auxiliar padre incluye sus sub-auxiliares.")
    role = models.CharField("rol", max_length=9, choices=Role, default=Role.PRIMARY)

    class Meta:
        db_table = sql_table("wfm", "adh_activity_status")
        ordering = ["activity_id", "role", "primary_status__sort_order"]
        verbose_name = "estado que cumple la actividad"
        verbose_name_plural = "estados que cumplen la actividad"
        constraints = [
            models.UniqueConstraint(fields=["activity", "primary_status", "aux_code"], name="uq_adh_activity_status"),
            models.CheckConstraint(condition=Q(role__in=["PRIMARY", "SECONDARY"]), name="ck_adh_activity_status_role"),
        ]

    def __str__(self) -> str:
        aux = f" · {self.aux_code.full_name}" if self.aux_code_id else ""
        return f"{self.activity.code}: {self.primary_status.label}{aux} ({self.get_role_display()})"


class ScheduleSegment(models.Model):
    class Origin(models.TextChoices):
        WFM = "WFM", "Programado por WFM"
        SYSTEM = "SYSTEM", "Automático (sistema)"
        REQUEST = "REQUEST", "Solicitud aprobada (cola WFM)"

    employee = _employee_fk("activity_segments")
    shift_date = models.DateField("fecha del turno")
    assignment = models.ForeignKey(
        "scheduling.ScheduleAssignment", on_delete=models.SET_NULL, null=True, blank=True, related_name="activity_segments",
        verbose_name="horario (contenedor)", help_text="Horario vigente (de la AP) cuyo bloque contiene al segmento.",
    )
    activity = models.ForeignKey(ActivityType, on_delete=models.PROTECT, related_name="segments", verbose_name="actividad")
    start_at = WallClockDateTimeField("inicio (hora local)")
    end_at = WallClockDateTimeField("fin (hora local)")
    notes = models.CharField("notas", max_length=200, blank=True)
    # Fase 19: de dónde viene el segmento, su respaldo (AP) y si está bloqueado (Lateness / ausencia: solo se reemplaza).
    origin = models.CharField("origen", max_length=7, choices=Origin, default=Origin.WFM)
    personnel_action = models.ForeignKey(
        "personnel_actions.PersonnelAction", on_delete=models.PROTECT, null=True, blank=True, related_name="activity_segments",
        verbose_name="AP de respaldo", help_text="AP aprobada del mismo empleado (obligatoria si la actividad o el cambio la exigen).",
    )
    is_locked = models.BooleanField(
        "bloqueado", default=False,
        help_text="Lateness / Unjustified Absence: no se elimina ni se mueve; solo se reemplaza con un segmento respaldado por AP.",
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+", verbose_name="programado por")
    created_at = models.DateTimeField("programado", auto_now_add=True)
    updated_at = models.DateTimeField("actualizado", auto_now=True)

    class Meta:
        db_table = sql_table("wfm", "adh_schedule_segment")
        ordering = ["employee_id", "start_at"]
        verbose_name = "segmento de actividad"
        verbose_name_plural = "segmentos de actividad"
        indexes = [
            models.Index(fields=["employee", "shift_date"], name="ix_adh_segment_emp_date"),
            models.Index(fields=["shift_date"], name="ix_adh_segment_date"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(end_at__gt=models.F("start_at")), name="ck_adh_segment_dates"),
            models.CheckConstraint(condition=Q(origin__in=["WFM", "SYSTEM", "REQUEST"]), name="ck_adh_segment_origin"),
            models.CheckConstraint(condition=Q(is_locked=False) | Q(origin="SYSTEM"), name="ck_adh_segment_locked_system"),
        ]

    def __str__(self) -> str:
        return f"{self.employee_id} {self.start_at:%Y-%m-%d %H:%M:%S}–{self.end_at:%H:%M:%S} {self.activity_id}"

    @property
    def seconds(self) -> int:
        """Duración exacta al segundo (Fase 18)."""
        return int((self.end_at - self.start_at).total_seconds())

    @property
    def minutes(self) -> float:
        """Minutos con decimales (sin redondear): 90 s = 1.5."""
        return round(self.seconds / 60, 4)


class AdherenceException(models.Model):
    employee = _employee_fk("adherence_exceptions")
    personnel_action = models.ForeignKey("personnel_actions.PersonnelAction", on_delete=models.PROTECT, related_name="adherence_exceptions",
                                         verbose_name="acción de personal", help_text="AP aprobada del mismo empleado que justifica la ventana.")
    start_at = WallClockDateTimeField("desde (hora local)")
    end_at = WallClockDateTimeField("hasta (hora local)")
    is_paid = models.BooleanField("tiempo pagado", default=True)
    reason = models.CharField("motivo", max_length=200)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+", verbose_name="registrado por")
    created_at = models.DateTimeField("registrado", auto_now_add=True)

    class Meta:
        db_table = sql_table("wfm", "adh_exception")
        ordering = ["employee_id", "start_at"]
        verbose_name = "justificación por AP"
        verbose_name_plural = "justificaciones por AP"
        indexes = [models.Index(fields=["employee", "start_at"], name="ix_adh_exception_emp_start")]
        constraints = [
            models.CheckConstraint(condition=Q(end_at__gt=models.F("start_at")), name="ck_adh_exception_dates"),
        ]

    def __str__(self) -> str:
        return f"{self.employee_id} {self.start_at:%Y-%m-%d %H:%M}–{self.end_at:%Y-%m-%d %H:%M}"


class AdherenceDay(models.Model):
    """Totales (segundos) del cálculo guardado de un agente en una fecha de turno."""

    employee = _employee_fk("adherence_days")
    shift_date = models.DateField("fecha del turno")
    scheduled_seconds = models.IntegerField("programado", default=0)
    scheduled_paid_seconds = models.IntegerField("programado pagado", default=0)
    in_adherence_seconds = models.IntegerField("en adherencia", default=0)
    out_of_adherence_seconds = models.IntegerField("out of adherence", default=0)
    justified_seconds = models.IntegerField("justificado por AP", default=0)
    logged_seconds = models.IntegerField("con sesión", default=0)
    logged_in_container_seconds = models.IntegerField("con sesión dentro del contenedor", default=0)
    paid_valid_seconds = models.IntegerField("válido para pago", default=0)
    billable_seconds = models.IntegerField("facturable", default=0)
    primary_work_seconds = models.IntegerField("trabajo principal (auxiliar primario)", default=0)
    secondary_paid_seconds = models.IntegerField("auxiliares secundarios pagados", default=0)
    unpaid_excess_seconds = models.IntegerField("unpaid excess login", default=0)
    adherence_pct = models.DecimalField("adherencia (%)", max_digits=6, decimal_places=2, null=True, blank=True)
    conformance_pct = models.DecimalField("conformidad (%)", max_digits=6, decimal_places=2, null=True, blank=True)
    computed_at = models.DateTimeField("calculado")
    computed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+", verbose_name="calculado por")

    class Meta:
        db_table = sql_table("wfm", "adh_adherence_day")
        ordering = ["shift_date", "employee_id"]
        verbose_name = "adherencia diaria (guardada)"
        verbose_name_plural = "adherencia diaria (guardada)"
        constraints = [
            models.UniqueConstraint(fields=["employee", "shift_date"], name="uq_adh_day_emp_date"),
            models.CheckConstraint(condition=Q(scheduled_seconds__gte=0, unpaid_excess_seconds__gte=0), name="ck_adh_day_seconds"),
        ]

    def __str__(self) -> str:
        return f"{self.employee_id} {self.shift_date} {self.adherence_pct}%"


class Deviation(models.Model):
    class Kind(models.TextChoices):
        OUT_OF_ADHERENCE = "OUT_OF_ADHERENCE", "Out of Adherence"
        UNPAID_EXCESS_LOGIN = "UNPAID_EXCESS_LOGIN", "Unpaid Excess Login"

    id = models.BigAutoField(primary_key=True)
    day = models.ForeignKey(AdherenceDay, on_delete=models.CASCADE, related_name="deviations", verbose_name="día")
    employee = _employee_fk("+")
    shift_date = models.DateField("fecha")
    kind = models.CharField("tipo", max_length=20, choices=Kind)
    start_at = WallClockDateTimeField("desde (hora local)")
    end_at = WallClockDateTimeField("hasta (hora local)")
    seconds = models.IntegerField("duración (s)")
    expected_activity = models.ForeignKey(ActivityType, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                          verbose_name="actividad programada")
    actual_status = models.ForeignKey(PrimaryStatus, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                      verbose_name="estado real")
    actual_aux = models.ForeignKey(AuxCode, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                   verbose_name="auxiliar real")

    class Meta:
        db_table = sql_table("wfm", "adh_deviation")
        ordering = ["employee_id", "start_at"]
        verbose_name = "desviación"
        verbose_name_plural = "desviaciones (Out of Adherence / Unpaid Excess Login)"
        indexes = [models.Index(fields=["employee", "shift_date"], name="ix_adh_deviation_emp_date")]
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=["OUT_OF_ADHERENCE", "UNPAID_EXCESS_LOGIN"]), name="ck_adh_deviation_kind"),
            models.CheckConstraint(condition=Q(end_at__gt=models.F("start_at")), name="ck_adh_deviation_dates"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.employee_id} {self.start_at:%Y-%m-%d %H:%M}"


class ChangeRequest(models.Model):
    """Fase 19 — Cola de aprobación de WFM: correcciones de segmentos solicitadas por el agente, su supervisor (cadena
    de mando del roster) o un usuario WFM de solo lectura. WFM aprueba (se aplica al plan) o rechaza. Los cambios del
    DÍA COMPLETO no pasan por la cola: exigen el flujo de AP."""

    class Kind(models.TextChoices):
        ADD = "ADD", "Agregar segmento"
        CHANGE = "CHANGE", "Cambiar segmento"
        DELETE = "DELETE", "Quitar segmento"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        APPROVED = "APPROVED", "Aprobada y aplicada"
        REJECTED = "REJECTED", "Rechazada"
        CANCELLED = "CANCELLED", "Anulada por quien la pidió"

    class Requester(models.TextChoices):
        AGENT = "AGENT", "Agente"
        SUPERVISOR = "SUPERVISOR", "Supervisor (cadena de mando)"
        WFM = "WFM", "Workforce"

    id = models.BigAutoField(primary_key=True)
    employee = _employee_fk("adherence_change_requests")
    shift_date = models.DateField("fecha del turno")
    kind = models.CharField("tipo", max_length=6, choices=Kind)
    segment = models.ForeignKey(ScheduleSegment, on_delete=models.SET_NULL, null=True, blank=True, related_name="change_requests",
                                verbose_name="segmento", help_text="Segmento a cambiar o quitar.")
    activity = models.ForeignKey(ActivityType, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                 verbose_name="actividad propuesta")
    start_at = WallClockDateTimeField("inicio propuesto (hora local)", null=True, blank=True)
    end_at = WallClockDateTimeField("fin propuesto (hora local)", null=True, blank=True)
    personnel_action = models.ForeignKey("personnel_actions.PersonnelAction", on_delete=models.PROTECT, null=True, blank=True,
                                         related_name="+", verbose_name="AP de respaldo")
    notes = models.CharField("notas del segmento", max_length=200, blank=True)
    reason = models.CharField("motivo / observaciones", max_length=500)
    before = models.JSONField("segmento antes", null=True, blank=True)
    status = models.CharField("estado", max_length=9, choices=Status, default=Status.PENDING)
    requester_role = models.CharField("solicitado como", max_length=10, choices=Requester)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+",
                                     verbose_name="solicitado por")
    requested_at = models.DateTimeField("solicitado", auto_now_add=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                                   verbose_name="resuelto por")
    decided_at = models.DateTimeField("resuelto", null=True, blank=True)
    decision_comment = models.CharField("comentario de WFM", max_length=500, blank=True)
    applied_segment_id = models.BigIntegerField("segmento resultante", null=True, blank=True)

    class Meta:
        db_table = sql_table("wfm", "adh_change_request")
        ordering = ["-requested_at", "-id"]
        verbose_name = "solicitud de corrección (cola WFM)"
        verbose_name_plural = "cola de aprobación de WFM (correcciones de segmentos)"
        indexes = [
            models.Index(fields=["status", "shift_date"], name="ix_adh_request_status"),
            models.Index(fields=["employee", "shift_date"], name="ix_adh_request_emp_date"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=["ADD", "CHANGE", "DELETE"]), name="ck_adh_request_kind"),
            models.CheckConstraint(condition=Q(status__in=["PENDING", "APPROVED", "REJECTED", "CANCELLED"]), name="ck_adh_request_status"),
            models.CheckConstraint(condition=Q(kind="DELETE") | Q(activity__isnull=False, start_at__isnull=False, end_at__isnull=False),
                                   name="ck_adh_request_proposal"),
            models.CheckConstraint(condition=Q(end_at__isnull=True) | Q(end_at__gt=models.F("start_at")), name="ck_adh_request_dates"),
        ]

    def __str__(self) -> str:
        return f"#{self.pk} {self.kind} {self.employee_id} {self.shift_date} ({self.status})"
