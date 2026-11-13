import { createElement } from "react";
import RequirePermission from "../../auth/RequirePermission.jsx";
import ActionDetailPage from "./pages/ActionDetailPage.jsx";
import ActionsPage from "./pages/ActionsPage.jsx";
import NewActionPage from "./pages/NewActionPage.jsx";
import RoleMatrixPage from "./pages/RoleMatrixPage.jsx";

const VIEW = "actions.view";
const CREATE = "actions.create";
const guard = (permission, page) => createElement(RequirePermission, { permission }, createElement(page));

/**
 * Acciones de Personal (Fase 9): eventos operativos con folio, fecha efectiva, justificación y firmas por rol.
 * Por empleado, también en las pestañas «Horario» y «Acciones de personal» del expediente.
 */
export const personnelActionsModule = {
  id: "personnel-actions",
  label: "Acciones de personal",
  permission: VIEW,
  basePath: "/personnel-actions",
  menu: [
    { to: "/personnel-actions", label: "Bandeja de AP", end: true },
    { to: "/personnel-actions/new", label: "Nueva AP", permission: CREATE },
    { to: "/personnel-actions/roles", label: "Roles por tipo de AP" },
  ],
  routes: [
    { path: "personnel-actions", element: guard(VIEW, ActionsPage) },
    { path: "personnel-actions/new", element: guard(CREATE, NewActionPage) },
    { path: "personnel-actions/roles", element: guard(VIEW, RoleMatrixPage) },
    { path: "personnel-actions/:folio", element: guard(VIEW, ActionDetailPage) },
  ],
};
