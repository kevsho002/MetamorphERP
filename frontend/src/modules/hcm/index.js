import { createElement } from "react";
import RequirePermission from "../../auth/RequirePermission.jsx";
import DigitalFilesPage from "./pages/DigitalFilesPage.jsx";
import EmployeeDetailPage from "./pages/EmployeeDetailPage.jsx";
import EmployeeFormPage from "./pages/EmployeeFormPage.jsx";
import EmployeeImportPage from "./pages/EmployeeImportPage.jsx";
import EmployeesPage from "./pages/EmployeesPage.jsx";
import ImportBatchPage from "./pages/ImportBatchPage.jsx";
import ImportHistoryPage from "./pages/ImportHistoryPage.jsx";

const VIEW = "hcm.view";
const MANAGE = "hcm.manage"; // alta, edición y cargas masivas (Administrador y RRHH)

/** Envuelve la página con la verificación de permiso (la API vuelve a validar con 403). */
const guarded = (permission, Page) => createElement(RequirePermission, { permission }, createElement(Page));

export const hcmModule = {
  id: "hcm",
  label: "Capital Humano",
  permission: VIEW,
  basePath: "/hcm/employees",
  menu: [
    { to: "/hcm/employees", label: "Empleados", end: true },
    { to: "/hcm/employees/new", label: "Alta de empleado", permission: MANAGE },
    { to: "/hcm/employees/import", label: "Carga masiva", permission: MANAGE },
    { to: "/hcm/employees/imports", label: "Historial de cargas", permission: MANAGE },
    { to: "/hcm/digital-files", label: "Expedientes digitales" },
  ],
  routes: [
    { path: "hcm/employees", element: guarded(VIEW, EmployeesPage) },
    { path: "hcm/employees/new", element: guarded(MANAGE, EmployeeFormPage) },
    { path: "hcm/employees/import", element: guarded(MANAGE, EmployeeImportPage) },
    { path: "hcm/employees/imports", element: guarded(MANAGE, ImportHistoryPage) },
    { path: "hcm/employees/imports/:id", element: guarded(MANAGE, ImportBatchPage) },
    { path: "hcm/employees/:code", element: guarded(VIEW, EmployeeDetailPage) },
    { path: "hcm/employees/:code/edit", element: guarded(MANAGE, EmployeeFormPage) },
    { path: "hcm/digital-files", element: guarded(VIEW, DigitalFilesPage) },
  ],
};
