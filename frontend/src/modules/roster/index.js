import { createElement } from "react";
import RequirePermission from "../../auth/RequirePermission.jsx";
import ChainOfCommandPage from "./pages/ChainOfCommandPage.jsx";
import RosterReportPage from "./pages/RosterReportPage.jsx";

const VIEW = "roster.view";

/**
 * Roster operativo (dominio independiente de la ficha). La edición por empleado vive en la
 * pestaña «Roster» del expediente (/hcm/employees/:ID?tab=roster); aquí, la consulta cruzada.
 * Fase 18: la cadena de mando (Director → Manager → Supervisor → Team Manager) también vive en el roster.
 */
export const rosterModule = {
  id: "roster",
  label: "Roster operativo",
  permission: VIEW,
  basePath: "/roster/report",
  menu: [
    { to: "/roster/report", label: "Consulta de roster" },
    { to: "/roster/hierarchy", label: "Cadena de mando" },
  ],
  routes: [
    { path: "roster/report", element: createElement(RequirePermission, { permission: VIEW }, createElement(RosterReportPage)) },
    { path: "roster/hierarchy", element: createElement(RequirePermission, { permission: VIEW }, createElement(ChainOfCommandPage)) },
  ],
};
