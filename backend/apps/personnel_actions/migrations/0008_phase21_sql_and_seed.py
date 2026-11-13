"""Fase 21: ciclo de vida del colaborador y control de AP por roles.

* FK de dbo.pa_employment_event a hcm.Employee (SQL-first).
* TR_pa_employment_event_rules (50094): el historial laboral no se elimina y sus datos no cambian; solo se registra
  la reactivación automática al terminar una suspensión (reactivated_at).
* Vista dbo.vw_EmployeeTenure: antigüedad vigente (desde la fecha de ingreso actual; el reingreso la reinicia) menos los
  días suspendidos (la suspensión la congela) e indicador de recontratación de la última terminación.
* Tipos de AP: suspensión disciplinaria, terminación / renuncia (indicador interno de recontratación, visible solo con
  hcm.manage) y reingreso. Roles que elaboran cada tipo (Generalista de RRHH, WFM, Administrador).
"""

from django.db import migrations

FK = """
IF OBJECT_ID(N'dbo.FK_pa_employment_event_employee', N'F') IS NULL
    ALTER TABLE dbo.pa_employment_event WITH CHECK ADD CONSTRAINT FK_pa_employment_event_employee
        FOREIGN KEY (employee_id) REFERENCES hcm.Employee (EmployeeId);
"""
FK_DROP = """
IF OBJECT_ID(N'dbo.FK_pa_employment_event_employee', N'F') IS NOT NULL
    ALTER TABLE dbo.pa_employment_event DROP CONSTRAINT FK_pa_employment_event_employee;
"""

EVENT_RULES = """
CREATE OR ALTER TRIGGER dbo.TR_pa_employment_event_rules
ON dbo.pa_employment_event
AFTER UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF NOT EXISTS (SELECT 1 FROM inserted) AND EXISTS (SELECT 1 FROM deleted)
        THROW 50094, N'El historial laboral (ingresos, suspensiones, terminaciones y reingresos) no se elimina.', 1;
    IF EXISTS (
        SELECT 1 FROM inserted i JOIN deleted d ON d.id = i.id
        WHERE i.employee_id <> d.employee_id OR i.kind <> d.kind OR i.start_date <> d.start_date
           OR ISNULL(i.end_date, '19000101') <> ISNULL(d.end_date, '19000101')
           OR ISNULL(i.action_id, -1) <> ISNULL(d.action_id, -1)
           OR i.termination_reason <> d.termination_reason
           OR ISNULL(CONVERT(int, i.rehire_eligible), -1) <> ISNULL(CONVERT(int, d.rehire_eligible), -1)
           OR i.hr_notes <> d.hr_notes
           OR ISNULL(i.previous_hire_date, '19000101') <> ISNULL(d.previous_hire_date, '19000101')
           OR ISNULL(i.previous_termination_date, '19000101') <> ISNULL(d.previous_termination_date, '19000101')
    )
        THROW 50094, N'El historial laboral es inmutable: solo se registra la reactivación al terminar una suspensión.', 1;
END;
"""

