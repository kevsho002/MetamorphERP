"""Fase 25 — Catálogo de objetos programables de SQL Server (vistas, procedimientos, funciones y triggers).

PURPOSES documenta el propósito de cada objeto; la migración system.0015 lo graba como propiedad extendida
`MS_Description` (visible en SSMS) y la vista adm.vw_SystemSqlObject lo expone junto al estado de cada objeto.
"""

from __future__ import annotations

PURPOSES: dict[str, str] = {
    # ---------------------------------------------------------------- vistas
    "vw_OpsClientBrand": "Cuentas (clientes) con sus marcas y líneas de negocio para reportería.",
    "vw_OpsLeaderHierarchy": "Cadena de mando de líderes operativos vigentes: nivel, puesto y a quién reportan.",
    "vw_RosterAgentHierarchy": "Jerarquía vigente de cada agente (Team Manager, supervisor, gerente) según el roster.",
    "vw_RosterAssignment": "Asignaciones del roster por colaborador (cliente, campaña, wave…) con vigencia.",
    "vw_EmployeeGeneralId": "General IDs de cada colaborador (ACD ID, Payroll Tool ID…) listos para JOIN.",
    "vw_EmployeeTenure": "Antigüedad, días suspendidos y estado del ciclo de vida laboral de cada colaborador.",
    "vw_HolidayCalendar": "Calendario de feriados por país con día de la semana ISO y recargo.",
    "vw_HolidaySegment": "Holiday Segments: feriados laborados por colaborador con sus horas y recargo.",
    "vw_SchAttendanceCutoff": "Cortes internos de asistencia (25→9, 10→24) con el periodo de pago que los liquida.",
    "vw_SchLunchRule": "Reglas de almuerzo por país: tiempo continuo mínimo y minutos de almuerzo legal.",
    "vw_SchPayPeriod": "Periodos de pago por ciclo con sus cortes y el estado de la asistencia.",
    "vw_SchPayrollHours": "Horas teóricas y reales por colaborador y periodo para la planilla.",
    "vw_SchScheduleAssignment": "Horarios asignados por fecha efectiva (principal o adicional) por colaborador.",
    "vw_SchScheduleDay": "Bloques diarios del horario: entrada, duración y minutos nocturnos.",
    "vw_SchTimeByOccurrenceDate": "Tiempo registrado (Web Timer) agrupado por fecha de ocurrencia.",
    "vw_AdhAdherenceDay": "Adherencia diaria guardada: % de adherencia, tiempo validado y excesos.",
    "vw_AdhChangeRequest": "Solicitudes de cambio de WFM (cola de aprobación) con su estado.",
    "vw_AdhDeviation": "Desviaciones de adherencia: actividad programada contra estado real del ACD.",
    "vw_AdhScheduleSegment": "Segmentos de la grilla IEX por colaborador con su duración al segundo.",
    "vw_AcdAgentSession": "Sesiones de agentes en el ACD (inicio, fin y duración).",
    "vw_AcdStatusSegment": "Tramos de estado primario / auxiliar del ACD por agente (formato Genesys).",
    "vw_PaActionAttachment": "Adjuntos (evidencias) de las acciones de personal, vigentes y retirados.",
    "vw_PersonnelAction": "Acciones de personal con folio, tipo, colaborador, estado y firmas.",
    "vw_PayPayrollDetail": "Detalle de planilla por colaborador: devengado, retenciones de ley y líquido.",
    "vw_PayPayrollDay": "Boleta diaria: cada fecha del corte con horas decimales y su traducción a dinero.",
    "vw_PayPayslipInventory": "Inventario de boletas físicas: impresión, firma, archivo y departamento.",
    "vw_PaySettlement": "Liquidaciones (finiquitos) con su lote, montos y estado.",
    "vw_SystemForeignKeys": "Relaciones (FK) de todas las tablas para dibujar el modelo entidad-relación.",
    "vw_SystemSqlObject": "Catálogo de vistas, procedimientos, funciones y triggers con estado, esquema y propósito.",
    "vw_AnnouncementCompliance": "Cumplimiento del acuse de recibo por comunicado: audiencia, confirmados y %.",
    # ---------------------------------------------------------------- procedimientos
    "usp_GenerateEmployeeCode": "Genera el ID corporativo del colaborador por país con dígito verificador.",
    "usp_HolidayCopyYear": "Copia los feriados de un año a otro (Semana Santa con la Pascua del año destino).",
    "usp_SystemTableStats": "Filas, espacio de datos e índices, columnas, FK y triggers por tabla.",
    "usp_SystemTableColumns": "Columnas de las tablas (tipo, nulos, PK, FK) para el ERD interactivo.",
    "usp_AnnouncementComplianceReport": "Reporte por usuario del acuse de recibo de un comunicado (pendiente, vencido…).",
    # ---------------------------------------------------------------- funciones
    "fn_ComputeCheckDigit": "Dígito verificador del ID corporativo (idéntico al de la aplicación).",
    "fn_EasterSunday": "Domingo de Pascua de un año (base de Semana Santa en el calendario de feriados).",
    "fn_EmployeesUnderLeader": "Colaboradores bajo la jerarquía directa o indirecta de un líder en una fecha.",
    # ---------------------------------------------------------------- triggers
    "TR_acd_aux_code_rules": "Un sub-auxiliar tiene un solo nivel y el mismo estado primario que su padre.",
    "TR_acd_status_segment_rules": "Tramos de estado del ACD sin traslapes por agente y con auxiliar de su mismo estado primario.",
    "TR_adh_exception_rules": "La AP que justifica una excepción de adherencia debe estar aprobada y ser del mismo colaborador.",
    "TR_adh_schedule_segment_locked": "Un segmento bloqueado (Lateness / ausencia) no se mueve ni se elimina, salvo el reemplazo documentado.",
    "TR_adh_schedule_segment_rules": "Segmentos de la grilla sin traslapes por agente y con AP aprobada cuando la actividad la exige.",
    "TR_gid_employee_general_id_rules": "Valor único por tipo en fechas que se cruzan y un ID vigente por tipo y colaborador.",
    "TR_hol_holiday_locked": "Un feriado con Holiday Segments no cambia de país ni de fecha y no se elimina.",
    "TR_ops_leader_rules": "Cada líder reporta a un líder activo del nivel inmediato superior.",
    "TR_pa_action_attachment_no_delete": "Los adjuntos de las AP nunca se borran (se retiran con motivo).",
    "TR_pa_action_attachment_rules": "Adjuntos solo en AP abiertas; contenido inmutable; retiro con motivo e irreversible.",
    "TR_pa_action_content_frozen": "Enviada la AP, su folio, tipo, colaborador, fecha efectiva y justificación ya no cambian.",
    "TR_pa_action_signature_immutable": "Las firmas digitales de las AP son inmutables.",
    "TR_pa_action_value_frozen": "Los valores (EAV) de una AP solo cambian mientras es borrador.",
    "TR_pa_employment_event_rules": "El historial laboral no se elimina ni se modifica: solo se registra.",
    "TR_pay_payroll_line_rules": "Las líneas de una planilla cerrada no cambian; las AP pagadas deben estar aprobadas.",
    "TR_pay_payroll_day_rules": "La boleta diaria de una planilla cerrada o pagada no cambia.",
    "TR_pay_payslip_rules": "Las boletas solo se generan de una planilla cerrada y coinciden con su línea de planilla.",
    "TR_pay_settlement_batch_rules": "Un lote de pago solo contiene liquidaciones aprobadas o pagadas; un lote pagado no cambia.",
    "TR_pay_settlement_line_locked": "Las líneas de una liquidación aprobada o pagada no cambian.",
    "TR_pay_settlement_rules": "Una liquidación aprobada o pagada no cambia sus montos, fechas, colaborador ni su sello.",
    "TR_roster_assignment_no_overlap": "Asignaciones del roster sin intervalos superpuestos por atributo y colaborador.",
    "TR_sch_attendance_cutoff_rules": "Cortes contiguos sin huecos ni colisiones, mapeados al periodo de su cierre; cerrados no cambian.",
    "TR_sch_lunch_rule_rules": "Un umbral de almuerzo por país y fechas.",
    "TR_sch_night_rule_rules": "Una regla de nocturnidad activa por país en fechas que se cruzan.",
    "TR_sch_pay_period_rules": "Periodos de pago contiguos, sin huecos ni colisiones por ciclo.",
    "TR_sch_schedule_assignment_rules": "Un solo horario principal por fecha; los adicionales conviven con él.",
    "TR_sch_time_record_rules": "Los registros de entrada / salida de un colaborador no se traslapan.",
    "TR_fin_Payroll_status": "El estado de la planilla solo avanza (cerrada → pagada); una planilla cerrada no se elimina.",
    "TR_fin_PayrollDetail_locked": "El detalle de una planilla cerrada no cambia.",
    "TR_fin_PayrollDeduction_locked": "Las retenciones de una planilla cerrada no cambian.",
    "TR_com_announcement_ack_rules": "Acuses de recibo inmutables y solo sobre comunicados publicados con acuse.",
    "TR_com_announcement_rules": "El contenido de un comunicado con acuse publicado queda congelado.",
    "TR_com_announcement_no_delete": "Solo se eliminan borradores de comunicados (los publicados se archivan).",
    "TR_com_compliance_snapshot_locked": "Las fotos de cumplimiento (compliance) son inmutables.",
}

