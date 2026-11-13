import { api, toQuery } from "../../services/apiClient.js";
import { formatSeconds } from "../../app/timeFormat.js";

const enc = encodeURIComponent;

/** Segmentos de actividad, justificaciones por AP y adherencia (backend: apps/adherence, Fase 16). */
export const adhApi = {
  catalogs: (options) => api.get("/adherence/catalogs/", options),
  createActivity: (payload) => api.post("/adherence/activities/", payload),
  updateActivity: (code, payload) => api.patch(`/adherence/activities/${enc(code)}/`, payload),
  planner: (params, options) => api.get(`/adherence/planner/${toQuery(params)}`, options),
  createSegment: (payload) => api.post("/adherence/segments/", payload),
  bulkSegments: (payload) => api.post("/adherence/segments/bulk/", payload),
  updateSegment: (id, payload) => api.patch(`/adherence/segments/${id}/`, payload),
  deleteSegment: (id) => api.delete(`/adherence/segments/${id}/`),
  exceptions: (params, options) => api.get(`/adherence/exceptions/${toQuery(params)}`, options),
  createException: (payload) => api.post("/adherence/exceptions/", payload),
  deleteException: (id) => api.delete(`/adherence/exceptions/${id}/`),
  report: (params, options) => api.get(`/adherence/report/${toQuery(params)}`, options),
  detail: (params, options) => api.get(`/adherence/detail/${toQuery(params)}`, options),
  compute: (payload) => api.post("/adherence/compute/", payload),
  // Fase 17: planificación estilo IEX
  gridFilters: (options) => api.get("/adherence/grid/filters/", options),
  grid: (params, options) => api.get(`/adherence/grid/${toQuery(params)}`, options),
  agentHistory: (params, options) => api.get(`/adherence/grid/agent/${toQuery(params)}`, options),
  gridSettings: (params, options) => api.get(`/adherence/grid/settings/${toQuery(params)}`, options),
  saveGridSettings: (payload) => api.put("/adherence/grid/settings/", payload),
  // Fase 18: audit trail de una línea (agente + fecha de turno)
  auditTrail: (params, options) => api.get(`/adherence/grid/audit/${toQuery(params)}`, options),
  // Fase 19: asistencia automática, ventana flotante del día y cola de aprobación de WFM
  replaceSegment: (id, payload) => api.post(`/adherence/segments/${id}/replace/`, payload),
  reconcile: (payload) => api.post("/adherence/attendance/reconcile/", payload),
  day: (params, options) => api.get(`/adherence/day/${toQuery(params)}`, options),
  requests: (params, options) => api.get(`/adherence/requests/${toQuery(params)}`, options),
  createRequest: (payload) => api.post("/adherence/requests/", payload),
  decideRequest: (id, payload) => api.post(`/adherence/requests/${id}/decide/`, payload),
  cancelRequest: (id) => api.post(`/adherence/requests/${id}/cancel/`, {}),
  myPlan: (params, options) => api.get(`/adherence/my-plan/${toQuery(params)}`, options),
};

/** Estado de asistencia de una fila (Fase 19). */
export const ATTENDANCE = {
  LATE: { label: "Lateness", cls: "badge--warn" },
  ABSENT: { label: "Ausencia injustificada", cls: "badge--error" },
  LEAVE: { label: "Permiso / licencia", cls: "badge--info" },
  INACTIVE: { label: "Inactivo", cls: "badge--muted" },
};

/** Agrupa actividades por categoría del Time Utilization (para <optgroup> y el desplegable de la barra). */
export function groupByCategory(activities) {
  const groups = new Map();
  activities.forEach((a) => {
    const key = a.utilization_category?.code ?? "";
    if (!groups.has(key)) groups.set(key, { code: key, name: a.utilization_category?.name ?? "Sin categoría",
      department: a.utilization_category?.department_label ?? "", sort: a.utilization_category?.sort_order ?? 9999, items: [] });
    groups.get(key).items.push(a);
  });
  return [...groups.values()].sort((x, y) => x.sort - y.sort);
}


/** Minutos desde las 00:00 de la fecha → "HH:MM" (un turno nocturno puede pasar de 24 h: se muestra la hora del reloj). */
export function minutesToHM(minutes) {
  const m = ((Math.round(minutes) % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
}

/** ISO local → minutos desde las 00:00 de `date` (AAAA-MM-DD). */
export function minutesFrom(date, iso) {
  return (wallMs(iso) - wallMs(`${date}T00:00:00`)) / 60_000;
}

/** Minutos (con decimales) desde las 00:00 → "HH:MM:SS" (Fase 18: granularidad al segundo). */
export function minutesToHMS(minutes) {
  const total = ((Math.round(minutes * 60) % 86400) + 86400) % 86400;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/** Hora para mostrar: "HH:MM" o "HH:MM:SS" si tiene segundos. */
export function clockLabel(minutes) {
  const full = minutesToHMS(minutes);
  return full.endsWith(":00") ? full.slice(0, 5) : full;
}

/** Total de tiempo en segundos según el formato global (Fase 21): "07:05:30" u "7.09" horas decimales. */
export function fmtHM(seconds) {
  return formatSeconds(seconds ?? 0);
}

/** Duración legible: 930 → "15 min 30 s"; 3600 → "1 h". */
export function fmtDuration(seconds) {
  const t = Math.round(seconds ?? 0);
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = t % 60;
  return [h ? `${h} h` : "", m ? `${m} min` : "", s ? `${s} s` : ""].filter(Boolean).join(" ") || "0 s";
}

/** "HH:MM:SS" | "MM:SS" | minutos → segundos (null si no es válido). */
export function parseDuration(text) {
  const t = String(text ?? "").trim();
  if (!t) return null;
  if (/^\d+$/.test(t)) return Number(t) * 60;
  const parts = t.split(":").map(Number);
  if (parts.some((n) => Number.isNaN(n) || n < 0) || parts.length < 2 || parts.length > 3) return null;
  const [h, m, s] = parts.length === 3 ? parts : [0, ...parts];
  if (m > 59 || s > 59) return null;
  return h * 3600 + m * 60 + s;
}

/** Segundos → "HH:MM:SS" (para editar duraciones). */
export function durationText(seconds) {
  if (seconds === null || seconds === undefined) return "";
  return minutesToHMS(seconds / 60);
}

export function fmtPct(value) {
  return value === null || value === undefined ? "—" : `${Number(value).toFixed(2)} %`;
}

/** "2026-10-05T10:15:00" → "10:15"; con segundos → "10:15:30" (hora local de la operación, sin conversión de zona). */
export function hhmm(iso) {
  if (!iso) return "—";
  const t = iso.slice(11, 19);
  return t.length === 8 && !t.endsWith(":00") ? t : iso.slice(11, 16);
}

/** "2026-10-05T10:15:30" → "10:15:30" (siempre con segundos, para editar). */
export function hhmmss(iso) {
  return iso ? (iso.slice(11, 19) + ":00").slice(0, 8) : "";
}

/** "HH:MM[:SS]" + segundos → "HH:MM:SS". */
export function addSeconds(hms, seconds) {
  const [h, m, s = 0] = hms.split(":").map(Number);
  return minutesToHMS((h * 3600 + m * 60 + s + seconds) / 60);
}

/** Fecha y hora local sin zona: los ISO del backend se leen tal cual (no como UTC). */
export function wallMs(iso) {
  const [d, t = "00:00:00"] = iso.split("T");
  const [y, mo, da] = d.split("-").map(Number);
  const [h, mi, s = 0] = t.split(":").map(Number);
  return Date.UTC(y, mo - 1, da, h, mi, s);
}
