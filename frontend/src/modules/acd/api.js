import { api, apiUrl, toQuery } from "../../services/apiClient.js";

const enc = encodeURIComponent;

/** Estados y auxiliares ACD (backend: apps/acd, Fase 11). Las horas las fija el servidor: el navegador no envía tiempos. */
export const acdApi = {
  catalogs: (options) => api.get("/acd/catalogs/", options),
  me: (options) => api.get("/acd/me/", options),
  login: () => api.post("/acd/me/login/"),
  logout: () => api.post("/acd/me/logout/"),
  setStatus: (primary_status, aux_code) => api.post("/acd/me/status/", { primary_status, aux_code: aux_code || null }),
  agents: (params, options) => api.get(`/acd/agents/${toQuery(params)}`, options),
  forceLogout: (code, reason) => api.post(`/acd/agents/${enc(code)}/logout/`, { reason }),
  report: (params, options) => api.get(`/acd/report/${toQuery(params)}`, options),
  reportCsvUrl: (params) => apiUrl(`/acd/report/${toQuery({ ...params, page: undefined, page_size: undefined, export: "csv" })}`),
  groups: (options) => api.get("/acd/groups/", options),
  group: (code, options) => api.get(`/acd/groups/${enc(code)}/`, options),
  createGroup: (payload) => api.post("/acd/groups/", payload),
  updateGroup: (code, payload) => api.patch(`/acd/groups/${enc(code)}/`, payload),
  addMember: (code, employee_code) => api.post(`/acd/groups/${enc(code)}/members/`, { employee_code }),
  removeMember: (code, employeeCode) => api.delete(`/acd/groups/${enc(code)}/members/${enc(employeeCode)}/`),
};

/** 01:02:03 a partir de milisegundos. */
export function fmtDuration(ms) {
  const total = Math.max(0, Math.floor((ms ?? 0) / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
}

export function fmtTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("es-SV", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
