import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "../../auth/AuthContext.jsx";
import { acdApi } from "./api.js";

/**
 * Estado ACD del usuario conectado, compartido por la barra superior (botón de turno + avatar con su menú de estados)
 * y la consola «Mi estado». Un solo origen de verdad: cualquier cambio hecho en uno se ve de inmediato en el otro.
 * Las horas las fija el servidor; `offset` corrige el reloj del navegador para los cronómetros.
 */
const AgentPresenceContext = createContext(null);

const REFRESH_MS = 60_000;

export function AgentPresenceProvider({ children }) {
  const { user, hasPermission } = useAuth();
  const enabled = Boolean(user?.employee_code) && hasPermission("acd.agent");
  const [state, setState] = useState({ loading: enabled, data: null, error: null });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const [offset, setOffset] = useState(0); // reloj del servidor − reloj del navegador
  const noticeTimer = useRef(null);

  const apply = useCallback((data) => {
    setOffset(new Date(data.server_time).getTime() - Date.now());
    setState({ loading: false, data, error: null });
  }, []);

  const reload = useCallback(
    (signal) =>
      acdApi
        .me({ signal })
        .then(apply)
        .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message })),
    [apply],
  );

  useEffect(() => {
    if (!enabled) {
      setState({ loading: false, data: null, error: null });
      return undefined;
    }
    const controller = new AbortController();
    reload(controller.signal);
    // Se refresca en segundo plano (cambios hechos por un supervisor, cierre forzado) solo con la pestaña visible.
    const timer = setInterval(() => document.visibilityState === "visible" && reload(), REFRESH_MS);
    const onVisible = () => document.visibilityState === "visible" && reload();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      controller.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [enabled, reload]);

  const flash = useCallback((next) => {
    setNotice(next);
    clearTimeout(noticeTimer.current);
    if (next) noticeTimer.current = setTimeout(() => setNotice(null), next.ok ? 5000 : 9000);
  }, []);
  useEffect(() => () => clearTimeout(noticeTimer.current), []);

  const run = useCallback(
    async (fn) => {
      setBusy(true);
      flash(null);
      try {
        const data = await fn();
        apply(data);
        flash({ ok: data.sync_status !== "ERROR", text: data.feedback });
        return data;
      } catch (err) {
        flash({ ok: false, text: err.message });
        return null;
      } finally {
        setBusy(false);
      }
    },
    [apply, flash],
  );

  const value = useMemo(() => {
    const data = state.data;
    return {
      enabled,
      loading: state.loading,
      error: state.error,
      data,
      offset,
      busy,
      notice,
      dismissNotice: () => flash(null),
      /** Puede operar su turno: tiene expediente, permiso acd.agent y un grupo ACD activo. */
      canOperate: Boolean(data?.group?.is_active),
      loggedIn: Boolean(data?.logged_in),
      current: data?.current ?? null,
      options: data?.options ?? [],
      reload,
      login: () => run(acdApi.login),
      logout: () => run(acdApi.logout),
      setStatus: (primary, aux) => run(() => acdApi.setStatus(primary, aux)),
    };
  }, [enabled, state, offset, busy, notice, flash, reload, run]);

  return <AgentPresenceContext.Provider value={value}>{children}</AgentPresenceContext.Provider>;
}

export function useAgentPresence() {
  const ctx = useContext(AgentPresenceContext);
  if (!ctx) throw new Error("useAgentPresence debe usarse dentro de <AgentPresenceProvider>");
  return ctx;
}

/** Hora actual (ms) que avanza cada segundo; úsese solo en componentes pequeños (cronómetros). */
export function useTicker(active = true) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return undefined;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}
