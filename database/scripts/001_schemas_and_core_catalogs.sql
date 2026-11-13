/* =============================================================================
   Metamorph ERP - 001: Esquemas base y catálogos núcleo
   -----------------------------------------------------------------------------
   Idempotente: puede ejecutarse N veces sin efectos secundarios.
   - Crea los esquemas de dominio si no existen:
       core -> catálogos transversales y secuencias
       hcm  -> capital humano (empleados, expediente digital)
       fin  -> planillas y retenciones legales
   - core.catCountry: replica EXACTA de la tabla ya existente en la BD de
     desarrollo (creada 2026-11-09). Solo se crea si no existe; nunca se altera.
   ============================================================================= */
SET NOCOUNT ON;
SET XACT_ABORT ON;
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

IF SCHEMA_ID(N'core') IS NULL EXEC (N'CREATE SCHEMA core AUTHORIZATION dbo;');
IF SCHEMA_ID(N'hcm')  IS NULL EXEC (N'CREATE SCHEMA hcm  AUTHORIZATION dbo;');
IF SCHEMA_ID(N'fin')  IS NULL EXEC (N'CREATE SCHEMA fin  AUTHORIZATION dbo;');
GO

/* ---------------------------------------------------------------------------
   core.catCountry  (catálogo de países; IdPrefix alimenta el ID corporativo)
   --------------------------------------------------------------------------- */
IF OBJECT_ID(N'core.catCountry', N'U') IS NULL
BEGIN
    BEGIN TRANSACTION;
    CREATE TABLE core.catCountry
    (
        CountryId          INT            IDENTITY(1,1) NOT NULL,
        CountryCode        CHAR(2)        NOT NULL,
        CountryName        NVARCHAR(200)  NOT NULL,
        CurrencyCode       CHAR(3)        NOT NULL,
        IdPrefix           NVARCHAR(20)   NOT NULL,
        EffectiveStartDate DATE           NOT NULL,
        EffectiveEndDate   DATE           NULL,
        IsActive           BIT            NOT NULL CONSTRAINT DF_catCountry_IsActive  DEFAULT (1),
        CreatedAt          DATETIME2(7)   NOT NULL CONSTRAINT DF_catCountry_CreatedAt DEFAULT (GETDATE()),
        CONSTRAINT PK_catCountry PRIMARY KEY CLUSTERED (CountryId)
    );
    CREATE UNIQUE NONCLUSTERED INDEX UIX_catCountry_ActiveCountryCode ON core.catCountry (CountryCode);
    COMMIT TRANSACTION;
END
GO

/* Semilla mínima (solo inserta los países que falten) */
INSERT INTO core.catCountry (CountryCode, CountryName, CurrencyCode, IdPrefix, EffectiveStartDate)
SELECT s.CountryCode, s.CountryName, s.CurrencyCode, s.IdPrefix, s.EffectiveStartDate
FROM (VALUES
        ('SV', N'El Salvador', 'USD', N'SV', CAST('2026-01-01' AS DATE)),
        ('GT', N'Guatemala',   'GTQ', N'GT', CAST('2026-01-01' AS DATE)),
        ('MX', N'México',      'MXN', N'MX', CAST('2026-01-01' AS DATE)),
        ('CO', N'Colombia',    'COP', N'CO', CAST('2026-01-01' AS DATE))
     ) AS s (CountryCode, CountryName, CurrencyCode, IdPrefix, EffectiveStartDate)
WHERE NOT EXISTS (SELECT 1 FROM core.catCountry c WHERE c.CountryCode = s.CountryCode);
GO
