/* =============================================================================
   Metamorph ERP - 030: WFM (Asistencias + ingesta paramétrica WFM / downtimes)
   -----------------------------------------------------------------------------
   Ingesta paramétrica = el formato de cada origen se describe con DATOS,
   no con código:
     wfm.catIngestionSource   origen (WFM externo, biométrico, manual, API...)
                              + Config JSON (delimitador, zona horaria, etc.)
     wfm.IngestionFieldMap    columna origen -> campo destino + formato/transformación
     wfm.DowntimeCodeMap      código de downtime del WFM externo -> tipo interno
     wfm.IngestionBatch       cada carga (archivo/lote), deduplicada por hash
     wfm.IngestionBatchError  errores por fila para reproceso
   Datos operativos:
     wfm.Attendance           <- "Asistencias" (1 registro por empleado y día)
     wfm.AttendanceDowntime   tiempos improductivos dentro de la jornada
     wfm.catDowntimeType      clasificación (pagado, cuenta como trabajado, adherencia)
   ============================================================================= */
SET NOCOUNT ON;
SET XACT_ABORT ON;
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

/* ---------------------------------------------------------------------------
   wfm.catIngestionSource
   --------------------------------------------------------------------------- */
IF OBJECT_ID(N'wfm.catIngestionSource', N'U') IS NULL
BEGIN
    BEGIN TRANSACTION;
    CREATE TABLE wfm.catIngestionSource
    (
        SourceId     INT            IDENTITY(1,1) NOT NULL,
        Code         NVARCHAR(30)   NOT NULL,
        Name         NVARCHAR(150)  NOT NULL,
        SourceType   NVARCHAR(20)   NOT NULL,
        FileFormat   NVARCHAR(10)   NULL,
        TimeZoneName NVARCHAR(64)   NOT NULL CONSTRAINT DF_catIngestionSource_TimeZoneName DEFAULT (N'Central America Standard Time'),
        Config       NVARCHAR(MAX)  NULL,      -- JSON: delimitador, encabezados, hoja, endpoint...
        IsActive     BIT            NOT NULL CONSTRAINT DF_catIngestionSource_IsActive  DEFAULT (1),
        CreatedAt    DATETIME2(0)   NOT NULL CONSTRAINT DF_catIngestionSource_CreatedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT PK_catIngestionSource PRIMARY KEY CLUSTERED (SourceId),
        CONSTRAINT UQ_catIngestionSource_Code UNIQUE (Code),
        CONSTRAINT CK_catIngestionSource_SourceType CHECK (SourceType IN (N'WFM', N'BIOMETRIC', N'MANUAL', N'API', N'FILE')),
        CONSTRAINT CK_catIngestionSource_FileFormat CHECK (FileFormat IS NULL OR FileFormat IN (N'CSV', N'XLSX', N'JSON', N'XML')),
        CONSTRAINT CK_catIngestionSource_Config     CHECK (Config IS NULL OR ISJSON(Config) = 1)
    );
    COMMIT TRANSACTION;
END
GO

/* ---------------------------------------------------------------------------
   wfm.IngestionFieldMap  (mapeo de columnas por origen)
   --------------------------------------------------------------------------- */
IF OBJECT_ID(N'wfm.IngestionFieldMap', N'U') IS NULL
BEGIN
    BEGIN TRANSACTION;
    CREATE TABLE wfm.IngestionFieldMap
    (
        FieldMapId    INT            IDENTITY(1,1) NOT NULL,
        SourceId      INT            NOT NULL,
        SourceField   NVARCHAR(100)  NOT NULL,   -- nombre/índice de la columna en el origen
        TargetField   NVARCHAR(50)   NOT NULL,   -- campo canónico de Metamorph
        DataType      NVARCHAR(20)   NOT NULL,
        FormatPattern NVARCHAR(50)   NULL,       -- p.ej. 'yyyy-MM-dd HH:mm:ss'
        DefaultValue  NVARCHAR(100)  NULL,
        IsRequired    BIT            NOT NULL CONSTRAINT DF_IngestionFieldMap_IsRequired DEFAULT (1),
        TransformRule NVARCHAR(100)  NULL,       -- TRIM, UPPER, SECONDS_TO_MINUTES...
        CONSTRAINT PK_IngestionFieldMap PRIMARY KEY CLUSTERED (FieldMapId),
        CONSTRAINT UQ_IngestionFieldMap_Target UNIQUE (SourceId, TargetField),
        CONSTRAINT FK_IngestionFieldMap_catIngestionSource FOREIGN KEY (SourceId) REFERENCES wfm.catIngestionSource (SourceId) ON DELETE CASCADE,
        CONSTRAINT CK_IngestionFieldMap_TargetField CHECK (TargetField IN (
            N'EmployeeCode', N'WorkDate', N'ScheduledStart', N'ScheduledEnd', N'ActualStart', N'ActualEnd',
            N'AttendanceStatus', N'DowntimeCode', N'DowntimeStart', N'DowntimeEnd', N'DowntimeMinutes', N'Notes')),
        CONSTRAINT CK_IngestionFieldMap_DataType CHECK (DataType IN (N'STRING', N'INT', N'DECIMAL', N'DATE', N'DATETIME', N'TIME'))
    );
    COMMIT TRANSACTION;
