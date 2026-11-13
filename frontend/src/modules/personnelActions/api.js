import { api, toQuery } from "../../services/apiClient.js";

const enc = encodeURIComponent;

/** Acciones de Personal (backend: apps/personnel_actions, Fase 9). */
export const actionsApi = {
  types: (options) => api.get("/personnel-actions/types/", options),
  list: (params, options) => api.get(`/personnel-actions/${toQuery(params)}`, options),
  get: (folio, options) => api.get(`/personnel-actions/${enc(folio)}/`, options),
  validate: (payload) => api.post("/personnel-actions/validate/", payload),
  create: (payload) => api.post("/personnel-actions/", payload),
  update: (folio, payload) => api.patch(`/personnel-actions/${enc(folio)}/`, payload),
  submit: (folio) => api.post(`/personnel-actions/${enc(folio)}/submit/`, {}),
  sign: (folio, decision, comment) => api.post(`/personnel-actions/${enc(folio)}/sign/`, { decision, comment }),
  cancel: (folio, reason) => api.post(`/personnel-actions/${enc(folio)}/cancel/`, { reason }),
  employee: (code, options) => api.get(`/personnel-actions/employees/${enc(code)}/`, options),
  picker: (params, options) => api.get(`/personnel-actions/employees/picker/${toQuery(params)}`, options), // Fase 23
  missingInitial: (options) => api.get("/personnel-actions/missing-initial/", options),
  schedulePreview: (payload, options) => api.post("/personnel-actions/schedule-preview/", payload, options),
  // Fase 21: ciclo de vida (antigüedad, suspensiones, terminaciones, reingresos) y roles por tipo de AP
  lifecycle: (code, options) => api.get(`/personnel-actions/employees/${enc(code)}/lifecycle/`, options),
  roleMatrix: (options) => api.get("/personnel-actions/role-matrix/", options),
  updateRoles: (code, payload) => api.patch(`/personnel-actions/role-matrix/${enc(code)}/`, payload),
};
