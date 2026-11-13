/* =============================================================================
   Metamorph ERP - 090: Datos de referencia (idempotente)
   -----------------------------------------------------------------------------
   IMPORTANTE: las tasas/tramos legales de El Salvador son VALORES DE
   REFERENCIA para desarrollo. Deben validarse contra la normativa vigente
   (ISSS, Ley SAP/AFP, tabla de retención de Renta del MH) antes de producción.
   Como son datos con vigencia, un cambio de ley = nueva fila con nueva
   EffectiveStartDate, sin tocar código.
   ============================================================================= */
SET NOCOUNT ON;
SET XACT_ABORT ON;
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

BEGIN TRANSACTION;

/* ----------------------------- HCM: tipos de documento ---------------------- */
INSERT INTO hcm.catDocumentType (Code, Name, IsMandatory, RequiresExpiry, RetentionYears)
SELECT s.Code, s.Name, s.IsMandatory, s.RequiresExpiry, s.RetentionYears
FROM (VALUES
        (N'NATIONAL_ID',      N'Documento de identidad',             1, 1, 10),
        (N'TAX_ID',           N'Identificación tributaria',          1, 0, 10),
        (N'EMPLOYMENT_CONTRACT', N'Contrato de trabajo',             1, 0, 10),
        (N'RESUME',           N'Currículum vitae',                   1, 0, 5),
        (N'ACADEMIC_DEGREE',  N'Título / certificación académica',   0, 0, 10),
        (N'BACKGROUND_CHECK', N'Solvencia / antecedentes penales',   0, 1, 5),
        (N'MEDICAL_CERT',     N'Certificado médico',                 0, 1, 5),
        (N'BANK_ACCOUNT',     N'Constancia de cuenta bancaria',      0, 0, 5)
     ) AS s (Code, Name, IsMandatory, RequiresExpiry, RetentionYears)
WHERE NOT EXISTS (SELECT 1 FROM hcm.catDocumentType d WHERE d.Code = s.Code);

/* ----------------------------- FIN: retenciones El Salvador (referencia) ---- */
DECLARE @SV INT = (SELECT CountryId FROM core.catCountry WHERE CountryCode = 'SV');

INSERT INTO fin.catDeductionType
    (CountryId, Code, Name, Category, Party, CalculationMethod, Rate, BaseCap,
     ReducesTaxableBase, CalculationOrder, EffectiveStartDate, LegalReference)
SELECT @SV, s.Code, s.Name, s.Category, s.Party, s.Method, s.Rate, s.BaseCap,
       s.ReducesTaxableBase, s.CalcOrder, '2026-01-01', s.LegalRef
FROM (VALUES
        (N'ISSS_EMP',  N'ISSS cotización laboral',  N'SOCIAL_SECURITY', N'EMPLOYEE', N'PERCENTAGE', 0.030000, 1000.00, 1, 10, N'Ley del Seguro Social - tope salarial cotizable USD 1,000'),
        (N'ISSS_PAT',  N'ISSS aporte patronal',     N'SOCIAL_SECURITY', N'EMPLOYER', N'PERCENTAGE', 0.075000, 1000.00, 0, 11, N'Ley del Seguro Social'),
        (N'AFP_EMP',   N'AFP cotización laboral',   N'PENSION',         N'EMPLOYEE', N'PERCENTAGE', 0.072500, NULL,    1, 20, N'Ley Integral del Sistema de Pensiones'),
        (N'AFP_PAT',   N'AFP aporte patronal',      N'PENSION',         N'EMPLOYER', N'PERCENTAGE', 0.087500, NULL,    0, 21, N'Ley Integral del Sistema de Pensiones'),
        (N'ISR_SV',    N'Impuesto sobre la Renta',  N'INCOME_TAX',      N'EMPLOYEE', N'BRACKET',    NULL,     NULL,    0, 90, N'Tabla de retención de Renta - Ministerio de Hacienda')
     ) AS s (Code, Name, Category, Party, Method, Rate, BaseCap, ReducesTaxableBase, CalcOrder, LegalRef)
WHERE @SV IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM fin.catDeductionType d
                  WHERE d.CountryId = @SV AND d.Code = s.Code AND d.EffectiveStartDate = '2026-01-01');

DECLARE @IsrSv INT = (SELECT DeductionTypeId FROM fin.catDeductionType
                      WHERE CountryId = @SV AND Code = N'ISR_SV' AND EffectiveStartDate = '2026-01-01');

INSERT INTO fin.DeductionBracket (DeductionTypeId, PayFrequency, LowerBound, UpperBound, Rate, FixedFee, ExcessOver)
SELECT @IsrSv, N'MONTHLY', s.LowerBound, s.UpperBound, s.Rate, s.FixedFee, s.ExcessOver
FROM (VALUES
        (0.00,     550.00,  0.000000,   0.00,    0.00),
        (550.01,   895.24,  0.100000,  17.67,  550.00),
        (895.25,  2038.10,  0.200000,  60.00,  895.24),
        (2038.11,    NULL,  0.300000, 288.57, 2038.10)
     ) AS s (LowerBound, UpperBound, Rate, FixedFee, ExcessOver)
WHERE @IsrSv IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM fin.DeductionBracket b
                  WHERE b.DeductionTypeId = @IsrSv AND b.PayFrequency = N'MONTHLY' AND b.LowerBound = s.LowerBound);

COMMIT TRANSACTION;
GO

/* ---------------------------------------------------------------------------
   Centros de costo base por país activo ({CC}-ADM, {CC}-RRHH, {CC}-OPS, {CC}-TI)
   Valores de referencia: reemplazar por el plan de centros de costo real.
   --------------------------------------------------------------------------- */
BEGIN TRANSACTION;

INSERT INTO core.catCostCenter (CountryId, Code, Name, EffectiveStartDate)
SELECT c.CountryId, c.CountryCode + N'-' + s.Suffix, s.Name + N' ' + c.CountryName, c.EffectiveStartDate
FROM core.catCountry AS c
CROSS JOIN (VALUES
        (N'ADM',  N'Administración'),
        (N'RRHH', N'Recursos Humanos'),
        (N'OPS',  N'Operaciones'),
        (N'TI',   N'Tecnología')
     ) AS s (Suffix, Name)
WHERE c.IsActive = 1
  AND NOT EXISTS (SELECT 1 FROM core.catCostCenter cc WHERE cc.Code = c.CountryCode + N'-' + s.Suffix);

COMMIT TRANSACTION;
GO
