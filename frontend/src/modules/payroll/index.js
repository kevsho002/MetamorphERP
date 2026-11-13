import { createElement } from "react";
import RequirePermission from "../../auth/RequirePermission.jsx";
import PayrollPage from "./pages/PayrollPage.jsx";
import PayrollRunPage from "./pages/PayrollRunPage.jsx";
import PayrollSettingsPage from "./pages/PayrollSettingsPage.jsx";
import PayslipInventoryPage from "./pages/PayslipInventoryPage.jsx";
import PayslipPrintPage from "./pages/PayslipPrintPage.jsx";
import SettlementBatchPage from "./pages/SettlementBatchPage.jsx";
import SettlementDetailPage from "./pages/SettlementDetailPage.jsx";
import SettlementsPage from "./pages/SettlementsPage.jsx";

const VIEW = "payroll.view";
const guard = (page) => createElement(RequirePermission, { permission: VIEW }, createElement(page));

/**
 * Planillas (Fase 20): cálculo automático por periodo de pago con el Web Timer, las AP de pago, los segmentos de WFM y la
 * adherencia; cierre con generación masiva de boletas e inventario físico de boletas para RRHH (impresas, firmadas,
 * archivadas) por quincena / mes y departamento.
 */
export const payrollModule = {
  id: "payroll",
  label: "Planillas",
  permission: VIEW,
  basePath: "/payroll",
  menu: [
    { to: "/payroll", label: "Cálculo de planilla", end: true },
    { to: "/payroll/inventory", label: "Inventario de boletas" },
    { to: "/payroll/settlements", label: "Liquidaciones e indemnizaciones" },
    { to: "/payroll/settings", label: "Parámetros salariales" },
  ],
  routes: [
    { path: "payroll", element: guard(PayrollPage) },
    { path: "payroll/runs/:id", element: guard(PayrollRunPage) },
    { path: "payroll/inventory", element: guard(PayslipInventoryPage) },
    { path: "payroll/settings", element: guard(PayrollSettingsPage) },
    { path: "payroll/payslips/print", element: guard(PayslipPrintPage) },
    { path: "payroll/settlements", element: guard(SettlementsPage) },
    { path: "payroll/settlements/:id", element: guard(SettlementDetailPage) },
    { path: "payroll/settlement-batches/:id", element: guard(SettlementBatchPage) },
  ],
};
