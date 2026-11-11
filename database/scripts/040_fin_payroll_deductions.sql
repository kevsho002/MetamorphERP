/* =============================================================================
   Metamorph ERP - 040: FIN (Planillas + retenciones legales configurables)
   -----------------------------------------------------------------------------
   Retenciones configurables por país y con vigencia (EffectiveStart/EndDate):
     fin.catDeductionType   regla: PERCENTAGE | BRACKET | FIXED, tope de base,
                            parte (EMPLOYEE/EMPLOYER), orden de cálculo y si
                            reduce la base gravable (p.ej. ISSS/AFP antes de Renta)
     fin.DeductionBracket   tramos por frecuencia de pago (tabla de ISR/Renta)
   Planilla:
     fin.Payroll            <- "Planillas" (encabezado por país/frecuencia/periodo)
     fin.PayrollDetail      una línea por empleado
     fin.PayrollDeduction   retención aplicada (snapshot de base y tasa usadas)
   ============================================================================= */
SET NOCOUNT ON;
SET XACT_ABORT ON;
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

/* ---------------------------------------------------------------------------
   fin.catDeductionType
   --------------------------------------------------------------------------- */
IF OBJECT_ID(N'fin.catDeductionType', N'U') IS NULL
BEGIN
    BEGIN TRANSACTION;
    CREATE TABLE fin.catDeductionType
    (
        DeductionTypeId     INT            IDENTITY(1,1) NOT NULL,
        CountryId           INT            NOT NULL,
        Code                NVARCHAR(30)   NOT NULL,
        Name                NVARCHAR(150)  NOT NULL,
        Category            NVARCHAR(20)   NOT NULL,
        Party               NVARCHAR(10)   NOT NULL,
        CalculationMethod   NVARCHAR(12)   NOT NULL,
        Rate                DECIMAL(9,6)   NULL,     -- 0.030000 = 3 %
        FixedAmount         DECIMAL(18,2)  NULL,
        BaseCap             DECIMAL(18,2)  NULL,     -- tope de la base de cálculo
        ReducesTaxableBase  BIT            NOT NULL CONSTRAINT DF_catDeductionType_ReducesTaxableBase DEFAULT (0),
        CalculationOrder    SMALLINT       NOT NULL CONSTRAINT DF_catDeductionType_CalculationOrder   DEFAULT (100),
        EffectiveStartDate  DATE           NOT NULL,
        EffectiveEndDate    DATE           NULL,
        LegalReference      NVARCHAR(300)  NULL,
        IsActive            BIT            NOT NULL CONSTRAINT DF_catDeductionType_IsActive  DEFAULT (1),
        CreatedAt           DATETIME2(0)   NOT NULL CONSTRAINT DF_catDeductionType_CreatedAt DEFAULT (SYSUTCDATETIME()),
        CreatedBy           NVARCHAR(100)  NOT NULL CONSTRAINT DF_catDeductionType_CreatedBy DEFAULT (SUSER_SNAME()),
        CONSTRAINT PK_catDeductionType PRIMARY KEY CLUSTERED (DeductionTypeId),
        CONSTRAINT UQ_catDeductionType_Version UNIQUE (CountryId, Code, EffectiveStartDate),
        CONSTRAINT FK_catDeductionType_catCountry FOREIGN KEY (CountryId) REFERENCES core.catCountry (CountryId),
        CONSTRAINT CK_catDeductionType_Category CHECK (Category IN (N'SOCIAL_SECURITY', N'PENSION', N'INCOME_TAX', N'OTHER')),
        CONSTRAINT CK_catDeductionType_Party    CHECK (Party IN (N'EMPLOYEE', N'EMPLOYER')),
        CONSTRAINT CK_catDeductionType_Method   CHECK (CalculationMethod IN (N'PERCENTAGE', N'BRACKET', N'FIXED')),
        CONSTRAINT CK_catDeductionType_Rate     CHECK (Rate IS NULL OR Rate BETWEEN 0 AND 1),
        CONSTRAINT CK_catDeductionType_Amounts  CHECK ((FixedAmount IS NULL OR FixedAmount >= 0) AND (BaseCap IS NULL OR BaseCap > 0)),
        CONSTRAINT CK_catDeductionType_MethodParams CHECK (
               (CalculationMethod = N'PERCENTAGE' AND Rate IS NOT NULL)
            OR (CalculationMethod = N'FIXED'      AND FixedAmount IS NOT NULL)
            OR (CalculationMethod = N'BRACKET')),
        CONSTRAINT CK_catDeductionType_Dates CHECK (EffectiveEndDate IS NULL OR EffectiveEndDate >= EffectiveStartDate)
    );
    COMMIT TRANSACTION;
END
GO

/* ---------------------------------------------------------------------------
   fin.DeductionBracket
   Monto = FixedFee + (Base - ExcessOver) * Rate, para LowerBound <= Base <= UpperBound
   --------------------------------------------------------------------------- */
