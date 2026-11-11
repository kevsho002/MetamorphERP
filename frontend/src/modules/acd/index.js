import { createElement } from "react";
import RequirePermission from "../../auth/RequirePermission.jsx";
import AgentBoardPage from "./pages/AgentBoardPage.jsx";
import AgentConsolePage from "./pages/AgentConsolePage.jsx";
import AcdGroupsPage from "./pages/AcdGroupsPage.jsx";
import AcdReportPage from "./pages/AcdReportPage.jsx";

const AGENT = "acd.agent";
const VIEW = "acd.view";
const guard = (permission, page) => createElement(RequirePermission, { permission }, createElement(page));

/**
 * Estados y auxiliares ACD (Fase 11, estilo Genesys Cloud): consola del agente (iniciar sesión, On Queue y auxiliares
 * de su grupo), tablero en vivo, reporte de estados con el formato de exportación de Genesys y grupos / acceso a
 * auxiliares. El tiempo pagado de cada sesión llega a «Horas teóricas vs reales» como registro WEB_TIMER.
 */
export const acdModule = {
  id: "acd",
  label: "ACD · Estados",
  permission: AGENT,
  basePath: "/acd/console",
  menu: [
    { to: "/acd/console", label: "Mi estado (agente)" },
    { to: "/acd/agents", label: "Agentes en vivo", permission: VIEW },
    { to: "/acd/report", label: "Reporte de estados", permission: VIEW },
    { to: "/acd/groups", label: "Grupos y auxiliares", permission: VIEW },
  ],
  routes: [
    { path: "acd/console", element: guard(AGENT, AgentConsolePage) },
    { path: "acd/agents", element: guard(VIEW, AgentBoardPage) },
    { path: "acd/report", element: guard(VIEW, AcdReportPage) },
    { path: "acd/groups", element: guard(VIEW, AcdGroupsPage) },
  ],
};
