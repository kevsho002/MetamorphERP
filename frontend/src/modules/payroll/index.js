import { createElement } from "react";
import PayrollPage from "./pages/PayrollPage.jsx";

export const payrollModule = {
  id: "payroll",
  label: "Planillas",
  permission: "payroll.view",
  basePath: "/payroll",
  menu: [{ to: "/payroll", label: "Planillas y retenciones" }],
  routes: [{ path: "payroll", element: createElement(PayrollPage) }],
};
