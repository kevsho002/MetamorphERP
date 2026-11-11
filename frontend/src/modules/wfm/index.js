import { createElement } from "react";
import AttendancePage from "./pages/AttendancePage.jsx";

export const wfmModule = {
  id: "wfm",
  label: "Workforce (WFM)",
  permission: "wfm.view",
  basePath: "/wfm/attendance",
  menu: [{ to: "/wfm/attendance", label: "Asistencias y downtimes" }],
  routes: [{ path: "wfm/attendance", element: createElement(AttendancePage) }],
};
