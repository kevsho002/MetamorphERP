import { api, apiUrl, toQuery } from "../../services/apiClient.js";

/** General IDs (backend: apps/general_ids). Módulo independiente del roster y de la ficha. */
export const generalIdsApi = {
  catalogs: (options) => api.get("/general-ids/catalogs/", options),
  employee: (code, params, options) =>
    api.get(`/general-ids/employees/${encodeURIComponent(code)}/${toQuery(params)}`, options),
  validate: (code, payload) => api.post(`/general-ids/employees/${encodeURIComponent(code)}/validate/`, payload),
  create: (code, payload) => api.post(`/general-ids/employees/${encodeURIComponent(code)}/`, payload),
  correct: (code, id, payload, { dryRun = false } = {}) =>
    api.patch(`/general-ids/employees/${encodeURIComponent(code)}/${id}/${dryRun ? "?dry_run=1" : ""}`, payload),
  close: (code, id, payload) => api.post(`/general-ids/employees/${encodeURIComponent(code)}/${id}/close/`, payload),
  lookup: (params, options) => api.get(`/general-ids/lookup/${toQuery(params)}`, options),
  report: (params, options) => api.get(`/general-ids/report/${toQuery(params)}`, options),
  reportCsvUrl: (params) => apiUrl(`/general-ids/report/${toQuery({ ...params, page: undefined, export: "csv" })}`),
};
