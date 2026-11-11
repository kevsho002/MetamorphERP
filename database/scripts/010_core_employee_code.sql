/* =============================================================================
   Metamorph ERP - 010: Generación algorítmica del ID corporativo de empleado
   -----------------------------------------------------------------------------
   Formato:   {IdPrefix}-{AAAA}-{NNNNNN}-{D}
   Ejemplo:   SV-2026-000123-7
     IdPrefix : core.catCountry.IdPrefix del país de contratación
     AAAA     : año de la fecha de ingreso (la secuencia se reinicia cada año)
     NNNNNN   : correlativo por país + año (máx. 999 999)
     D        : dígito verificador Luhn (mod 10) calculado sobre
                IdPrefix + AAAA + NNNNNN, con letras convertidas a número
                (A=10 ... Z=35, igual que IBAN) para que un error en el
                prefijo también se detecte.

   Concurrencia / ACID:
     core.usp_GenerateEmployeeCode reserva el correlativo con UPDLOCK+HOLDLOCK.
     Si se invoca dentro de una transacción del llamador (caso del backend),
     el bloqueo se mantiene hasta su COMMIT/ROLLBACK: un ROLLBACK de la
     creación del empleado devuelve el correlativo => no hay huecos.
     El algoritmo equivalente en Python vive en
     backend/app/modules/hcm/services/employee_code.py (debe mantenerse igual).
   ============================================================================= */
SET NOCOUNT ON;
SET XACT_ABORT ON;
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

IF OBJECT_ID(N'core.EmployeeCodeSequence', N'U') IS NULL
BEGIN
    BEGIN TRANSACTION;
    CREATE TABLE core.EmployeeCodeSequence
    (
        CountryId    INT          NOT NULL,
        SequenceYear SMALLINT     NOT NULL,
        LastValue    INT          NOT NULL CONSTRAINT DF_EmployeeCodeSequence_LastValue DEFAULT (0),
        UpdatedAt    DATETIME2(0) NOT NULL CONSTRAINT DF_EmployeeCodeSequence_UpdatedAt DEFAULT (SYSUTCDATETIME()),
        CONSTRAINT PK_EmployeeCodeSequence PRIMARY KEY CLUSTERED (CountryId, SequenceYear),
        CONSTRAINT FK_EmployeeCodeSequence_catCountry FOREIGN KEY (CountryId) REFERENCES core.catCountry (CountryId),
        CONSTRAINT CK_EmployeeCodeSequence_LastValue CHECK (LastValue BETWEEN 0 AND 999999),
        CONSTRAINT CK_EmployeeCodeSequence_Year      CHECK (SequenceYear BETWEEN 1900 AND 9999)
    );
    COMMIT TRANSACTION;
END
GO

/* Dígito verificador Luhn sobre un payload alfanumérico (solo ASCII A-Z / 0-9). */
CREATE OR ALTER FUNCTION core.fn_ComputeCheckDigit (@Payload NVARCHAR(100))
RETURNS TINYINT
WITH SCHEMABINDING
AS
BEGIN
    DECLARE @Digits VARCHAR(300) = '',
            @i      INT = 1,
            @c      NCHAR(1),
            @d      INT,
            @Sum    INT = 0,
            @Pos    INT = 0;

    SET @Payload = UPPER(@Payload);

    WHILE @i <= LEN(@Payload)
    BEGIN
        SET @c = SUBSTRING(@Payload, @i, 1);
        IF @c COLLATE Latin1_General_BIN LIKE N'[0-9]'
            SET @Digits += CAST(@c AS VARCHAR(1));
        ELSE IF @c COLLATE Latin1_General_BIN LIKE N'[A-Z]'
            SET @Digits += CAST(UNICODE(@c) - 55 AS VARCHAR(2));   -- 'A'(65) -> 10
        SET @i += 1;
    END;

    -- Luhn: desde la derecha se duplica la posición 0, 2, 4... (el dígito
    -- verificador se agrega después, por eso el último dígito del payload se duplica).
    SET @i = LEN(@Digits);
    WHILE @i >= 1
    BEGIN
        SET @d = CAST(SUBSTRING(@Digits, @i, 1) AS INT);
        IF @Pos % 2 = 0
        BEGIN
            SET @d *= 2;
            IF @d > 9 SET @d -= 9;
        END;
        SET @Sum += @d;
        SET @Pos += 1;
        SET @i   -= 1;
    END;

    RETURN CAST((10 - @Sum % 10) % 10 AS TINYINT);
END;
GO

CREATE OR ALTER PROCEDURE core.usp_GenerateEmployeeCode
    @CountryId INT,
    @HireDate  DATE = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @EffectiveDate DATE = COALESCE(@HireDate, CAST(SYSUTCDATETIME() AS DATE));
    DECLARE @Year     SMALLINT = YEAR(@EffectiveDate),
            @Prefix   NVARCHAR(20),
            @Next     INT,
            @OwnTran  BIT = 0,
            @Seq      NVARCHAR(6),
            @Code     NVARCHAR(40);

    SELECT @Prefix = UPPER(LTRIM(RTRIM(c.IdPrefix)))
    FROM core.catCountry AS c
    WHERE c.CountryId = @CountryId
      AND c.IsActive = 1
      AND c.EffectiveStartDate <= @EffectiveDate
      AND (c.EffectiveEndDate IS NULL OR c.EffectiveEndDate >= @EffectiveDate);

    IF @Prefix IS NULL
        THROW 50001, N'País inexistente, inactivo o fuera de vigencia para la fecha de ingreso.', 1;

    IF @@TRANCOUNT = 0
    BEGIN
        BEGIN TRANSACTION;
        SET @OwnTran = 1;
    END;

    -- HOLDLOCK = rango serializable: aun si la fila no existe, dos sesiones
    -- concurrentes no pueden insertar la misma (País, Año).
    UPDATE core.EmployeeCodeSequence WITH (UPDLOCK, HOLDLOCK)
       SET @Next = LastValue = LastValue + 1,
           UpdatedAt = SYSUTCDATETIME()
     WHERE CountryId = @CountryId
       AND SequenceYear = @Year;

    IF @@ROWCOUNT = 0
    BEGIN
        INSERT INTO core.EmployeeCodeSequence (CountryId, SequenceYear, LastValue)
        VALUES (@CountryId, @Year, 1);
        SET @Next = 1;
    END;

    IF @OwnTran = 1 COMMIT TRANSACTION;

    SET @Seq  = RIGHT(N'000000' + CAST(@Next AS NVARCHAR(7)), 6);
    SET @Code = CONCAT(@Prefix, N'-', @Year, N'-', @Seq, N'-',
                       core.fn_ComputeCheckDigit(CONCAT(@Prefix, @Year, @Seq)));

    SELECT @Code AS EmployeeCode, @Next AS SequenceValue, @Year AS SequenceYear;
END;
GO
