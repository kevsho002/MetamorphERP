import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, SESSION_EXPIRED_EVENT } from "../services/apiClient.js";

/**
 * Sesión del usuario (cookie HttpOnly de Django; el SPA nunca ve credenciales ni tokens).
 * status: loading | authenticated | anonymous
 */
const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState("loading");
  // Aviso para la pantalla de login (p. ej. «Su sesión se cerró por inactividad»).
  const [notice, setNotice] = useState(null);

  const refresh = useCallback(async (signal) => {
    try {
      const me = await api.get("/auth/me/", { signal });
      setUser(me);
      setStatus("authenticated");
    } catch (err) {
      if (err.name === "AbortError") return;
      setUser(null);
      setStatus("anonymous");
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  // La política de sesión del servidor cerró la sesión: se vuelve al login con el motivo.
  useEffect(() => {
    const onExpired = (e) => {
      setUser(null);
      setStatus("anonymous");
      setNotice(e.detail?.message ?? "Su sesión expiró. Inicie sesión de nuevo.");
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
  }, []);

  const login = useCallback(async (username, password) => {
    const me = await api.post("/auth/login/", { username, password });
    setNotice(null);
    setUser(me);
    setStatus("authenticated");
    return me;
  }, []);

  /** `reason`: texto opcional que verá la pantalla de login (cierre por inactividad en el navegador). */
  const logout = useCallback(async (reason) => {
    try {
      await api.post("/auth/logout/");
    } catch {
      // La sesión ya pudo haber expirado en el servidor: igual se limpia el estado local.
    } finally {
      setUser(null);
      setStatus("anonymous");
      setNotice(typeof reason === "string" ? reason : null);
    }
  }, []);

  const changePassword = useCallback(async (currentPassword, newPassword) => {
    const me = await api.post("/auth/password/change/", {
      current_password: currentPassword,
      new_password: newPassword,
    });
    setUser(me);
    return me;
  }, []);

  const value = useMemo(
    () => ({
      user,
      status,
      notice,
      isAdmin: Boolean(user && (user.is_superuser || user.role === "ADMIN")),
      login,
      logout,
      changePassword,
      refresh,
      hasPermission: (permission) => !permission || Boolean(user?.permissions?.includes(permission)),
    }),
    [user, status, notice, login, logout, changePassword, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth debe usarse dentro de <AuthProvider>");
  return ctx;
}
