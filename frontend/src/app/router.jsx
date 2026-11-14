import { createBrowserRouter, Navigate } from "react-router-dom";
import AppLayout from "../components/layout/AppLayout.jsx";
import { hcmModule } from "../modules/hcm/index.js";
import { wfmModule } from "../modules/wfm/index.js";
import { payrollModule } from "../modules/payroll/index.js";
import { rosterModule } from "../modules/roster/index.js";
import { generalIdsModule } from "../modules/generalIds/index.js";
import { schedulingModule } from "../modules/scheduling/index.js";
import { personnelActionsModule } from "../modules/personnelActions/index.js";
import { acdModule } from "../modules/acd/index.js";
import { systemModule } from "../modules/system/index.js";
import { portalModule } from "../modules/portal/index.js";
import AnnouncementsPage from "../modules/announcements/AnnouncementsPage.jsx";
import AnnouncementDetailPage from "../modules/announcements/AnnouncementDetailPage.jsx";
import AnnouncementEditorPage from "../modules/announcements/AnnouncementEditorPage.jsx";
import CompliancePage from "../modules/announcements/CompliancePage.jsx";
import RequirePermission from "../auth/RequirePermission.jsx";

/**
 * Registro de módulos (monolito modular en el frontend).
 * Cada módulo exporta { id, label, basePath, routes[] } y se monta aquí;
 * el menú lateral se genera a partir de este mismo arreglo.
 */
export const modules = [portalModule, hcmModule, rosterModule, generalIdsModule, personnelActionsModule, schedulingModule, acdModule, wfmModule, payrollModule, systemModule];

export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppLayout modules={modules} />,
    children: [
      // Fase 24: el inicio (y el logotipo de la barra) lleva a los anuncios corporativos, visibles para todo usuario.
      { index: true, element: <Navigate to="/announcements" replace /> },
      { path: "announcements", element: <AnnouncementsPage /> },
      // Fase 25: periódico virtual (comunicados, acuse de recibo y cumplimiento)
      { path: "announcements/new", element: <RequirePermission permission="announcements.manage"><AnnouncementEditorPage /></RequirePermission> },
      { path: "announcements/compliance", element: <RequirePermission permission="announcements.compliance"><CompliancePage /></RequirePermission> },
      { path: "announcements/:id", element: <AnnouncementDetailPage /> },
      { path: "announcements/:id/edit", element: <RequirePermission permission="announcements.manage"><AnnouncementEditorPage /></RequirePermission> },
      { path: "announcements/:id/compliance", element: <RequirePermission permission="announcements.compliance"><CompliancePage /></RequirePermission> },
      ...modules.flatMap((m) => m.routes),
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);
