/* =============================================================================
   Metamorph ERP - 020: HCM  (Empleados + Expediente Digital)
   -----------------------------------------------------------------------------
   hcm.Employee              <- "Empleados"
   hcm.DigitalFile           <- "ExpedientesDigitales" (1:1 con Employee)
   hcm.catDocumentType       <- tipos de documento del expediente
   hcm.DigitalFileDocument   <- documentos versionados del expediente
                                (el binario vive en almacenamiento de archivos;
                                 la BD guarda metadatos + hash SHA-256)
   ============================================================================= */
SET NOCOUNT ON;
SET XACT_ABORT ON;
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

/* ---------------------------------------------------------------------------
   hcm.Employee
   --------------------------------------------------------------------------- */
IF OBJECT_ID(N'hcm.Employee', N'U') IS NULL
BEGIN
    BEGIN TRANSACTION;
    CREATE TABLE hcm.Employee
    (
        EmployeeId        INT            IDENTITY(1,1) NOT NULL,
        EmployeeCode      NVARCHAR(40)   NOT NULL,   -- core.usp_GenerateEmployeeCode
        CountryId         INT            NOT NULL,
        FirstName         NVARCHAR(100)  NOT NULL,
        MiddleName        NVARCHAR(100)  NULL,
        LastName          NVARCHAR(100)  NOT NULL,
        SecondLastName    NVARCHAR(100)  NULL,
        NationalIdType    NVARCHAR(20)   NOT NULL,   -- DUI, DPI, CURP, CC, PASSPORT...
        NationalIdNumber  NVARCHAR(30)   NOT NULL,
        BirthDate         DATE           NOT NULL,
        Gender            CHAR(1)        NULL,
        WorkEmail         NVARCHAR(254)  NULL,
        PersonalEmail     NVARCHAR(254)  NULL,
        PhoneNumber       NVARCHAR(30)   NULL,
        HireDate          DATE           NOT NULL,
        TerminationDate   DATE           NULL,
        EmploymentStatus  NVARCHAR(20)   NOT NULL CONSTRAINT DF_Employee_EmploymentStatus DEFAULT (N'ACTIVE'),
        BaseSalary        DECIMAL(18,2)  NOT NULL,   -- en la moneda del país (catCountry.CurrencyCode)
        PayFrequency      NVARCHAR(15)   NOT NULL CONSTRAINT DF_Employee_PayFrequency DEFAULT (N'MONTHLY'),
        CreatedAt         DATETIME2(0)   NOT NULL CONSTRAINT DF_Employee_CreatedAt DEFAULT (SYSUTCDATETIME()),
        CreatedBy         NVARCHAR(100)  NOT NULL CONSTRAINT DF_Employee_CreatedBy DEFAULT (SUSER_SNAME()),
        UpdatedAt         DATETIME2(0)   NULL,
        UpdatedBy         NVARCHAR(100)  NULL,
        RowVer            ROWVERSION     NOT NULL,   -- concurrencia optimista
        CONSTRAINT PK_Employee PRIMARY KEY CLUSTERED (EmployeeId),
        CONSTRAINT UQ_Employee_EmployeeCode UNIQUE (EmployeeCode),
        CONSTRAINT UQ_Employee_NationalId UNIQUE (CountryId, NationalIdType, NationalIdNumber),
        CONSTRAINT FK_Employee_catCountry FOREIGN KEY (CountryId) REFERENCES core.catCountry (CountryId),
        CONSTRAINT CK_Employee_EmployeeCode_Format
            CHECK (EmployeeCode LIKE N'%_-[0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]-[0-9]'),
        CONSTRAINT CK_Employee_Gender           CHECK (Gender IN ('M', 'F', 'X')),
        CONSTRAINT CK_Employee_EmploymentStatus CHECK (EmploymentStatus IN (N'ACTIVE', N'INACTIVE', N'TERMINATED')),
        CONSTRAINT CK_Employee_PayFrequency     CHECK (PayFrequency IN (N'MONTHLY', N'BIWEEKLY', N'WEEKLY')),
        CONSTRAINT CK_Employee_BaseSalary       CHECK (BaseSalary >= 0),
        CONSTRAINT CK_Employee_Dates            CHECK (TerminationDate IS NULL OR TerminationDate >= HireDate),
        CONSTRAINT CK_Employee_Termination
            CHECK ((EmploymentStatus = N'TERMINATED' AND TerminationDate IS NOT NULL)
                OR (EmploymentStatus <> N'TERMINATED'))
    );

    CREATE NONCLUSTERED INDEX IX_Employee_Country_Status ON hcm.Employee (CountryId, EmploymentStatus)
        INCLUDE (EmployeeCode, FirstName, LastName);
    CREATE NONCLUSTERED INDEX IX_Employee_LastName ON hcm.Employee (LastName, FirstName);
    COMMIT TRANSACTION;
