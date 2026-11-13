"""Fase 19: catálogo del Time Utilization Project, actividades del sistema e integridad en SQL Server.

* Categorías (segmento principal) y sub segmentos tomados de «Time Utilization Project - Kevin Duran.xlsx»
  (Departamento → Segmento principal → Sub segmento). La matriz de banderas del archivo venía vacía: los valores
  (requiere sesión ACD, día completo / parcial, requiere AP, pagado, facturable, áreas que revisan) son los iniciales
  por categoría y se ajustan en WFM › Actividades.
* Actividades del sistema: Lateness, Unjustified Absence y Legal Benefit Lunch (solo las inserta el sistema).
* TR_adh_schedule_segment_rules agrega 50072 (la actividad exige AP aprobada del mismo empleado) y 50074 (las
  actividades del sistema solo las inserta el sistema); TR_adh_schedule_segment_locked (50073): un segmento
  bloqueado (Lateness / ausencia) no se elimina ni se mueve, salvo el reemplazo documentado que hace el servicio
  (SESSION_CONTEXT N'adh.replace_locked' = 1).
* vw_AdhScheduleSegment agrega origen, bloqueo, AP de respaldo y categoría; vw_AdhChangeRequest = cola de WFM.
"""

import re
from importlib import import_module

from django.db import migrations

_m2 = import_module("apps.adherence.migrations.0002_sql_integrity_views_and_seed")
_m6 = import_module("apps.adherence.migrations.0006_seconds_granularity")

CATEGORIES = [
    # code, segmento principal, departamento, orden
    ("WFM_REGULAR", "Billable - Regular Segments", "WFM", 10),
    ("WFM_OUT_OF_PHONE", "Billable - Out of the Phone Work", "WFM", 20),
    ("WFM_UNLOGGED", "Billable - Worked Time Unlogged", "WFM", 30),
    ("TD_TRAINING", "Training", "TD", 40),
    ("IT_SYSTEM_ISSUES", "System Issues", "IT", 50),
    ("HR_PAID", "HR Confidential Paid", "HR", 60),
    ("HR_UNPAID", "HR Confidential Unpaid", "HR", 70),
    ("ATTENDANCE", "Asistencia automática (Lateness / Absence)", "SYSTEM", 90),
]

DEPARTMENTS = {"WFM": "Workforce Management", "HR": "Human Resources", "IT": "Information Technologies",
               "TD": "Training & Development", "SYSTEM": "Sistema"}

# Actividades existentes (Fase 16) → categoría.
EXISTING = {"PRODUCTION": "WFM_REGULAR", "BACK_OFFICE": "WFM_REGULAR", "BREAK": "WFM_REGULAR", "MEAL": "WFM_REGULAR",
            "COACHING": "WFM_REGULAR", "MEETING": "WFM_REGULAR", "TRAINING": "TD_TRAINING"}

_LEAVES = ["1:1 With HR", "Active Pause", "Bereavement", "Breastfeeding Time", "By Law Vacation", "Client Recognition Time",
           "Jury Duty", "Leave of Absence", "Local Election Day", "Mandatory Time Off", "Maternity", "National Election Day",
           "Paternity", "Scheduled Medical Appointment", "Skycom Recognition Time", "Transfer Undefined", "Voluntary Time Off",
           "Wedding"]
HR_PAID = sorted(_LEAVES + ["ADA Paid", "Company Holiday Paid", "FMLA Paid", "Paid Sick Time"])
HR_UNPAID = sorted(_LEAVES + ["ADA Unpaid", "Company Holiday Unpaid", "FMLA Unpaid", "Suspension", "Unpaid Sick Time"])
IT_ITEMS = ["Client Hardware", "Client Hardware Replacement", "Client Software", "Client Software Replacement", "Client Tools",
            "Skycom Hardware", "Skycom Hardware Replacement", "Skycom Software", "Skycom Software Replacement", "Skycom Tools",
            "Third Party Service Issue"]
TD_ITEMS = ["External Development Time", "Nesting Offline Activity", "Nesting Online Activity", "New Hire Training",
            "Skycom Academy", "Tenured Hire Training (Client)", "Tenured Hire Training (Skycom)"]
OUT_OF_PHONE = ["Chat", "Email", "Floorwalking", "Research", "SME Work", "Social Media Work", "Tickets Processing"]
UNLOGGED = ["Chat", "Client Project", "Email", "Floorwalking", "Research", "Skycom Project", "Social Media Work", "Training Support"]


_ABBR = [("SCHEDULED_MEDICAL_APPOINTMENT", "MEDICAL_APPOINTMENT"), ("REPLACEMENT", "REPL"),
         ("TENURED_HIRE_TRAINING", "TENURED_TRAINING"), ("EXTERNAL_DEVELOPMENT_TIME", "EXTERNAL_DEVELOPMENT"),
         ("THIRD_PARTY_SERVICE_ISSUE", "THIRD_PARTY_SERVICE")]