END
GO

/* ---------------------------------------------------------------------------
   wfm.catDowntimeType
   --------------------------------------------------------------------------- */
IF OBJECT_ID(N'wfm.catDowntimeType', N'U') IS NULL
BEGIN
    BEGIN TRANSACTION;
    CREATE TABLE wfm.catDowntimeType
    (
        DowntimeTypeId    INT            IDENTITY(1,1) NOT NULL,
        Code              NVARCHAR(30)   NOT NULL,
        Name              NVARCHAR(150)  NOT NULL,
        IsPaid            BIT            NOT NULL CONSTRAINT DF_catDowntimeType_IsPaid           DEFAULT (1),
        CountsAsWorked    BIT            NOT NULL CONSTRAINT DF_catDowntimeType_CountsAsWorked   DEFAULT (0),
        AffectsAdherence  BIT            NOT NULL CONSTRAINT DF_catDowntimeType_AffectsAdherence DEFAULT (1),
        MaxMinutesPerDay  SMALLINT       NULL,
        IsActive          BIT            NOT NULL CONSTRAINT DF_catDowntimeType_IsActive  DEFAULT (1),
        CreatedAt         DATETIME2(0)   NOT NULL CONSTRAINT DF_catDowntimeType_CreatedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT PK_catDowntimeType PRIMARY KEY CLUSTERED (DowntimeTypeId),
        CONSTRAINT UQ_catDowntimeType_Code UNIQUE (Code),
        CONSTRAINT CK_catDowntimeType_MaxMinutes CHECK (MaxMinutesPerDay IS NULL OR MaxMinutesPerDay BETWEEN 1 AND 1440)
    );
    COMMIT TRANSACTION;
END
GO

/* ---------------------------------------------------------------------------
   wfm.DowntimeCodeMap  (código externo del WFM -> tipo interno, por origen)
   --------------------------------------------------------------------------- */
IF OBJECT_ID(N'wfm.DowntimeCodeMap', N'U') IS NULL
BEGIN
    BEGIN TRANSACTION;
    CREATE TABLE wfm.DowntimeCodeMap
    (
        SourceId       INT           NOT NULL,
        ExternalCode   NVARCHAR(50)  NOT NULL,
        DowntimeTypeId INT           NOT NULL,
        CONSTRAINT PK_DowntimeCodeMap PRIMARY KEY CLUSTERED (SourceId, ExternalCode),
        CONSTRAINT FK_DowntimeCodeMap_catIngestionSource FOREIGN KEY (SourceId)       REFERENCES wfm.catIngestionSource (SourceId) ON DELETE CASCADE,
        CONSTRAINT FK_DowntimeCodeMap_catDowntimeType    FOREIGN KEY (DowntimeTypeId) REFERENCES wfm.catDowntimeType (DowntimeTypeId)
    );
    COMMIT TRANSACTION;
END
GO

/* ---------------------------------------------------------------------------
   wfm.IngestionBatch
   --------------------------------------------------------------------------- */
