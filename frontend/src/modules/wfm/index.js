import { createElement } from "react";
import RequirePermission from "../../auth/RequirePermission.jsx";
import ActivityTypesPage from "./pages/ActivityTypesPage.jsx";
import AdherencePage from "./pages/AdherencePage.jsx";
import AttendancePage from "./pages/AttendancePage.jsx";
import JustificationsPage from "./pages/JustificationsPage.jsx";
import SegmentPlannerPage from "./pages/SegmentPlannerPage.jsx";

const VIEW = "wfm.view";
const guard = (page) => createElement(RequirePermission, { permission: VIEW }, createElement(page));

/**
 * Workforce (WFM). Fase 16: segmentos de actividad dentro del turno (contenedor de la AP), validación de pago y
 * facturación, motor de adherencia (Out of Adherence / Unpaid Excess Login) y justificaciones respaldadas por AP.
 * Editar requiere «wfm.manage»; las pantallas lo indican con `can_manage`.
 */
export const wfmModule = {
  id: "wfm",
  label: "Workforce (WFM)",
  permission: VIEW,
  basePath: "/wfm/planner",
  menu: [
    { to: "/wfm/planner", label: "Planificador de segmentos" },
    { to: "/wfm/adherence", label: "Adherencia" },
    { to: "/wfm/justifications", label: "Justificaciones (AP)" },
    { to: "/wfm/activities", label: "Actividades (segmentos)" },
    { to: "/wfm/attendance", label: "Asistencias y downtimes" },
  ],
  routes: [
    { path: "wfm/planner", element: guard(SegmentPlannerPage) },
    { path: "wfm/adherence", element: guard(AdherencePage) },
    { path: "wfm/justifications", element: guard(JustificationsPage) },
    { path: "wfm/activities", element: guard(ActivityTypesPage) },
    { path: "wfm/attendance", element: guard(AttendancePage) },
  ],
};