def _code(prefix: str, text: str) -> str:
    slug = re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")
    for long, short in _ABBR:
        slug = slug.replace(long, short)
    return (prefix + slug)[:30].rstrip("_")


def _rows():
    """(code, name, category, tipo, color, icon, paid, billable, client_paid, login, full_day, partial, ap, review, rules_from)."""
    out = []
    for name in HR_PAID:
        out.append((_code("HRP_", name), f"Paid Time Off - {name}", "HR_PAID", "TIME_OFF", "#db2777", "heart", True, False, "NONE",
                    False, True, True, True, "WFM,HR,FIN", None))
    for name in HR_UNPAID:
        out.append((_code("HRU_", name), f"Unpaid Time Off - {name}", "HR_UNPAID", "TIME_OFF", "#9d174d", "heart", False, False,
                    "NONE", False, True, True, True, "WFM,HR", None))
    out.append(("HRU_ATTRITION", "Attrition", "HR_UNPAID", "TIME_OFF", "#9d174d", "user-x", False, False, "NONE",
                False, True, False, True, "WFM,HR,FIN", None))
    for paid, prefix, color in ((True, "ITP_", "#7c3aed"), (False, "ITU_", "#5b21b6")):
        for name in IT_ITEMS:
            out.append((_code(prefix, name), f"Tech Issues {'Paid' if paid else 'Unpaid'} - {name}", "IT_SYSTEM_ISSUES", "SYSTEM_ISSUE",
                        color, "laptop", paid, False, "NONE", False, False, True, False, "WFM,IT", None))
    for billable, prefix, color in ((True, "TDB_", "#4f46e5"), (False, "TDN_", "#6366f1")):
        for name in TD_ITEMS:
            online = name == "Nesting Online Activity"
            out.append((_code(prefix, name), f"{'Billable' if billable else 'Non Billable'} - {name}", "TD_TRAINING", "TRAINING",
                        color, "school", True, billable, "MANDATORY" if billable else "NONE", online, True, True, False, "WFM,OM",
                        "PRODUCTION" if online else None))
    for name in OUT_OF_PHONE:
        out.append((_code("OPW_", name), f"Out of the Phone - {name}", "WFM_OUT_OF_PHONE", "BACK_OFFICE", "#0f766e", "briefcase",
                    True, True, "MANDATORY", True, False, True, False, "WFM,OM", "BACK_OFFICE"))
    for name in UNLOGGED:
        out.append((_code("WTU_", name), f"Worked Time Unlogged - {name}", "WFM_UNLOGGED", "BACK_OFFICE", "#115e59", "briefcase",
                    True, True, "MANDATORY", False, False, True, False, "WFM,OM,FIN", None))
    return out


SYSTEM = [
    # code, name, system_role, tipo, color, icon, paid, login, full_day, partial, default_seconds
    ("LATENESS", "Lateness", "LATENESS", "ATTENDANCE", "#dc2626", "alarm", False, True, False, True, None),
    ("UNJUSTIFIED_ABSENCE", "Unjustified Absence", "ABSENCE", "ATTENDANCE", "#7f1d1d", "user-x", False, True, True, True, None),
    ("LEGAL_BENEFIT_LUNCH", "Legal Benefit Lunch", "LEGAL_LUNCH", "MEAL", "#f59e0b", "utensils", False, False, False, True, 3600),
]


