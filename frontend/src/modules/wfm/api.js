import { api, toQuery } from "../../services/apiClient.js";

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
};

/** 7:05 (horas:minutos) a partir de segundos. */
export function fmtHM(seconds) {
  const total = Math.round((seconds ?? 0) / 60);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export function fmtPct(value) {
  return value === null || value === undefined ? "—" : `${Number(value).toFixed(2)} %`;
}

/** "2026-10-05T10:15:00" → "10:15" (hora local de la operación, sin conversión de zona). */
export function hhmm(iso) {
  return iso ? iso.slice(11, 16) : "—";
}

export function addMinutes(hm, minutes) {
  const [h, m] = hm.split(":").map(Number);
  const total = (((h * 60 + m + minutes) % 1440) + 1440) % 1440;
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

/** Fecha y hora local sin zona: los ISO del backend se leen tal cual (no como UTC). */
export function wallMs(iso) {
  const [d, t = "00:00:00"] = iso.split("T");
  const [y, mo, da] = d.split("-").map(Number);
  const [h, mi, s = 0] = t.split(":").map(Number);
  return Date.UTC(y, mo - 1, da, h, mi, s);
}
