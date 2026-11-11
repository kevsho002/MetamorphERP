import { createElement } from "react";
import SystemStatusPage from "./pages/SystemStatusPage.jsx";

export const systemModule = {
  id: "system",
  label: "Sistema",
  permission: "system.status",
  basePath: "/system/status",
  menu: [{ to: "/system/status", label: "Estado del sistema" }],
  routes: [{ path: "system/status", element: createElement(SystemStatusPage) }],
};
