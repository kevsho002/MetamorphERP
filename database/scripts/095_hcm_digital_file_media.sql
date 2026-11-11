/* =============================================================================
   Metamorph ERP - 095: Expediente digital multimedia (Fase 5)
   -----------------------------------------------------------------------------
   * hcm.catDocumentType.IsSensitive: documentos con datos personales protegidos
     (identidad, tributarios, bancarios, médicos, antecedentes). Solo los ve quien
     tiene permiso de planilla (misma regla que los atributos EAV sensibles).
   * Tipo PROFILE_PHOTO: la fotografía de perfil se versiona como un documento más
     del expediente (una sola versión vigente, historial completo).
   * hcm.DigitalFileDocument: dimensiones de la imagen y restricción de formato
     (solo PNG / JPEG, validados además por contenido en el backend).
   Se ejecuta DESPUÉS de 090 (los tipos base ya existen). Idempotente.
   ============================================================================= */
SET NOCOUNT ON;
SET XACT_ABORT ON;
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

/* ------------------------------------------------ catDocumentType.IsSensitive */
IF COL_LENGTH(N'hcm.catDocumentType', N'IsSensitive') IS NULL
BEGIN
    BEGIN TRANSACTION;
    ALTER TABLE hcm.catDocumentType
        ADD IsSensitive BIT NOT NULL CONSTRAINT DF_catDocumentType_IsSensitive DEFAULT (0);
    -- Clasificación inicial (solo la primera vez: luego se administra como dato).
    EXEC (N'UPDATE hcm.catDocumentType SET IsSensitive = 1
            WHERE Code IN (N''NATIONAL_ID'', N''TAX_ID'', N''BANK_ACCOUNT'', N''MEDICAL_CERT'', N''BACKGROUND_CHECK'');');
    COMMIT TRANSACTION;
END
GO

/* ------------------------------------------------ tipo: fotografía de perfil */
INSERT INTO hcm.catDocumentType (Code, Name, IsMandatory, RequiresExpiry, RetentionYears, IsSensitive)
SELECT N'PROFILE_PHOTO', N'Fotografía de perfil', 0, 0, NULL, 0
WHERE NOT EXISTS (SELECT 1 FROM hcm.catDocumentType WHERE Code = N'PROFILE_PHOTO');
GO

/* ------------------------------------------------ DigitalFileDocument: imagen */
IF COL_LENGTH(N'hcm.DigitalFileDocument', N'ImageWidth') IS NULL
    ALTER TABLE hcm.DigitalFileDocument ADD ImageWidth INT NULL, ImageHeight INT NULL;
GO

IF OBJECT_ID(N'hcm.CK_DigitalFileDocument_ImageSize', N'C') IS NULL
    ALTER TABLE hcm.DigitalFileDocument WITH CHECK
        ADD CONSTRAINT CK_DigitalFileDocument_ImageSize
        CHECK ((ImageWidth IS NULL AND ImageHeight IS NULL) OR (ImageWidth > 0 AND ImageHeight > 0));
GO

IF OBJECT_ID(N'hcm.CK_DigitalFileDocument_MimeType', N'C') IS NULL
    ALTER TABLE hcm.DigitalFileDocument WITH CHECK
        ADD CONSTRAINT CK_DigitalFileDocument_MimeType CHECK (MimeType IN (N'image/png', N'image/jpeg'));
GO

/* Historial por documento (pestaña «Documentos» del expediente). */
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_DigitalFileDocument_File_Type'
               AND object_id = OBJECT_ID(N'hcm.DigitalFileDocument'))
    CREATE NONCLUSTERED INDEX IX_DigitalFileDocument_File_Type
        ON hcm.DigitalFileDocument (DigitalFileId, DocumentTypeId, VersionNumber DESC)
        INCLUDE (IsCurrent, UploadedAt);
GO
