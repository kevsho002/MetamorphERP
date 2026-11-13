import { createElement } from "react";
import RequirePermission from "../../auth/RequirePermission.jsx";
import AppearancePage from "./pages/AppearancePage.jsx";
import DataModelPage from "./pages/DataModelPage.jsx";
import SystemStatusPage from "./pages/SystemStatusPage.jsx";

const STATUS = "system.status";

/**
 * Sistema. Fase 22: «Apariencia y configuraciones visuales» (formato de tiempos, modo día / noche, densidad y paleta
 * corporativa; visible para todos) y, para el Administrador, el estado del sistema y «Datos y modelo ER».
 */
export const systemModule = {
  id: "system",
  label: "Sistema",
  permission: "self.view",
  basePath: "/system/status",
  menu: [
    { to: "/system/appearance", label: "Apariencia y configuraciones visuales" },
    { to: "/system/status", label: "Estado del sistema", permission: STATUS },
    { to: "/system/data", label: "Datos y modelo ER", permission: STATUS },
  ],
  routes: [
    { path: "system/status", element: createElement(SystemStatusPage) },
    { path: "system/appearance", element: createElement(AppearancePage) },
    { path: "system/data", element: createElement(RequirePermission, { permission: STATUS }, createElement(DataModelPage)) },
  ],
};
