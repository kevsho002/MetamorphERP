import { createElement } from "react";
import RequirePermission from "../../auth/RequirePermission.jsx";
import MyPayslipsPage from "./pages/MyPayslipsPage.jsx";
import NotificationsPage from "./pages/NotificationsPage.jsx";
import PayrollExceptionsPage from "./pages/PayrollExceptionsPage.jsx";

const SELF = "self.view";
const guard = (page) => createElement(RequirePermission, { permission: SELF }, createElement(page));

/**
 * Portal del colaborador (Fase 21): boletas preliminares y finales, y excepciones de planilla (el agente las reporta; su
 * supervisor o Planillas las atienden antes del cierre). Fase 22: centro de notificaciones operativas.
 */
export const portalModule = {
  id: "portal",
  label: "Mi portal",
  permission: SELF,
  basePath: "/portal",
  menu: [
    { to: "/portal/notifications", label: "Notificaciones" },
    { to: "/portal/payslips", label: "Mis boletas" },
    { to: "/portal/exceptions", label: "Excepciones de planilla" },
  ],
  routes: [
    { path: "portal/notifications", element: guard(NotificationsPage) },
    { path: "portal/payslips", element: guard(MyPayslipsPage) },
    { path: "portal/exceptions", element: guard(PayrollExceptionsPage) },
  ],
};
