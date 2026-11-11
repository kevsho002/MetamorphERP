import { createBrowserRouter, Navigate } from "react-router-dom";
import AppLayout from "../components/layout/AppLayout.jsx";
import { hcmModule } from "../modules/hcm/index.js";
import { wfmModule } from "../modules/wfm/index.js";
import { payrollModule } from "../modules/payroll/index.js";
import { systemModule } from "../modules/system/index.js";

/**
 * Registro de módulos (monolito modular en el frontend).
 * Cada módulo exporta { id, label, basePath, routes[] } y se monta aquí;
 * el menú lateral se genera a partir de este mismo arreglo.
 */
export const modules = [hcmModule, wfmModule, payrollModule, systemModule];

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppLayout modules={modules} />,
    children: [
      { index: true, element: <Navigate to={systemModule.basePath} replace /> },
      ...modules.flatMap((m) => m.routes),
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);
