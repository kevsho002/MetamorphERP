import { api, apiUrl, toQuery } from "../../services/apiClient.js";

const enc = encodeURIComponent;

/** Planilla automática y control de boletas físicas (backend: apps/payroll, Fase 20). */
export const payrollApi = {
  catalogs: (options) => api.get("/payroll/catalogs/", options),
  periods: (params, options) => api.get(`/payroll/periods/${toQuery(params)}`, options),
  runs: (params, options) => api.get(`/payroll/runs/${toQuery(params)}`, options),
  calculate: (periodId) => api.post("/payroll/runs/", { period_id: periodId }),
  run: (id, params, options) => api.get(`/payroll/runs/${id}/${toQuery(params)}`, options),
  runCsvUrl: (id, params) => apiUrl(`/payroll/runs/${id}/${toQuery({ ...params, export: "csv" })}`),
  breakdown: (id, code, options) => api.get(`/payroll/runs/${id}/employees/${enc(code)}/`, options),
  runAction: (id, action, payload = {}) => api.post(`/payroll/runs/${id}/${action}/`, payload),
  settings: (options) => api.get("/payroll/settings/", options),
  createSetting: (payload) => api.post("/payroll/settings/", payload),
  updateSetting: (id, payload) => api.patch(`/payroll/settings/${id}/`, payload),
  updateConcept: (code, payload) => api.patch(`/payroll/concepts/${enc(code)}/`, payload),
  newDeductionVersion: (id, payload) => api.post(`/payroll/deduction-types/${id}/versions/`, payload),
  payslips: (params, options) => api.get(`/payroll/payslips/${toQuery(params)}`, options),
  payslip: (id, options) => api.get(`/payroll/payslips/${id}/`, options),
  // Fase 22: boletas en PDF (descarga formal; la sesión viaja en la cookie)
  payslipPdfUrl: (id) => apiUrl(`/payroll/payslips/${id}/pdf/`),
  employeePdfUrl: (runId, code) => apiUrl(`/payroll/runs/${runId}/employees/${code}/pdf/`),
  myPayslipPdfUrl: (kind, id) => apiUrl(`/payroll/me/payslips/${kind}/${id}/pdf/`),
  printable: (params, options) => api.get(`/payroll/payslips/print/${toQuery(params)}`, options),
  payslipAction: (payload) => api.post("/payroll/payslips/actions/", payload),
  batches: (params, options) => api.get(`/payroll/batches/${toQuery(params)}`, options),
  updateBatch: (id, payload) => api.patch(`/payroll/batches/${id}/`, payload),
  // Fase 21: pre-cierre, portal, excepciones, reglas por cuenta, feriados y liquidaciones
  iterations: (id, options) => api.get(`/payroll/runs/${id}/iterations/`, options),
  myPayslips: (params, options) => api.get(`/payroll/me/payslips/${toQuery(params)}`, options),
  myCutoffs: (params, options) => api.get(`/payroll/me/cutoffs/${toQuery(params)}`, options), // Fase 27
  exceptions: (params, options) => api.get(`/payroll/exceptions/${toQuery(params)}`, options),
  reportException: (payload) => api.post("/payroll/exceptions/", payload),
  resolveException: (id, payload) => api.post(`/payroll/exceptions/${id}/resolve/`, payload),
  accountRules: (options) => api.get("/payroll/account-rules/", options),
  saveAccountRule: (clientId, payload) => api.patch(`/payroll/account-rules/${clientId}/`, payload),
  holidays: (params, options) => api.get(`/holidays/${toQuery(params)}`, options),
  createHoliday: (payload) => api.post("/holidays/", payload),
  updateHoliday: (id, payload) => api.patch(`/holidays/${id}/`, payload),
  deleteHoliday: (id) => api.delete(`/holidays/${id}/`),
  copyHolidayYear: (payload) => api.post("/holidays/copy-year/", payload), // Fase 23
  holidaySegments: (params, options) => api.get(`/holidays/segments/${toQuery(params)}`, options),
  generateHolidaySegments: (payload) => api.post("/holidays/segments/generate/", payload),
  settlements: (params, options) => api.get(`/payroll/settlements/${toQuery(params)}`, options),
  openSettlement: (payload) => api.post("/payroll/settlements/", payload),
  settlement: (id, options) => api.get(`/payroll/settlements/${id}/`, options),
  settlementAction: (id, action, payload = {}) => api.post(`/payroll/settlements/${id}/${action}/`, payload),
  settlementBatches: (options) => api.get("/payroll/settlement-batches/", options),
  createSettlementBatch: (payload) => api.post("/payroll/settlement-batches/", payload),
  settlementBatch: (id, options) => api.get(`/payroll/settlement-batches/${id}/`, options),
  settlementBatchAction: (id, action, payload = {}) => api.post(`/payroll/settlement-batches/${id}/${action}/`, payload),
};

export const SETTLEMENT_STATUS = {
  DRAFT: { label: "Borrador", cls: "badge--muted" },
  CALCULATED: { label: "Calculada", cls: "badge--info" },
  APPROVED: { label: "Aprobada", cls: "badge--ok" },
  PAID: { label: "Pagada", cls: "badge--ok" },
  CANCELLED: { label: "Anulada", cls: "badge--muted" },
};

export const RUN_STATUS = {
  DRAFT: { label: "Borrador", cls: "badge--muted" },
  CALCULATED: { label: "Calculada", cls: "badge--info" },
  APPROVED: { label: "Cerrada", cls: "badge--ok" },
  PAID: { label: "Pagada", cls: "badge--ok" },
  CANCELLED: { label: "Anulada", cls: "badge--muted" },
};

export const MONTHS = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];

/** Grupos de líneas de la boleta en el orden en que se imprimen. */
export const LINE_GROUPS = [
  { kinds: ["EARNING", "TIME_DISCOUNT"], title: "Devengado" },
  { kinds: ["LEGAL"], title: "Retenciones de ley" },
  { kinds: ["DEDUCTION"], title: "Otros descuentos autorizados" },
  { kinds: ["EMPLOYER"], title: "Aportes patronales (no se descuentan)" },
  { kinds: ["INFO"], title: "Insumos de tiempo (información)" },
];

export function num(value, digits = 2) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isNaN(n) ? String(value) : n.toLocaleString("es-SV", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function pct(rate) {
  if (rate === null || rate === undefined || rate === "") return "";
  return `${(Number(rate) * 100).toLocaleString("es-SV", { maximumFractionDigits: 3 })} %`;
}