IF OBJECT_ID(N'fin.DeductionBracket', N'U') IS NULL
BEGIN
    BEGIN TRANSACTION;
    CREATE TABLE fin.DeductionBracket
    (
        DeductionBracketId INT            IDENTITY(1,1) NOT NULL,
        DeductionTypeId    INT            NOT NULL,
        PayFrequency       NVARCHAR(15)   NOT NULL,
        LowerBound         DECIMAL(18,2)  NOT NULL,
        UpperBound         DECIMAL(18,2)  NULL,      -- NULL = en adelante
        Rate               DECIMAL(9,6)   NOT NULL,
        FixedFee           DECIMAL(18,2)  NOT NULL CONSTRAINT DF_DeductionBracket_FixedFee   DEFAULT (0),
        ExcessOver         DECIMAL(18,2)  NOT NULL CONSTRAINT DF_DeductionBracket_ExcessOver DEFAULT (0),
        CONSTRAINT PK_DeductionBracket PRIMARY KEY CLUSTERED (DeductionBracketId),
        CONSTRAINT UQ_DeductionBracket_Lower UNIQUE (DeductionTypeId, PayFrequency, LowerBound),
        CONSTRAINT FK_DeductionBracket_catDeductionType FOREIGN KEY (DeductionTypeId) REFERENCES fin.catDeductionType (DeductionTypeId) ON DELETE CASCADE,
        CONSTRAINT CK_DeductionBracket_PayFrequency CHECK (PayFrequency IN (N'MONTHLY', N'BIWEEKLY', N'WEEKLY')),
        CONSTRAINT CK_DeductionBracket_Bounds CHECK (LowerBound >= 0 AND (UpperBound IS NULL OR UpperBound > LowerBound)),
        CONSTRAINT CK_DeductionBracket_Rate   CHECK (Rate BETWEEN 0 AND 1 AND FixedFee >= 0 AND ExcessOver >= 0)
    );
    COMMIT TRANSACTION;
END
GO

/* ---------------------------------------------------------------------------
   fin.Payroll
   --------------------------------------------------------------------------- */
IF OBJECT_ID(N'fin.Payroll', N'U') IS NULL
BEGIN
    BEGIN TRANSACTION;
    CREATE TABLE fin.Payroll
    (
        PayrollId             INT            IDENTITY(1,1) NOT NULL,
        PayrollCode           NVARCHAR(40)   NOT NULL,
        CountryId             INT            NOT NULL,
        PayFrequency          NVARCHAR(15)   NOT NULL,
        PeriodStart           DATE           NOT NULL,
        PeriodEnd             DATE           NOT NULL,
        PaymentDate           DATE           NOT NULL,
        PayrollStatus         NVARCHAR(15)   NOT NULL CONSTRAINT DF_Payroll_PayrollStatus DEFAULT (N'DRAFT'),
        CurrencyCode          CHAR(3)        NOT NULL,
        TotalGross            DECIMAL(18,2)  NOT NULL CONSTRAINT DF_Payroll_TotalGross       DEFAULT (0),
        TotalDeductions       DECIMAL(18,2)  NOT NULL CONSTRAINT DF_Payroll_TotalDeductions  DEFAULT (0),
        TotalNet              DECIMAL(18,2)  NOT NULL CONSTRAINT DF_Payroll_TotalNet         DEFAULT (0),
        TotalEmployerCost     DECIMAL(18,2)  NOT NULL CONSTRAINT DF_Payroll_TotalEmployerCost DEFAULT (0),
        ApprovedAt            DATETIME2(0)   NULL,
        ApprovedBy            NVARCHAR(100)  NULL,
        CreatedAt             DATETIME2(0)   NOT NULL CONSTRAINT DF_Payroll_CreatedAt DEFAULT (SYSUTCDATETIME()),
        CreatedBy             NVARCHAR(100)  NOT NULL CONSTRAINT DF_Payroll_CreatedBy DEFAULT (SUSER_SNAME()),
        UpdatedAt             DATETIME2(0)   NULL,
        UpdatedBy             NVARCHAR(100)  NULL,
        RowVer                ROWVERSION     NOT NULL,
        CONSTRAINT PK_Payroll PRIMARY KEY CLUSTERED (PayrollId),
        CONSTRAINT UQ_Payroll_PayrollCode UNIQUE (PayrollCode),
        CONSTRAINT UQ_Payroll_Period UNIQUE (CountryId, PayFrequency, PeriodStart),
        CONSTRAINT FK_Payroll_catCountry FOREIGN KEY (CountryId) REFERENCES core.catCountry (CountryId),
        CONSTRAINT CK_Payroll_PayFrequency CHECK (PayFrequency IN (N'MONTHLY', N'BIWEEKLY', N'WEEKLY')),
        CONSTRAINT CK_Payroll_Status CHECK (PayrollStatus IN (N'DRAFT', N'CALCULATED', N'APPROVED', N'PAID', N'CANCELLED')),
        CONSTRAINT CK_Payroll_Period CHECK (PeriodEnd >= PeriodStart),
        CONSTRAINT CK_Payroll_Approval CHECK (PayrollStatus NOT IN (N'APPROVED', N'PAID') OR ApprovedAt IS NOT NULL)
    );
    COMMIT TRANSACTION;