IF OBJECT_ID(N'wfm.IngestionBatch', N'U') IS NULL
BEGIN
    BEGIN TRANSACTION;
    CREATE TABLE wfm.IngestionBatch
    (
        BatchId       BIGINT         IDENTITY(1,1) NOT NULL,
        SourceId      INT            NOT NULL,
        OriginalName  NVARCHAR(255)  NULL,
        Sha256Hash    CHAR(64)       NOT NULL,
        PeriodStart   DATE           NULL,
        PeriodEnd     DATE           NULL,
        BatchStatus   NVARCHAR(20)   NOT NULL CONSTRAINT DF_IngestionBatch_BatchStatus DEFAULT (N'RECEIVED'),
        TotalRows     INT            NOT NULL CONSTRAINT DF_IngestionBatch_TotalRows   DEFAULT (0),
        ValidRows     INT            NOT NULL CONSTRAINT DF_IngestionBatch_ValidRows   DEFAULT (0),
        ErrorRows     INT            NOT NULL CONSTRAINT DF_IngestionBatch_ErrorRows   DEFAULT (0),
        ReceivedAt    DATETIME2(0)   NOT NULL CONSTRAINT DF_IngestionBatch_ReceivedAt  DEFAULT (SYSUTCDATETIME()),
        ProcessedAt   DATETIME2(0)   NULL,
        CreatedBy     NVARCHAR(100)  NOT NULL CONSTRAINT DF_IngestionBatch_CreatedBy   DEFAULT (SUSER_SNAME()),
        CONSTRAINT PK_IngestionBatch PRIMARY KEY CLUSTERED (BatchId),
        CONSTRAINT UQ_IngestionBatch_SourceHash UNIQUE (SourceId, Sha256Hash),  -- evita cargar dos veces el mismo archivo
        CONSTRAINT FK_IngestionBatch_catIngestionSource FOREIGN KEY (SourceId) REFERENCES wfm.catIngestionSource (SourceId),
        CONSTRAINT CK_IngestionBatch_BatchStatus CHECK (BatchStatus IN (N'RECEIVED', N'VALIDATING', N'PROCESSED', N'PARTIAL', N'FAILED', N'REVERTED')),
        CONSTRAINT CK_IngestionBatch_Rows   CHECK (TotalRows >= 0 AND ValidRows >= 0 AND ErrorRows >= 0 AND ValidRows + ErrorRows <= TotalRows),
        CONSTRAINT CK_IngestionBatch_Period CHECK (PeriodEnd IS NULL OR PeriodStart IS NULL OR PeriodEnd >= PeriodStart)
    );
    COMMIT TRANSACTION;
END
GO

/* ---------------------------------------------------------------------------
   wfm.IngestionBatchError
   --------------------------------------------------------------------------- */
IF OBJECT_ID(N'wfm.IngestionBatchError', N'U') IS NULL
BEGIN
    BEGIN TRANSACTION;
    CREATE TABLE wfm.IngestionBatchError
    (
        BatchErrorId BIGINT         IDENTITY(1,1) NOT NULL,
        BatchId      BIGINT         NOT NULL,
        RowNumber    INT            NOT NULL,
        FieldName    NVARCHAR(100)  NULL,
        ErrorCode    NVARCHAR(50)   NOT NULL,
        ErrorMessage NVARCHAR(500)  NOT NULL,
        RawData      NVARCHAR(MAX)  NULL,
        CONSTRAINT PK_IngestionBatchError PRIMARY KEY CLUSTERED (BatchErrorId),
        CONSTRAINT FK_IngestionBatchError_IngestionBatch FOREIGN KEY (BatchId) REFERENCES wfm.IngestionBatch (BatchId) ON DELETE CASCADE
    );
    CREATE NONCLUSTERED INDEX IX_IngestionBatchError_Batch ON wfm.IngestionBatchError (BatchId, RowNumber);
    COMMIT TRANSACTION;
END
GO

/* ---------------------------------------------------------------------------
   wfm.Attendance
   --------------------------------------------------------------------------- */
