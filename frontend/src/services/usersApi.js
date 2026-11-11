import { api } from "./apiClient.js";

/** API de cuentas (apps/accounts): roles y acciones sobre una cuenta existente. */
export const usersApi = {
  roles: (options) => api.get("/roles/", options),
  resetPassword: (id) => api.post(`/users/${id}/reset-password/`),
  assignRole: (id, role) => api.post(`/users/${id}/role/`, { role }),
  activate: (id) => api.post(`/users/${id}/activate/`),
  deactivate: (id) => api.post(`/users/${id}/deactivate/`),
};
