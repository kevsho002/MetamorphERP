import { createElement } from "react";
import RequirePermission from "../../auth/RequirePermission.jsx";
import RosterReportPage from "./pages/RosterReportPage.jsx";

const VIEW = "roster.view";

/**
 * Roster operativo (dominio independiente de la ficha). La edición por empleado vive en la
 * pestaña «Roster» del expediente (/hcm/employees/:ID?tab=roster); aquí, la consulta cruzada.
 */
export const rosterModule = {
  id: "roster",
  label: "Roster operativo",
  permission: VIEW,
  basePath: "/roster/report",
  menu: [{ to: "/roster/report", label: "Consulta de roster" }],
  routes: [{ path: "roster/report", element: createElement(RequirePermission, { permission: VIEW }, createElement(RosterReportPage)) }],
};