TENURE_VIEW = """
CREATE OR ALTER VIEW dbo.vw_EmployeeTenure
AS
SELECT
    e.EmployeeId, e.EmployeeCode, e.EmploymentStatus, e.HireDate, e.TerminationDate,
    t.EndDate AS TenureEndDate,
    DATEDIFF(day, e.HireDate, t.EndDate) + 1 AS CalendarDays,
    ISNULL(s.SuspendedDays, 0) AS SuspendedDays,
    DATEDIFF(day, e.HireDate, t.EndDate) + 1 - ISNULL(s.SuspendedDays, 0) AS TenureDays,
    CAST((DATEDIFF(day, e.HireDate, t.EndDate) + 1 - ISNULL(s.SuspendedDays, 0)) / 365.25 AS decimal(9, 2)) AS TenureYears,
    lt.rehire_eligible AS LastTerminationRehireEligible
FROM hcm.Employee e
CROSS APPLY (SELECT CASE WHEN e.TerminationDate IS NOT NULL AND e.TerminationDate < CAST(GETDATE() AS date)
                         THEN e.TerminationDate ELSE CAST(GETDATE() AS date) END AS EndDate) t
OUTER APPLY (
    SELECT SUM(x.Days) AS SuspendedDays
    FROM (
        SELECT DATEDIFF(day,
                        CASE WHEN ev.start_date > e.HireDate THEN ev.start_date ELSE e.HireDate END,
                        CASE WHEN ev.end_date < t.EndDate THEN ev.end_date ELSE t.EndDate END) + 1 AS Days
        FROM dbo.pa_employment_event ev
        WHERE ev.employee_id = e.EmployeeId AND ev.kind = N'SUSPENSION'
          AND ev.end_date >= e.HireDate AND ev.start_date <= t.EndDate
    ) x
) s
OUTER APPLY (
    SELECT TOP (1) ev.rehire_eligible FROM dbo.pa_employment_event ev
    WHERE ev.employee_id = e.EmployeeId AND ev.kind = N'TERMINATION' ORDER BY ev.start_date DESC, ev.id DESC
) lt;
"""

REASONS = ["Renuncia voluntaria", "Despido sin causa justificada", "Despido con causa justificada", "Fin de contrato a plazo",
           "Mutuo acuerdo", "Abandono de labores"]
REASON_CHOICES = [{"value": v, "label": l} for v, l in zip(
    ["RENUNCIA", "DESPIDO_SIN_CAUSA", "DESPIDO_CON_CAUSA", "FIN_CONTRATO", "MUTUO_ACUERDO", "ABANDONO"], REASONS)]

AP_TYPES = [
    {
        "code": "AP_SUSPENSION", "name": "Suspensión disciplinaria", "category": "STATUS", "effect": "SUSPENSION",
        "folio_prefix": "APSU", "creator_signs_first_step": True, "display_order": 60, "creator_roles": ["HR", "ADMIN"],
        "view_permission": "hcm.view", "create_permission": "hcm.manage",
        "description": "Inactiva al colaborador por los días indicados desde la fecha efectiva (sin goce de salario) y congela su "
                       "antigüedad; al terminar vuelve a Activo automáticamente.",
        "attributes": [
            {"key": "dias", "label": "Días de suspensión", "data_type": "INTEGER", "required": True, "display_order": 10,
             "min_value": "1", "max_value": "30", "help_text": "Días calendario desde la fecha efectiva (Código de Trabajo: hasta 30)."},
            {"key": "falta", "label": "Falta disciplinaria", "data_type": "CHOICE", "required": True, "display_order": 20,
             "choices": ["Ausencias injustificadas", "Incumplimiento de políticas", "Conducta inapropiada", "Reincidencia", "Otra"]},
        ],
        "steps": [(1, "Generalista de Recursos Humanos", "HR"), (2, "Aprobación de Administración / Gerencia", "ADMIN")],
    },
    {
        "code": "AP_TERMINACION", "name": "Terminación / renuncia", "category": "STATUS", "effect": "TERMINATION",
        "folio_prefix": "APTE", "creator_signs_first_step": True, "display_order": 61, "creator_roles": ["HR", "ADMIN"],
        "view_permission": "hcm.manage", "create_permission": "hcm.manage",
        "description": "Termina la relación laboral en la fecha efectiva (último día laborado). Registra el indicador INTERNO de "
                       "recomendación de recontratación (solo RRHH) y abre la liquidación del colaborador.",
        "attributes": [
            {"key": "motivo_terminacion", "label": "Motivo de terminación", "data_type": "CHOICE", "required": True,
             "display_order": 10, "choices": REASON_CHOICES},
            {"key": "recomendable_recontratacion", "label": "¿Recomendable para recontratación?", "data_type": "BOOLEAN",
             "required": True, "display_order": 20, "help_text": "Indicador interno: solo lo ve Recursos Humanos en el perfil."},
            {"key": "observaciones_rrhh", "label": "Observaciones internas de RRHH", "data_type": "LONG_TEXT", "required": False,
             "display_order": 30, "max_length": 2000},
        ],
        "steps": [(1, "Generalista de Recursos Humanos", "HR"), (2, "Aprobación de Administración / Gerencia", "ADMIN")],
    },
    {
        "code": "AP_REINGRESO", "name": "Reingreso de colaborador", "category": "STATUS", "effect": "REHIRE",
        "folio_prefix": "APRI", "creator_signs_first_step": True, "display_order": 62, "creator_roles": ["HR", "ADMIN"],
        "view_permission": "hcm.manage", "create_permission": "hcm.manage",
        "description": "Reactiva a un colaborador que ya laboró en la empresa: la fecha efectiva es su nueva fecha de ingreso y su "
                       "antigüedad se reinicia. Si su última terminación no lo recomendó, el sistema emite una alerta formal.",
        "attributes": [
            {"key": "new_base_salary", "label": "Salario base mensual del reingreso", "data_type": "DECIMAL", "required": True,
             "display_order": 10, "min_value": "0.01"},
            {"key": "motivo", "label": "Motivo del reingreso", "data_type": "TEXT", "required": True, "display_order": 20,
             "max_length": 300},
        ],
        "steps": [(1, "Generalista de Recursos Humanos", "HR")],
    },
]

