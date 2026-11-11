import { createElement } from "react";
import RequirePermission from "../../auth/RequirePermission.jsx";
import GeneralIdsReportPage from "./pages/GeneralIdsReportPage.jsx";

const VIEW = "general_ids.view";

/**
 * General IDs (Fase 7): identificadores para reportería y JOINs (ACD ID, Payroll Tool ID…).
 * El registro por empleado vive en la pestaña «General IDs» del expediente; aquí, la consulta y el buscador.
 */
export const generalIdsModule = {
  id: "general-ids",
  label: "General IDs",
  permission: VIEW,
  basePath: "/general-ids",
  menu: [{ to: "/general-ids", label: "Consulta de General IDs" }],
  routes: [{ path: "general-ids", element: createElement(RequirePermission, { permission: VIEW }, createElement(GeneralIdsReportPage)) }],
};