LEVEL1 = {"V": "VIEW", "P": "PROCEDURE", "FN": "FUNCTION", "IF": "FUNCTION", "TF": "FUNCTION"}


def apply_descriptions(cursor) -> int:
    """Graba (o actualiza) la propiedad extendida MS_Description de cada objeto documentado que exista."""
    cursor.execute("""
        SELECT o.name, RTRIM(o.type), SCHEMA_NAME(o.schema_id), OBJECT_NAME(o.parent_object_id),
               CASE WHEN ep.major_id IS NULL THEN 0 ELSE 1 END
        FROM sys.objects o
        LEFT JOIN sys.extended_properties ep ON ep.major_id = o.object_id AND ep.minor_id = 0 AND ep.name = N'MS_Description'
        WHERE o.is_ms_shipped = 0 AND o.type IN ('V', 'P', 'FN', 'IF', 'TF', 'TR')""")
    n = 0
    for name, kind, schema, parent, has in cursor.fetchall():
        text = PURPOSES.get(name)
        if not text:
            continue
        proc = "sys.sp_updateextendedproperty" if has else "sys.sp_addextendedproperty"
        if kind == "TR":
            cursor.execute(f"EXEC {proc} @name = N'MS_Description', @value = %s, @level0type = N'SCHEMA', @level0name = %s, "
                           "@level1type = N'TABLE', @level1name = %s, @level2type = N'TRIGGER', @level2name = %s",
                           [text, schema, parent, name])
        else:
            cursor.execute(f"EXEC {proc} @name = N'MS_Description', @value = %s, @level0type = N'SCHEMA', @level0name = %s, "
                           "@level1type = %s, @level1name = %s", [text, schema, LEVEL1[kind], name])
        n += 1
    return n
