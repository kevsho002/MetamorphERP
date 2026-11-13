import { createElement } from "react";
import { Navigate } from "react-router-dom";
import RequirePermission from "../../auth/RequirePermission.jsx";
import ActivityTypesPage from "./pages/ActivityTypesPage.jsx";
import AdherencePage from "./pages/AdherencePage.jsx";
import ChangeRequestsPage from "./pages/ChangeRequestsPage.jsx";
import PlanningPage from "./pages/PlanningPage.jsx";

const VIEW = "wfm.view";
const guard = (page) => createElement(RequirePermission, { permission: VIEW }, createElement(page));

/**
 * Workforce (WFM). Fase 16: segmentos de actividad dentro del turno (contenedor de la AP), validación de pago y
 * facturación, motor de adherencia (Out of Adherence / Unpaid Excess Login) y justificaciones respaldadas por AP.
 * Fase 17: planificación estilo Nice IEX (filtros jerárquicos, barra de segmentos con drag & drop, grilla de grupo y
 * vista histórica del agente). Fase 18: la cadena de mando se gestiona en el Roster (/roster/hierarchy); barra compacta,
 * granularidad al segundo y audit trail por línea / fecha. Fase 19: Lateness / ausencias automáticas, categorías del Time
 * Utilization, segmentos que exigen AP, ventana flotante del día y cola de aprobación de WFM.
 * Editar requiere «wfm.manage»; las pantallas lo indican con `can_manage`.
 */
export const wfmModule = {
  id: "wfm",
  label: "Workforce (WFM)",
  permission: VIEW,
  basePath: "/wfm/planner",
  menu: [
    { to: "/wfm/planner", label: "Planificación (grilla IEX)" },
    { to: "/wfm/requests", label: "Cola de aprobación" },
    { to: "/wfm/adherence", label: "Adherencia" },
    { to: "/wfm/activities", label: "Actividades (segmentos)" },
  ],
  routes: [
    { path: "wfm/planner", element: guard(PlanningPage) },
    { path: "wfm/requests", element: guard(ChangeRequestsPage) },
    { path: "wfm/adherence", element: guard(AdherencePage) },
    // Fase 22: las justificaciones son AP del módulo regular (Acciones de personal › Justificaciones y permisos).
    { path: "wfm/justifications", element: createElement(Navigate, { to: "/personnel-actions/justifications", replace: true }) },
    { path: "wfm/activities", element: guard(ActivityTypesPage) },
    { path: "wfm/hierarchy", element: createElement(Navigate, { to: "/roster/hierarchy", replace: true }) }, // movida al roster (Fase 18)
    // Fase 22: se retiró el mock «Asistencias y downtimes» (la asistencia vive en la grilla IEX y la adherencia).
    { path: "wfm/attendance", element: createElement(Navigate, { to: "/wfm/adherence", replace: true }) },
  ],
};
