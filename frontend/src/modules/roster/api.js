import { api, apiUrl, toQuery } from "../../services/apiClient.js";

/** Roster operativo (backend: apps/roster). Dominio independiente de la ficha del empleado. */
export const rosterApi = {
  attributes: (options) => api.get("/roster/attributes/", options),
  dimensions: (options) => api.get("/roster/dimensions/", options),
  employee: (code, asOf, options) =>
    api.get(`/roster/employees/${encodeURIComponent(code)}/${toQuery({ as_of: asOf })}`, options),
  history: (code, attribute, options) =>
    api.get(
      `/roster/employees/${encodeURIComponent(code)}/history/${toQuery({ attribute, include_superseded: 1 })}`,
      options,
    ),
  validate: (code, payload) => api.post(`/roster/employees/${encodeURIComponent(code)}/changes/validate/`, payload),
  apply: (code, payload) => api.post(`/roster/employees/${encodeURIComponent(code)}/changes/`, payload),
  report: (params, options) => api.get(`/roster/report/${toQuery(params)}`, options),
  reportCsvUrl: (params) => apiUrl(`/roster/report/${toQuery({ ...params, page: undefined, export: "csv" })}`),
};

/** Cadena de mando (Fase 18: se gestiona en el roster; backend: apps/operations + /roster/hierarchy/). */
export const leadersApi = {
  list: (params, options) => api.get(`/roster/hierarchy/leaders/${toQuery(params)}`, options),
  create: (payload) => api.post("/roster/hierarchy/leaders/", payload),
  update: (id, payload) => api.patch(`/roster/hierarchy/leaders/${id}/`, payload),
};

/** Niveles de la cadena de mando, del más alto al más bajo (parámetro de filtro, nivel, etiqueta). */
export const CHAIN_LEVELS = [
  ["director", "OPS_DIRECTOR", "Operations Director"],
  ["manager", "OPS_MANAGER", "Operations Manager"],
  ["supervisor", "ACCOUNT_SUPERVISOR", "Account Supervisor"],
  ["team_manager", "TEAM_MANAGER", "Team Manager"],
];
