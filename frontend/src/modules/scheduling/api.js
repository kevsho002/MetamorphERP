import { api, apiUrl, toQuery } from "../../services/apiClient.js";

const enc = encodeURIComponent;

/**
 * Horarios, tiempo por fecha de ocurrencia y cortes de nómina (backend: apps/scheduling, Fases 8–10).
 * La carga manual de tiempos está retirada (Fase 10): solo se consultan los registros existentes.
 */
export const schedulingApi = {
  catalogs: (options) => api.get("/scheduling/catalogs/", options),
  assignments: (code, options) => api.get(`/scheduling/employees/${enc(code)}/assignments/`, options),
  schedulePreview: (payload, options) => api.post("/scheduling/schedule-preview/", payload, options),
  timeline: (code, params, options) => api.get(`/scheduling/employees/${enc(code)}/timeline/${toQuery(params)}`, options),
  employeeDay: (code, date, options) => api.get(`/scheduling/employees/${enc(code)}/days/${enc(date)}/`, options),
  timeRecords: (params, options) => api.get(`/scheduling/time-records/${toQuery(params)}`, options),
  lunchRules: (options) => api.get("/scheduling/lunch-rules/", options),
  report: (params, options) => api.get(`/scheduling/report/${toQuery(params)}`, options),
  reportCsvUrl: (params) => apiUrl(`/scheduling/report/${toQuery({ ...params, page: undefined, export: "csv" })}`),
  payCycles: (params, options) => api.get(`/scheduling/pay-cycles/${toQuery(params)}`, options),
  generatePeriods: (code, year) => api.post(`/scheduling/pay-cycles/${enc(code)}/generate/`, { year }),
  closePeriod: (id) => api.post(`/scheduling/pay-periods/${id}/close/`),
  reopenPeriod: (id) => api.post(`/scheduling/pay-periods/${id}/reopen/`),
};
