import { api, apiUrl, toQuery } from "../../services/apiClient.js";

/** Endpoints de Gestión de Empleados (backend: apps/employees). */
export const employeesApi = {
  catalogs: (options) => api.get("/hcm/catalogs/", options),

  list: (params, options) => api.get(`/hcm/employees/${toQuery(params)}`, options),
  get: (code, options) => api.get(`/hcm/employees/${encodeURIComponent(code)}/`, options),
  create: (payload) => api.post("/hcm/employees/", payload),
  validateCreate: (payload) => api.post("/hcm/employees/validate/", payload),
  update: (code, payload) => api.patch(`/hcm/employees/${encodeURIComponent(code)}/`, payload),
  validateUpdate: (code, payload) => api.post(`/hcm/employees/${encodeURIComponent(code)}/validate/`, payload),

  /** Plantilla vigente del país a una fecha (fecha de ingreso) + especificación del formulario. */
  applicableTemplate: (country, date, options) =>
    api.get(`/hcm/employee-templates/applicable/${toQuery({ country, date })}`, options),
  templates: (params, options) => api.get(`/hcm/employee-templates/${toQuery(params)}`, options),
  templateCsvUrl: (templateId) => apiUrl(`/hcm/employee-templates/${templateId}/csv/`),

  /** Carga masiva: multipart con el archivo y las opciones. */
  importFile: (file, { dryRun, atomicity }) => {
    const form = new FormData();
    form.append("file", file);
    form.append("dry_run", dryRun ? "true" : "false");
    form.append("atomicity", atomicity);
    return api.post("/hcm/employee-imports/", form);
  },
  imports: (params, options) => api.get(`/hcm/employee-imports/${toQuery(params)}`, options),
  importBatch: (id, params, options) => api.get(`/hcm/employee-imports/${id}/${toQuery(params)}`, options),

  // ------------------------------------------------------------ expediente digital (Fase 5)
  /** Expediente con la plantilla vigente a `asOf` (AAAA-MM-DD); sin fecha, la de ingreso. */
  digitalFile: (code, asOf, options) =>
    api.get(`/hcm/employees/${encodeURIComponent(code)}/digital-file/${toQuery({ as_of: asOf })}`, options),
  digitalFiles: (params, options) => api.get(`/hcm/digital-files/${toQuery(params)}`, options),
  documents: (code, type, options) =>
    api.get(`/hcm/employees/${encodeURIComponent(code)}/documents/${toQuery({ type })}`, options),
  uploadDocument: (code, { file, documentType, issueDate, expiryDate }) => {
    const form = new FormData();
    form.append("file", file);
    form.append("document_type", documentType);
    if (issueDate) form.append("issue_date", issueDate);
    if (expiryDate) form.append("expiry_date", expiryDate);
    return api.post(`/hcm/employees/${encodeURIComponent(code)}/documents/`, form);
  },
  uploadPhoto: (code, file) => {
    const form = new FormData();
    form.append("file", file);
    return api.post(`/hcm/employees/${encodeURIComponent(code)}/photo/`, form);
  },
  /** Las rutas de contenido que devuelve el backend ya incluyen /api/v1. */
  contentUrl: (path, { download = false } = {}) => (download ? `${path}?download=1` : path),
  history: (code, options) => api.get(`/hcm/employees/${encodeURIComponent(code)}/history/`, options),

  // ------------------------------------------------------------ cuenta Metamorph vinculada
  createUserAccount: (code, payload) => api.post(`/hcm/employees/${encodeURIComponent(code)}/user-account/`, payload),
  /** Fase 7: cuentas existentes sin empleado (que el usuario actual puede administrar) y vínculo. */
  accountCandidates: (search, options) => api.get(`/hcm/user-account-candidates/${toQuery({ search })}`, options),
  linkUserAccount: (code, userId) =>
    api.post(`/hcm/employees/${encodeURIComponent(code)}/user-account/link/`, { user_id: userId }),
};
