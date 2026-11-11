/* =============================================================================
   Metamorph ERP — Fase 7: ciclo de vida oficial del colaborador
   Estados: ACTIVE (Activo), INACTIVE (Inactivo) y TERMINATED (Terminado).
   Sustituye el estado SUSPENDED (Suspendido) por INACTIVE y conserva la regla
   "Terminado <=> fecha de terminación". Idempotente: se puede re-ejecutar.
   ============================================================================= */
SET NOCOUNT ON;
SET XACT_ABORT ON;
GO

IF EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE name = N'CK_Employee_EmploymentStatus'
      AND parent_object_id = OBJECT_ID(N'hcm.Employee')
      AND definition LIKE N'%SUSPENDED%'
)
BEGIN
    BEGIN TRANSACTION;
    ALTER TABLE hcm.Employee DROP CONSTRAINT CK_Employee_EmploymentStatus;
    UPDATE hcm.Employee SET EmploymentStatus = N'INACTIVE' WHERE EmploymentStatus = N'SUSPENDED';
    ALTER TABLE hcm.Employee WITH CHECK ADD CONSTRAINT CK_Employee_EmploymentStatus
        CHECK (EmploymentStatus IN (N'ACTIVE', N'INACTIVE', N'TERMINATED'));
    COMMIT TRANSACTION;
    PRINT N'CK_Employee_EmploymentStatus: SUSPENDED -> INACTIVE (Activo / Inactivo / Terminado).';
END
GO

IF EXISTS (SELECT 1 FROM sys.extended_properties
           WHERE major_id = OBJECT_ID(N'hcm.Employee') AND name = N'MS_Description'
             AND minor_id = COLUMNPROPERTY(OBJECT_ID(N'hcm.Employee'), N'EmploymentStatus', 'ColumnId'))
    EXEC sys.sp_updateextendedproperty N'MS_Description',
        N'Ciclo de vida: ACTIVE = Activo, INACTIVE = Inactivo, TERMINATED = Terminado (exige TerminationDate).',
        N'SCHEMA', N'hcm', N'TABLE', N'Employee', N'COLUMN', N'EmploymentStatus';
ELSE
    EXEC sys.sp_addextendedproperty N'MS_Description',
        N'Ciclo de vida: ACTIVE = Activo, INACTIVE = Inactivo, TERMINATED = Terminado (exige TerminationDate).',
        N'SCHEMA', N'hcm', N'TABLE', N'Employee', N'COLUMN', N'EmploymentStatus';
GO
