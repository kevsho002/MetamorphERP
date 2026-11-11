/* =============================================================================
   Metamorph ERP - 050: Centros de costo
   -----------------------------------------------------------------------------
   Idempotente. Catálogo por país; lo referencia el usuario del sistema
   (dbo.accounts_customuser.cost_center_id, tabla administrada por Django) y,
   en fases posteriores, la imputación de planilla.
   ============================================================================= */
SET NOCOUNT ON;
SET XACT_ABORT ON;
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

IF OBJECT_ID(N'core.catCostCenter', N'U') IS NULL
BEGIN
    BEGIN TRANSACTION;
    CREATE TABLE core.catCostCenter
    (
        CostCenterId       INT            IDENTITY(1,1) NOT NULL,
        CountryId          INT            NOT NULL,
        Code               NVARCHAR(20)   NOT NULL,
        Name               NVARCHAR(150)  NOT NULL,
        ParentCostCenterId INT            NULL,
        EffectiveStartDate DATE           NOT NULL CONSTRAINT DF_catCostCenter_EffectiveStartDate DEFAULT (CAST(SYSUTCDATETIME() AS DATE)),
        EffectiveEndDate   DATE           NULL,
        IsActive           BIT            NOT NULL CONSTRAINT DF_catCostCenter_IsActive  DEFAULT (1),
        CreatedAt          DATETIME2(0)   NOT NULL CONSTRAINT DF_catCostCenter_CreatedAt DEFAULT (SYSUTCDATETIME()),
        CreatedBy          NVARCHAR(100)  NOT NULL CONSTRAINT DF_catCostCenter_CreatedBy DEFAULT (SUSER_SNAME()),
        CONSTRAINT PK_catCostCenter PRIMARY KEY CLUSTERED (CostCenterId),
        CONSTRAINT UQ_catCostCenter_Code UNIQUE (Code),
        CONSTRAINT FK_catCostCenter_Country FOREIGN KEY (CountryId) REFERENCES core.catCountry (CountryId),
        CONSTRAINT FK_catCostCenter_Parent  FOREIGN KEY (ParentCostCenterId) REFERENCES core.catCostCenter (CostCenterId),
        CONSTRAINT CK_catCostCenter_Code    CHECK (Code NOT LIKE N'%[^-A-Z0-9_]%' COLLATE Latin1_General_BIN AND LEN(Code) >= 2),
        CONSTRAINT CK_catCostCenter_Dates   CHECK (EffectiveEndDate IS NULL OR EffectiveEndDate >= EffectiveStartDate),
        CONSTRAINT CK_catCostCenter_NotSelfParent CHECK (ParentCostCenterId IS NULL OR ParentCostCenterId <> CostCenterId)
    );
    CREATE NONCLUSTERED INDEX IX_catCostCenter_Country ON core.catCostCenter (CountryId) INCLUDE (Code, Name, IsActive);
    COMMIT TRANSACTION;
END
GO
