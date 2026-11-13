/* =============================================================================
   Metamorph ERP - 097: Fase 22 - retiro del módulo mock «Asistencias y downtimes»
   -----------------------------------------------------------------------------
   La operación se gestiona con la grilla IEX (adh_schedule_segment), el motor de
   adherencia, la asistencia automática (Lateness / Unjustified Absence) y el Web
   Timer (sch_time_record). Las tablas de ingesta paramétrica del esquema wfm
   nunca tuvieron datos operativos: se eliminan junto con el esquema.
   Idempotente: en una BD nueva no hay nada que borrar.
   ============================================================================= */
SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

IF OBJECT_ID(N'wfm.AttendanceDowntime', N'U')  IS NOT NULL DROP TABLE wfm.AttendanceDowntime;
IF OBJECT_ID(N'wfm.Attendance', N'U')          IS NOT NULL DROP TABLE wfm.Attendance;
IF OBJECT_ID(N'wfm.IngestionBatchError', N'U') IS NOT NULL DROP TABLE wfm.IngestionBatchError;
IF OBJECT_ID(N'wfm.IngestionBatch', N'U')      IS NOT NULL DROP TABLE wfm.IngestionBatch;
IF OBJECT_ID(N'wfm.DowntimeCodeMap', N'U')     IS NOT NULL DROP TABLE wfm.DowntimeCodeMap;
IF OBJECT_ID(N'wfm.IngestionFieldMap', N'U')   IS NOT NULL DROP TABLE wfm.IngestionFieldMap;
IF OBJECT_ID(N'wfm.catDowntimeType', N'U')     IS NOT NULL DROP TABLE wfm.catDowntimeType;
IF OBJECT_ID(N'wfm.catIngestionSource', N'U')  IS NOT NULL DROP TABLE wfm.catIngestionSource;
GO

IF SCHEMA_ID(N'wfm') IS NOT NULL
   AND NOT EXISTS (SELECT 1 FROM sys.objects WHERE schema_id = SCHEMA_ID(N'wfm'))
    EXEC (N'DROP SCHEMA wfm;');
GO