END
GO

/* ---------------------------------------------------------------------------
   fin.PayrollDetail
   --------------------------------------------------------------------------- */
IF OBJECT_ID(N'fin.PayrollDetail', N'U') IS NULL
BEGIN
    BEGIN TRANSACTION;
    CREATE TABLE fin.PayrollDetail
    (
        PayrollDetailId        BIGINT         IDENTITY(1,1) NOT NULL,
        PayrollId              INT            NOT NULL,
        EmployeeId             INT            NOT NULL,
        BaseSalary             DECIMAL(18,2)  NOT NULL,   -- snapshot del salario al calcular
        PaidDays               DECIMAL(5,2)   NOT NULL,
        WorkedMinutes          INT            NOT NULL CONSTRAINT DF_PayrollDetail_WorkedMinutes  DEFAULT (0),
        OvertimeAmount         DECIMAL(18,2)  NOT NULL CONSTRAINT DF_PayrollDetail_OvertimeAmount DEFAULT (0),
        OtherEarnings          DECIMAL(18,2)  NOT NULL CONSTRAINT DF_PayrollDetail_OtherEarnings  DEFAULT (0),
        GrossPay               DECIMAL(18,2)  NOT NULL,
        TaxableBase            DECIMAL(18,2)  NOT NULL,
        TotalDeductions        DECIMAL(18,2)  NOT NULL,
        NetPay                 DECIMAL(18,2)  NOT NULL,
        EmployerContributions  DECIMAL(18,2)  NOT NULL CONSTRAINT DF_PayrollDetail_EmployerContributions DEFAULT (0),
        CONSTRAINT PK_PayrollDetail PRIMARY KEY CLUSTERED (PayrollDetailId),
        CONSTRAINT UQ_PayrollDetail_Employee UNIQUE (PayrollId, EmployeeId),
        CONSTRAINT FK_PayrollDetail_Payroll  FOREIGN KEY (PayrollId)  REFERENCES fin.Payroll (PayrollId) ON DELETE CASCADE,
        CONSTRAINT FK_PayrollDetail_Employee FOREIGN KEY (EmployeeId) REFERENCES hcm.Employee (EmployeeId),
        CONSTRAINT CK_PayrollDetail_Amounts CHECK (
            BaseSalary >= 0 AND PaidDays >= 0 AND WorkedMinutes >= 0 AND OvertimeAmount >= 0 AND OtherEarnings >= 0
            AND GrossPay >= 0 AND TaxableBase >= 0 AND TotalDeductions >= 0 AND EmployerContributions >= 0),
        CONSTRAINT CK_PayrollDetail_Net CHECK (NetPay = GrossPay - TotalDeductions)
    );
    CREATE NONCLUSTERED INDEX IX_PayrollDetail_Employee ON fin.PayrollDetail (EmployeeId) INCLUDE (PayrollId, NetPay);
    COMMIT TRANSACTION;
END
GO

/* ---------------------------------------------------------------------------
   fin.PayrollDeduction
   --------------------------------------------------------------------------- */
IF OBJECT_ID(N'fin.PayrollDeduction', N'U') IS NULL
BEGIN
    BEGIN TRANSACTION;
    CREATE TABLE fin.PayrollDeduction
    (
        PayrollDeductionId BIGINT         IDENTITY(1,1) NOT NULL,
        PayrollDetailId    BIGINT         NOT NULL,
        DeductionTypeId    INT            NOT NULL,
        Party              NVARCHAR(10)   NOT NULL,   -- snapshot (EMPLOYEE/EMPLOYER)
        CalculationBase    DECIMAL(18,2)  NOT NULL,
        AppliedRate        DECIMAL(9,6)   NULL,
        Amount             DECIMAL(18,2)  NOT NULL,
        CONSTRAINT PK_PayrollDeduction PRIMARY KEY CLUSTERED (PayrollDeductionId),
        CONSTRAINT UQ_PayrollDeduction_Type UNIQUE (PayrollDetailId, DeductionTypeId),
        CONSTRAINT FK_PayrollDeduction_PayrollDetail    FOREIGN KEY (PayrollDetailId) REFERENCES fin.PayrollDetail (PayrollDetailId) ON DELETE CASCADE,
        CONSTRAINT FK_PayrollDeduction_catDeductionType FOREIGN KEY (DeductionTypeId) REFERENCES fin.catDeductionType (DeductionTypeId),
        CONSTRAINT CK_PayrollDeduction_Party   CHECK (Party IN (N'EMPLOYEE', N'EMPLOYER')),
        CONSTRAINT CK_PayrollDeduction_Amounts CHECK (CalculationBase >= 0 AND Amount >= 0 AND (AppliedRate IS NULL OR AppliedRate BETWEEN 0 AND 1))
    );
    COMMIT TRANSACTION;
END
GO