def seed(apps, schema_editor):
    Category = apps.get_model("adherence", "UtilizationCategory")
    Activity = apps.get_model("adherence", "ActivityType")
    Rule = apps.get_model("adherence", "ActivityStatusRule")
    cats = {}
    for code, name, dept, order in CATEGORIES:
        cats[code], _ = Category.objects.get_or_create(code=code, defaults={"name": name, "department": dept, "sort_order": order})
    for code, cat in EXISTING.items():
        Activity.objects.filter(code=code, utilization_category__isnull=True).update(utilization_category=cats[cat])
    Activity.objects.filter(is_billable=True, client_paid="NONE").update(client_paid="MANDATORY")
    Activity.objects.filter(code="TRAINING").update(allows_full_day=True)  # capacitación de día completo (con AP)
    Activity.objects.filter(code="MEAL").update(review_areas="WFM")
    rules_of = {a.code: list(Rule.objects.filter(activity=a)) for a in Activity.objects.filter(code__in=["PRODUCTION", "BACK_OFFICE"])}
    codes = [r[0] for r in _rows()]
    assert len(codes) == len(set(codes)), "códigos duplicados en el Time Utilization"
    for i, (code, name, cat, kind, color, icon, paid, billable, client_paid, login, full_day, partial, ap, review, rules_from) \
            in enumerate(_rows()):
        if Activity.objects.filter(code=code).exists():
            continue
        source = rules_of.get(rules_from) if rules_from else None
        a = Activity.objects.create(
            code=code, name=name[:80], category=kind, color=color, icon=icon, is_paid=paid, is_billable=billable,
            client_paid=client_paid, requires_acd_login=bool(login and source), allows_full_day=full_day, allows_partial=partial,
            requires_ap=ap, review_areas=review, utilization_category=cats[cat], sort_order=cats[cat].sort_order * 10 + i % 100,
            description=f"Time Utilization: {DEPARTMENTS[cats[cat].department]} › {cats[cat].name}.",
        )
        for r in source or []:
            Rule.objects.create(activity=a, primary_status_id=r.primary_status_id, aux_code_id=r.aux_code_id, role=r.role)
    for code, name, role, kind, color, icon, paid, login, full_day, partial, secs in SYSTEM:
        if Activity.objects.filter(system_role=role).exists() or Activity.objects.filter(code=code).exists():
            continue
        Activity.objects.create(
            code=code, name=name, system_role=role, category=kind, color=color, icon=icon, is_paid=paid, is_billable=False,
            requires_acd_login=login, allows_full_day=full_day, allows_partial=partial, requires_ap=False, review_areas="WFM,HR",
            default_seconds=secs, utilization_category=cats["ATTENDANCE"], sort_order=900,
            description="La inserta el sistema (Fase 19): no se coloca desde la barra de segmentos.",
        )


def unseed(apps, schema_editor):
    Activity = apps.get_model("adherence", "ActivityType")
    Segment = apps.get_model("adherence", "ScheduleSegment")
    used = set(Segment.objects.values_list("activity_id", flat=True))
    prefixes = ("HRP_", "HRU_", "ITP_", "ITU_", "TDB_", "TDN_", "OPW_", "WTU_")
    for a in Activity.objects.exclude(pk__in=used):
        if a.code.startswith(prefixes) or a.system_role:
            a.delete()


SEGMENT_TRIGGER = """
CREATE OR ALTER TRIGGER dbo.TR_adh_schedule_segment_rules
ON dbo.adh_schedule_segment
AFTER INSERT, UPDATE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.adh_schedule_segment AS s
          ON s.employee_id = i.employee_id AND s.id <> i.id
         AND s.start_at < i.end_at AND i.start_at < s.end_at
    )
        THROW 50070, N'Segmentos: el segmento de actividad se traslapa con otro del mismo agente.', 1;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.adh_activity_type AS t ON t.id = i.activity_id
        LEFT JOIN dbo.pa_action AS a ON a.id = i.personnel_action_id
        WHERE (t.requires_ap = 1 AND i.origin <> N'SYSTEM' AND a.id IS NULL)
           OR (a.id IS NOT NULL AND (a.status <> N'APPROVED' OR a.employee_id <> i.employee_id))
    )
        THROW 50072, N'Segmentos: la actividad o el cambio exige una AP aprobada del mismo empleado.', 1;
    IF EXISTS (
        SELECT 1
        FROM inserted AS i
        JOIN dbo.adh_activity_type AS t ON t.id = i.activity_id
        WHERE t.system_role <> N'' AND i.origin <> N'SYSTEM'
    )
        THROW 50074, N'Segmentos: Lateness, Unjustified Absence y Legal Benefit Lunch solo los inserta el sistema.', 1;
END
"""

LOCKED_TRIGGER = """
CREATE OR ALTER TRIGGER dbo.TR_adh_schedule_segment_locked
ON dbo.adh_schedule_segment
AFTER UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT EXISTS (SELECT 1 FROM deleted WHERE is_locked = 1)
        RETURN;
    IF ISNULL(CAST(SESSION_CONTEXT(N'adh.replace_locked') AS int), 0) = 1
        RETURN;
    IF NOT EXISTS (SELECT 1 FROM inserted)
       OR EXISTS (
            SELECT 1
            FROM deleted AS d
            JOIN inserted AS i ON i.id = d.id
            WHERE d.is_locked = 1
              AND (i.start_at <> d.start_at OR i.end_at <> d.end_at OR i.activity_id <> d.activity_id
                   OR i.employee_id <> d.employee_id OR i.is_locked <> d.is_locked)
       )
        THROW 50073, N'Segmentos: el Lateness o la ausencia no se elimina ni se mueve; solo se reemplaza con un segmento respaldado por AP.', 1;
END
"""

