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