END
GO

/* ---------------------------------------------------------------------------
   hcm.DigitalFile  (Expediente Digital, uno por empleado)
   --------------------------------------------------------------------------- */
IF OBJECT_ID(N'hcm.DigitalFile', N'U') IS NULL
BEGIN
    BEGIN TRANSACTION;
    CREATE TABLE hcm.DigitalFile
    (
        DigitalFileId  INT            IDENTITY(1,1) NOT NULL,
        EmployeeId     INT            NOT NULL,
        FileStatus     NVARCHAR(20)   NOT NULL CONSTRAINT DF_DigitalFile_FileStatus DEFAULT (N'OPEN'),
        OpenedAt       DATETIME2(0)   NOT NULL CONSTRAINT DF_DigitalFile_OpenedAt  DEFAULT (SYSUTCDATETIME()),
        ClosedAt       DATETIME2(0)   NULL,
        Notes          NVARCHAR(1000) NULL,
        CreatedAt      DATETIME2(0)   NOT NULL CONSTRAINT DF_DigitalFile_CreatedAt DEFAULT (SYSUTCDATETIME()),
        CreatedBy      NVARCHAR(100)  NOT NULL CONSTRAINT DF_DigitalFile_CreatedBy DEFAULT (SUSER_SNAME()),
        UpdatedAt      DATETIME2(0)   NULL,
        UpdatedBy      NVARCHAR(100)  NULL,
        CONSTRAINT PK_DigitalFile PRIMARY KEY CLUSTERED (DigitalFileId),
        CONSTRAINT UQ_DigitalFile_Employee UNIQUE (EmployeeId),
        CONSTRAINT FK_DigitalFile_Employee FOREIGN KEY (EmployeeId) REFERENCES hcm.Employee (EmployeeId),
        CONSTRAINT CK_DigitalFile_FileStatus CHECK (FileStatus IN (N'OPEN', N'ARCHIVED')),
        CONSTRAINT CK_DigitalFile_Dates      CHECK (ClosedAt IS NULL OR ClosedAt >= OpenedAt)
    );
    COMMIT TRANSACTION;
END
GO

/* ---------------------------------------------------------------------------
   hcm.catDocumentType
   --------------------------------------------------------------------------- */
IF OBJECT_ID(N'hcm.catDocumentType', N'U') IS NULL
BEGIN
    BEGIN TRANSACTION;
    CREATE TABLE hcm.catDocumentType
    (
        DocumentTypeId  INT            IDENTITY(1,1) NOT NULL,
        Code            NVARCHAR(30)   NOT NULL,
        Name            NVARCHAR(150)  NOT NULL,
        CountryId       INT            NULL,          -- NULL = aplica a todos los países
        IsMandatory     BIT            NOT NULL CONSTRAINT DF_catDocumentType_IsMandatory    DEFAULT (0),
        RequiresExpiry  BIT            NOT NULL CONSTRAINT DF_catDocumentType_RequiresExpiry DEFAULT (0),
        RetentionYears  SMALLINT       NULL,
        IsActive        BIT            NOT NULL CONSTRAINT DF_catDocumentType_IsActive       DEFAULT (1),
        CreatedAt       DATETIME2(0)   NOT NULL CONSTRAINT DF_catDocumentType_CreatedAt      DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT PK_catDocumentType PRIMARY KEY CLUSTERED (DocumentTypeId),
        CONSTRAINT UQ_catDocumentType_Code UNIQUE (Code),
        CONSTRAINT FK_catDocumentType_catCountry FOREIGN KEY (CountryId) REFERENCES core.catCountry (CountryId),
        CONSTRAINT CK_catDocumentType_RetentionYears CHECK (RetentionYears IS NULL OR RetentionYears > 0)
    );
    COMMIT TRANSACTION;
