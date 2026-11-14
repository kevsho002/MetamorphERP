import { api, apiUrl, toQuery } from "../../services/apiClient.js";

/** Fase 25 — Periódico virtual: comunicados, acuse de recibo y reportes de cumplimiento. */
export const newsApi = {
  list: (params, options) => api.get(`/announcements/${toQuery(params)}`, options),
  pending: (options) => api.get("/announcements/pending/", options),
  get: (id, options) => api.get(`/announcements/${id}/`, options),
  create: (body) => api.post("/announcements/", body),
  update: (id, body) => api.patch(`/announcements/${id}/`, body),
  remove: (id) => api.delete(`/announcements/${id}/`),
  publish: (id) => api.post(`/announcements/${id}/publish/`),
  archive: (id) => api.post(`/announcements/${id}/archive/`),
  ack: (id) => api.post(`/announcements/${id}/ack/`, { confirm: true }),
  complianceSummary: (options) => api.get("/announcements/compliance/", options),
  compliance: (id, options) => api.get(`/announcements/${id}/compliance/`, options),
  snapshot: (id) => api.post(`/announcements/${id}/compliance/`),
  complianceCsvUrl: (id) => apiUrl(`/announcements/${id}/compliance/?export=csv`),
};

export const PENDING_EVENT = "metamorph:announcements-changed";
export const notifyChanged = () => window.dispatchEvent(new Event(PENDING_EVENT));

export const CATEGORY_TONE = {
  NEWS: "info", BLOG: "muted", FORM: "info", HR: "ok", PAYROLL: "info", CULTURE: "muted", OPS: "warn", SECURITY: "error", ORG_CHANGE: "warn",
};
