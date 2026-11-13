import { createElement } from "react";
import RequirePermission from "../../auth/RequirePermission.jsx";
import DayDetailPage from "./pages/DayDetailPage.jsx";
import HolidaysPage from "./pages/HolidaysPage.jsx";
import HoursReportPage from "./pages/HoursReportPage.jsx";
import PayCyclesPage from "./pages/PayCyclesPage.jsx";

const VIEW = "schedules.view";
const guard = (permission, page) => createElement(RequirePermission, { permission }, createElement(page));

/**
 * Horarios, tiempo y cortes (Fases 8–10). La asignación por empleado vive en la pestaña «Horario» del
 * expediente (/hcm/employees/:ID?tab=schedule) y se cambia con Acciones de Personal; aquí, reporte de horas
 * teóricas vs reales, desglose por fecha de ocurrencia y cortes agrupados por año.
 * Fase 10: la carga MANUAL de registros de tiempo se retiró (riesgo de manipulación); la reemplazará el Web Timer interno.
 */
export const schedulingModule = {
  id: "scheduling",
  label: "Horarios y tiempo",
  permission: VIEW,
  basePath: "/scheduling/report",
  menu: [
    { to: "/scheduling/report", label: "Horas teóricas vs reales" },
    { to: "/scheduling/pay-cycles", label: "Ciclos de pago y cortes" },
    { to: "/scheduling/holidays", label: "Calendario de feriados" },
  ],
  routes: [
    { path: "scheduling/report", element: guard(VIEW, HoursReportPage) },
    { path: "scheduling/employees/:code/days/:date", element: guard(VIEW, DayDetailPage) },
    { path: "scheduling/pay-cycles", element: guard(VIEW, PayCyclesPage) },
    { path: "scheduling/holidays", element: guard(VIEW, HolidaysPage) },
  ],
};