END
GO

/* ---------------------------------------------------------------------------
   hcm.DigitalFileDocument  (versionado; solo una versión vigente por tipo)
   --------------------------------------------------------------------------- */
IF OBJECT_ID(N'hcm.DigitalFileDocument', N'U') IS NULL
BEGIN
    BEGIN TRANSACTION;
    CREATE TABLE hcm.DigitalFileDocument
    (
        DocumentId      BIGINT         IDENTITY(1,1) NOT NULL,
        DigitalFileId   INT            NOT NULL,
        DocumentTypeId  INT            NOT NULL,
        VersionNumber   INT            NOT NULL CONSTRAINT DF_DigitalFileDocument_VersionNumber DEFAULT (1),
        IsCurrent       BIT            NOT NULL CONSTRAINT DF_DigitalFileDocument_IsCurrent     DEFAULT (1),
        OriginalName    NVARCHAR(255)  NOT NULL,
        StoragePath     NVARCHAR(500)  NOT NULL,
        MimeType        NVARCHAR(100)  NOT NULL,
        SizeBytes       BIGINT         NOT NULL,
        Sha256Hash      CHAR(64)       NOT NULL,
        IssueDate       DATE           NULL,
        ExpiryDate      DATE           NULL,
        UploadedAt      DATETIME2(0)   NOT NULL CONSTRAINT DF_DigitalFileDocument_UploadedAt DEFAULT (SYSUTCDATETIME()),
        UploadedBy      NVARCHAR(100)  NOT NULL CONSTRAINT DF_DigitalFileDocument_UploadedBy DEFAULT (SUSER_SNAME()),
        CONSTRAINT PK_DigitalFileDocument PRIMARY KEY CLUSTERED (DocumentId),
        CONSTRAINT UQ_DigitalFileDocument_Version UNIQUE (DigitalFileId, DocumentTypeId, VersionNumber),
        CONSTRAINT FK_DigitalFileDocument_DigitalFile     FOREIGN KEY (DigitalFileId)  REFERENCES hcm.DigitalFile (DigitalFileId) ON DELETE CASCADE,
        CONSTRAINT FK_DigitalFileDocument_catDocumentType FOREIGN KEY (DocumentTypeId) REFERENCES hcm.catDocumentType (DocumentTypeId),
        CONSTRAINT CK_DigitalFileDocument_SizeBytes  CHECK (SizeBytes > 0),
        CONSTRAINT CK_DigitalFileDocument_Version    CHECK (VersionNumber > 0),
        CONSTRAINT CK_DigitalFileDocument_Sha256     CHECK (Sha256Hash COLLATE Latin1_General_BIN NOT LIKE '%[^0-9a-f]%' AND LEN(Sha256Hash) = 64),
        CONSTRAINT CK_DigitalFileDocument_Dates      CHECK (ExpiryDate IS NULL OR IssueDate IS NULL OR ExpiryDate >= IssueDate)
    );

    CREATE UNIQUE NONCLUSTERED INDEX UIX_DigitalFileDocument_Current
        ON hcm.DigitalFileDocument (DigitalFileId, DocumentTypeId)
        WHERE IsCurrent = 1;

    CREATE NONCLUSTERED INDEX IX_DigitalFileDocument_Expiry
        ON hcm.DigitalFileDocument (ExpiryDate)
        INCLUDE (DigitalFileId, DocumentTypeId)
        WHERE IsCurrent = 1 AND ExpiryDate IS NOT NULL;
    COMMIT TRANSACTION;
END
GO