SEGMENT_VIEW = """
CREATE OR ALTER VIEW dbo.vw_AdhScheduleSegment
AS
SELECT
    s.id                AS SegmentId,
    e.EmployeeCode      AS EmployeeId,
    CONCAT_WS(N' ', e.FirstName, e.MiddleName, e.LastName, e.SecondLastName) AS EmployeeName,
    s.shift_date        AS ShiftDate,
    s.start_at          AS StartLocal,
    s.end_at            AS EndLocal,
    DATEDIFF(SECOND, s.start_at, s.end_at)                              AS DurationSeconds,
    CAST(DATEDIFF(SECOND, s.start_at, s.end_at) / 60.0 AS decimal(9, 4)) AS Minutes,
    t.code              AS ActivityCode,
    t.name              AS ActivityName,
    t.category          AS ActivityCategory,
    t.is_paid           AS IsPaid,
    t.is_billable       AS IsBillable,
    pa.folio            AS ScheduleActionFolio,
    s.notes             AS Notes,
    s.origin            AS Origin,
    s.is_locked         AS IsLocked,
    bk.folio            AS BackingActionFolio,
    uc.department       AS Department,
    uc.name             AS UtilizationCategory,
    t.requires_ap       AS RequiresAp,
    t.requires_acd_login AS RequiresAcdLogin,
    NULLIF(t.system_role, N'') AS SystemRole
FROM dbo.adh_schedule_segment AS s
JOIN hcm.Employee AS e ON e.EmployeeId = s.employee_id
JOIN dbo.adh_activity_type AS t ON t.id = s.activity_id
LEFT JOIN dbo.adh_activity_category AS uc ON uc.id = t.utilization_category_id
LEFT JOIN dbo.sch_schedule_assignment AS sa ON sa.id = s.assignment_id
LEFT JOIN dbo.pa_action AS pa ON pa.id = sa.personnel_action_id
LEFT JOIN dbo.pa_action AS bk ON bk.id = s.personnel_action_id;
"""

REQUEST_VIEW = """
CREATE OR ALTER VIEW dbo.vw_AdhChangeRequest
AS
SELECT
    r.id                AS RequestId,
    e.EmployeeCode      AS EmployeeId,
    CONCAT_WS(N' ', e.FirstName, e.MiddleName, e.LastName, e.SecondLastName) AS EmployeeName,
    r.shift_date        AS ShiftDate,
    r.kind              AS Kind,
    r.status            AS Status,
    r.requester_role    AS RequesterRole,
    ru.username         AS RequestedBy,
    r.requested_at      AS RequestedAtUtc,
    t.code              AS ProposedActivity,
    r.start_at          AS ProposedStartLocal,
    r.end_at            AS ProposedEndLocal,
    pa.folio            AS BackingActionFolio,
    r.reason            AS Reason,
    du.username         AS DecidedBy,
    r.decided_at        AS DecidedAtUtc,
    r.decision_comment  AS DecisionComment,
    r.applied_segment_id AS AppliedSegmentId
FROM dbo.adh_change_request AS r
JOIN hcm.Employee AS e ON e.EmployeeId = r.employee_id
LEFT JOIN dbo.adh_activity_type AS t ON t.id = r.activity_id
LEFT JOIN dbo.pa_action AS pa ON pa.id = r.personnel_action_id
LEFT JOIN dbo.accounts_customuser AS ru ON ru.id = r.requested_by_id
LEFT JOIN dbo.accounts_customuser AS du ON du.id = r.decided_by_id;
"""

FK = ("IF OBJECT_ID(N'dbo.FK_adh_change_request_Employee', N'F') IS NULL\n"
      "    ALTER TABLE dbo.adh_change_request WITH CHECK ADD CONSTRAINT FK_adh_change_request_Employee "
      "FOREIGN KEY (employee_id) REFERENCES hcm.Employee (EmployeeId);")

FORWARD = [FK, SEGMENT_TRIGGER, LOCKED_TRIGGER, SEGMENT_VIEW, REQUEST_VIEW]
REVERSE = [
    "IF OBJECT_ID(N'dbo.vw_AdhChangeRequest', N'V') IS NOT NULL DROP VIEW dbo.vw_AdhChangeRequest;",
    _m6.SEGMENT_VIEW,
    "IF OBJECT_ID(N'dbo.TR_adh_schedule_segment_locked', N'TR') IS NOT NULL DROP TRIGGER dbo.TR_adh_schedule_segment_locked;",
    _m2.SEGMENT_TRIGGER,
    "IF OBJECT_ID(N'dbo.FK_adh_change_request_Employee', N'F') IS NOT NULL ALTER TABLE dbo.adh_change_request DROP CONSTRAINT FK_adh_change_request_Employee;",
]


class Migration(migrations.Migration):
    dependencies = [("adherence", "0007_phase19_attendance_categories_requests"), ("personnel_actions", "0005_seed_additional_schedule_type")]

    operations = [
        migrations.RunSQL(FORWARD, REVERSE),
        migrations.RunPython(seed, unseed),
    ]