IF OBJECT_ID(N'wfm.Attendance', N'U') IS NULL
BEGIN
    BEGIN TRANSACTION;
    CREATE TABLE wfm.Attendance
    (
        AttendanceId       BIGINT         IDENTITY(1,1) NOT NULL,
        EmployeeId         INT            NOT NULL,
        WorkDate           DATE           NOT NULL,
        ScheduledStart     DATETIME2(0)   NULL,
        ScheduledEnd       DATETIME2(0)   NULL,
        ActualStart        DATETIME2(0)   NULL,
        ActualEnd          DATETIME2(0)   NULL,
        ScheduledMinutes   INT            NOT NULL CONSTRAINT DF_Attendance_ScheduledMinutes DEFAULT (0),
        WorkedMinutes      INT            NOT NULL CONSTRAINT DF_Attendance_WorkedMinutes    DEFAULT (0),
        AttendanceStatus   NVARCHAR(20)   NOT NULL,
        SourceId           INT            NOT NULL,
        BatchId            BIGINT         NULL,
        IsManualAdjustment BIT            NOT NULL CONSTRAINT DF_Attendance_IsManualAdjustment DEFAULT (0),
        Notes              NVARCHAR(500)  NULL,
        CreatedAt          DATETIME2(0)   NOT NULL CONSTRAINT DF_Attendance_CreatedAt DEFAULT (SYSUTCDATETIME()),
        CreatedBy          NVARCHAR(100)  NOT NULL CONSTRAINT DF_Attendance_CreatedBy DEFAULT (SUSER_SNAME()),
        UpdatedAt          DATETIME2(0)   NULL,
        UpdatedBy          NVARCHAR(100)  NULL,
        RowVer             ROWVERSION     NOT NULL,
        CONSTRAINT PK_Attendance PRIMARY KEY CLUSTERED (AttendanceId),
        CONSTRAINT UQ_Attendance_EmployeeDay UNIQUE (EmployeeId, WorkDate),
        CONSTRAINT FK_Attendance_Employee           FOREIGN KEY (EmployeeId) REFERENCES hcm.Employee (EmployeeId),
        CONSTRAINT FK_Attendance_catIngestionSource FOREIGN KEY (SourceId)   REFERENCES wfm.catIngestionSource (SourceId),
        CONSTRAINT FK_Attendance_IngestionBatch     FOREIGN KEY (BatchId)    REFERENCES wfm.IngestionBatch (BatchId),
        CONSTRAINT CK_Attendance_Status CHECK (AttendanceStatus IN
            (N'PRESENT', N'LATE', N'ABSENT', N'LEAVE', N'VACATION', N'HOLIDAY', N'REST_DAY')),
        CONSTRAINT CK_Attendance_Schedule CHECK (ScheduledEnd IS NULL OR ScheduledStart IS NULL OR ScheduledEnd > ScheduledStart),
        CONSTRAINT CK_Attendance_Actual   CHECK (ActualEnd    IS NULL OR ActualStart    IS NULL OR ActualEnd    > ActualStart),
        CONSTRAINT CK_Attendance_Minutes  CHECK (ScheduledMinutes BETWEEN 0 AND 1440 AND WorkedMinutes BETWEEN 0 AND 1440)
    );
    CREATE NONCLUSTERED INDEX IX_Attendance_WorkDate ON wfm.Attendance (WorkDate) INCLUDE (EmployeeId, AttendanceStatus, WorkedMinutes);
    CREATE NONCLUSTERED INDEX IX_Attendance_Batch    ON wfm.Attendance (BatchId) WHERE BatchId IS NOT NULL;
    COMMIT TRANSACTION;
END
GO

/* ---------------------------------------------------------------------------
   wfm.AttendanceDowntime
   --------------------------------------------------------------------------- */
IF OBJECT_ID(N'wfm.AttendanceDowntime', N'U') IS NULL
BEGIN
    BEGIN TRANSACTION;
    CREATE TABLE wfm.AttendanceDowntime
    (
        AttendanceDowntimeId BIGINT        IDENTITY(1,1) NOT NULL,
        AttendanceId         BIGINT        NOT NULL,
        DowntimeTypeId       INT           NOT NULL,
        StartAt              DATETIME2(0)  NOT NULL,
        EndAt                DATETIME2(0)  NOT NULL,
        DurationMinutes      AS (DATEDIFF(MINUTE, StartAt, EndAt)) PERSISTED,
        ExternalCode         NVARCHAR(50)  NULL,    -- código original reportado por el WFM
        BatchId              BIGINT        NULL,
        CreatedAt            DATETIME2(0)  NOT NULL CONSTRAINT DF_AttendanceDowntime_CreatedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT PK_AttendanceDowntime PRIMARY KEY CLUSTERED (AttendanceDowntimeId),
        CONSTRAINT FK_AttendanceDowntime_Attendance      FOREIGN KEY (AttendanceId)   REFERENCES wfm.Attendance (AttendanceId) ON DELETE CASCADE,
        CONSTRAINT FK_AttendanceDowntime_catDowntimeType FOREIGN KEY (DowntimeTypeId) REFERENCES wfm.catDowntimeType (DowntimeTypeId),
        CONSTRAINT FK_AttendanceDowntime_IngestionBatch  FOREIGN KEY (BatchId)        REFERENCES wfm.IngestionBatch (BatchId),
        CONSTRAINT CK_AttendanceDowntime_Range CHECK (EndAt > StartAt)
    );
    CREATE NONCLUSTERED INDEX IX_AttendanceDowntime_Attendance ON wfm.AttendanceDowntime (AttendanceId) INCLUDE (DowntimeTypeId, DurationMinutes);
    COMMIT TRANSACTION;
END
GO
