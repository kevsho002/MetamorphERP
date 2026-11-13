import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, MAINTENANCE_EVENT } from "../services/apiClient.js";
import { setBrand } from "./appearance.js";

/**
 * Configuración del cliente web que el administrador controla en /admin/
 * (GET /system/client-config/, público): mantenimiento, aviso general,
 * tiempos de sesión y límites de imágenes. Se refresca cada 5 minutos,
 * al volver a la pestaña y cuando la API responde «mantenimiento».
 */
const DEFAULTS = {
  maintenance_mode: false,
  maintenance_message: "",
  announcement: "",
  announcement_level: "info",
  idle_timeout_seconds: 1800,
  idle_warning_seconds: 60,
  max_session_hours: 8,
  max_document_mb: 5,
  allowed_image_types: ["image/png", "image/jpeg"],
};
const REFRESH_MS = 5 * 60 * 1000;

const ClientConfigContext = createContext({ config: DEFAULTS, refresh: () => {} });

export function ClientConfigProvider({ children }) {
  const [config, setConfig] = useState(DEFAULTS);

  const refresh = useCallback(async () => {
    try {
      const data = await api.get("/system/client-config/");
      setConfig({ ...DEFAULTS, ...data });
      setBrand(data.brand_palette, data.brand_accent); // Fase 22: paleta corporativa
    } catch {
      // Sin conexión: se conservan los últimos valores conocidos.
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, REFRESH_MS);
    const onFocus = () => document.visibilityState === "visible" && refresh();
    const onMaintenance = (e) =>
      setConfig((c) => ({ ...c, maintenance_mode: true, maintenance_message: e.detail?.message || c.maintenance_message }));
    document.addEventListener("visibilitychange", onFocus);
    window.addEventListener(MAINTENANCE_EVENT, onMaintenance);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onFocus);
      window.removeEventListener(MAINTENANCE_EVENT, onMaintenance);
    };
  }, [refresh]);

  const value = useMemo(() => ({ config, refresh }), [config, refresh]);
  return <ClientConfigContext.Provider value={value}>{children}</ClientConfigContext.Provider>;
}

export const useClientConfig = () => useContext(ClientConfigContext);
