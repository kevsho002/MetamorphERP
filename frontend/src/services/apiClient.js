/**
 * Cliente HTTP único para la API REST de Metamorph.
 * - Base relativa (/api/v1): funciona con el proxy de Vite y en despliegue unificado.
 * - Autenticación por sesión de Django: la cookie HttpOnly viaja sola
 *   (mismo origen); en métodos no seguros se envía el token CSRF en X-CSRFToken.
 */
export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
const CSRF_COOKIE = "metamorph_csrftoken";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
    this.code = body && typeof body === "object" ? body.code : undefined;
  }
}

/**
 * Eventos globales del cliente web (los escuchan AuthContext y el layout):
 * - metamorph:session-expired  -> la política de sesión cerró la sesión (inactividad / duración).
 * - metamorph:maintenance      -> el sistema está en mantenimiento (solo administradores operan).
 */
export const SESSION_EXPIRED_EVENT = "metamorph:session-expired";
export const MAINTENANCE_EVENT = "metamorph:maintenance";

// Última respuesta del servidor (la usa el vigilante de inactividad para no hacer pings innecesarios).
let lastServerContact = Date.now();
export const lastServerContactAt = () => lastServerContact;

function broadcast(error) {
  if (typeof window === "undefined") return;
  if (error.status === 401 && error.code === "session_expired") {
    window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT, { detail: { message: error.message } }));
  } else if (error.status === 503 && error.code === "maintenance") {
    window.dispatchEvent(new CustomEvent(MAINTENANCE_EVENT, { detail: { message: error.message } }));
  }
}

function readCookie(name) {
  const match = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null;
}

/** Garantiza que exista la cookie CSRF (Django la emite en GET /auth/csrf/). */
export async function ensureCsrfToken() {
  if (!readCookie(CSRF_COOKIE)) {
    await fetch(`${API_BASE}/auth/csrf/`, { credentials: "same-origin" });
  }
  return readCookie(CSRF_COOKIE);
}

function firstError(payload) {
  if (!payload || typeof payload !== "object") return null;
  if (payload.detail) return payload.detail;
  const [field, messages] = Object.entries(payload)[0] ?? [];
  if (!field) return null;
  const message = Array.isArray(messages) ? messages[0] : messages;
  return field === "non_field_errors" ? message : `${field}: ${message}`;
}

/** Convierte {a: 1, b: "", c: null} en "?a=1" (omite vacíos). */
export function toQuery(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  });
  const text = query.toString();
  return text ? `?${text}` : "";
}

/** URL absoluta de la API (para enlaces de descarga que usan la cookie de sesión). */
export const apiUrl = (path) => `${API_BASE}${path}`;

export async function apiRequest(path, { method = "GET", body, signal, headers = {} } = {}) {
  const unsafe = !SAFE_METHODS.has(method);
  const csrfToken = unsafe ? await ensureCsrfToken() : null;
  // FormData (archivos): el navegador arma el multipart y su boundary; no se fija Content-Type.
  const isForm = typeof FormData !== "undefined" && body instanceof FormData;

  const response = await fetch(`${API_BASE}${path}`, {
    method,
    signal,
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...(body !== undefined && !isForm ? { "Content-Type": "application/json" } : {}),
      ...(csrfToken ? { "X-CSRFToken": csrfToken } : {}),
      ...headers,
    },
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  });

  lastServerContact = Date.now();
  if (response.status === 204) return null;
  const isJson = response.headers.get("content-type")?.includes("application/json");
  const payload = isJson ? await response.json() : await response.text();

  if (!response.ok) {
    const detail = isJson ? firstError(payload) ?? payload?.error : payload;
    const error = new ApiError(detail || `HTTP ${response.status}`, response.status, payload);
    broadcast(error);
    throw error;
  }
  return payload;
}

export const api = {
  get: (path, options) => apiRequest(path, { ...options, method: "GET" }),
  post: (path, body, options) => apiRequest(path, { ...options, method: "POST", body }),
  put: (path, body, options) => apiRequest(path, { ...options, method: "PUT", body }),
  patch: (path, body, options) => apiRequest(path, { ...options, method: "PATCH", body }),
  delete: (path, options) => apiRequest(path, { ...options, method: "DELETE" }),
};