# Roles que elaboran los tipos existentes (Fase 21: validación estricta).
CREATOR_ROLES = {
    "AP_HORARIO_INICIAL": ["HR", "ADMIN"],
    "AP_CAMBIO_HORARIO": ["WFM", "HR", "ADMIN"],
    "AP_HORARIO_ADICIONAL": ["WFM", "HR", "ADMIN"],
    "AP_AJUSTE_SALARIAL": ["HR", "ADMIN"],
    "AP_HORAS_EXTRA": ["WFM", "HR", "ADMIN"],
    "AP_JUSTIFICACION_TIEMPO": ["WFM", "HR", "ADMIN"],
    "AP_BONIFICACION": ["HR", "ADMIN"],
    "AP_VACACIONES": ["HR", "ADMIN"],
    "AP_DESCUENTO": ["HR", "ADMIN"],
}


def seed(apps, schema_editor):
    ActionType = apps.get_model("personnel_actions", "ActionType")
    Attribute = apps.get_model("personnel_actions", "ActionAttribute")
    Step = apps.get_model("personnel_actions", "ApprovalStep")
    for code, roles in CREATOR_ROLES.items():
        ActionType.objects.filter(code=code, creator_roles=[]).update(creator_roles=roles)
    for spec in AP_TYPES:
        spec = dict(spec)
        attributes, steps = spec.pop("attributes"), spec.pop("steps")
        if ActionType.objects.filter(code=spec["code"]).exists():
            continue
        t = ActionType.objects.create(**spec)
        for a in attributes:
            Attribute.objects.create(action_type=t, **a)
        for order, label, role in steps:
            Step.objects.create(action_type=t, order=order, label=label, role=role)


def unseed(apps, schema_editor):
    ActionType = apps.get_model("personnel_actions", "ActionType")
    Action = apps.get_model("personnel_actions", "PersonnelAction")
    for spec in AP_TYPES:
        if not Action.objects.filter(action_type__code=spec["code"]).exists():
            ActionType.objects.filter(code=spec["code"]).delete()


class Migration(migrations.Migration):
    dependencies = [("personnel_actions", "0007_phase21_lifecycle_and_roles")]

    operations = [
        migrations.RunSQL(FK, FK_DROP),
        migrations.RunSQL(EVENT_RULES, "DROP TRIGGER IF EXISTS dbo.TR_pa_employment_event_rules;"),
        migrations.RunSQL(TENURE_VIEW, "DROP VIEW IF EXISTS dbo.vw_EmployeeTenure;"),
        migrations.RunPython(seed, unseed),
    ]
