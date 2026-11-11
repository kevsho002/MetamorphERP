/* =============================================================================
   Metamorph ERP - 060: Empleado <-> Centro de costos, amarrados al MISMO país
   -----------------------------------------------------------------------------
   Fase 3 (alta individual y masiva de empleados).
   * core.catCostCenter expone la clave alterna (CostCenterId, CountryId).
   * hcm.Employee.CostCenterId (NULL permitido) referencia esa clave alterna con
     una FK COMPUESTA (CostCenterId, CountryId): la BD rechaza asignar a un
     empleado de El Salvador un centro de costos de Guatemala, aunque la
     aplicación tuviera un error. Con CostCenterId NULL la FK no se evalúa.
   Idempotente: puede ejecutarse varias veces.
   ============================================================================= */
SET NOCOUNT ON;
SET XACT_ABORT ON;
SET ANSI_NULLS ON;
SET QUOTED_IDENTIFIER ON;
GO

IF NOT EXISTS (SELECT 1 FROM sys.key_constraints
               WHERE name = N'UQ_catCostCenter_Id_Country' AND parent_object_id = OBJECT_ID(N'core.catCostCenter'))
    ALTER TABLE core.catCostCenter
        ADD CONSTRAINT UQ_catCostCenter_Id_Country UNIQUE (CostCenterId, CountryId);
GO

IF COL_LENGTH(N'hcm.Employee', N'CostCenterId') IS NULL
    ALTER TABLE hcm.Employee ADD CostCenterId INT NULL;
GO

IF OBJECT_ID(N'hcm.FK_Employee_CostCenter_Country', N'F') IS NULL
    ALTER TABLE hcm.Employee WITH CHECK
        ADD CONSTRAINT FK_Employee_CostCenter_Country
        FOREIGN KEY (CostCenterId, CountryId) REFERENCES core.catCostCenter (CostCenterId, CountryId);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = N'IX_Employee_CostCenter' AND object_id = OBJECT_ID(N'hcm.Employee'))
    CREATE NONCLUSTERED INDEX IX_Employee_CostCenter ON hcm.Employee (CostCenterId) WHERE CostCenterId IS NOT NULL;
GO
