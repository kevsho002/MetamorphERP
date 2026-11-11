import { useCallback, useEffect, useRef, useState } from "react";
import { useClientConfig } from "../../app/ClientConfigContext.jsx";
import { useAuth } from "../../auth/AuthContext.jsx";
import { api, lastServerContactAt } from "../../services/apiClient.js";

const ACTIVITY_EVENTS = ["pointerdown", "keydown", "wheel", "touchstart", "mousemove"];
const PING_EVERY_MS = 2 * 60 * 1000; // si hay actividad sin llamadas a la API, se avisa al servidor
const TICK_MS = 1000;

/**
 * Cierre por inactividad en el navegador, alineado con la política del servidor
 * (parámetros de sesión del /admin/). Muestra una cuenta regresiva antes del cierre
 * con «Seguir conectado». El servidor aplica la misma regla de forma independiente.
 */
export default function SessionWatcher() {
  const { config } = useClientConfig();
  const { logout } = useAuth();
  const lastActivity = useRef(Date.now());
  const [remaining, setRemaining] = useState(null); // segundos para el cierre (solo durante el aviso)

  const idleMs = config.idle_timeout_seconds * 1000;
  const warnMs = Math.min(config.idle_warning_seconds * 1000, idleMs / 2);

  const keepAlive = useCallback(async () => {
    lastActivity.current = Date.now();
    setRemaining(null);
    try {
      await api.get("/auth/me/"); // cuenta como actividad en el servidor
    } catch {
      // Si la sesión ya expiró, AuthContext recibe el evento y muestra el login.
    }
  }, []);

  useEffect(() => {
    let lastMark = 0;
    const onActivity = () => {
      const now = Date.now();
      if (now - lastMark < 1000) return; // throttle
      lastMark = now;
      if (remaining !== null) return; // durante el aviso solo cuenta el botón explícito
      lastActivity.current = now;
      if (now - lastServerContactAt() > PING_EVERY_MS) {
        api.get("/auth/me/").catch(() => {});
      }
    };
    ACTIVITY_EVENTS.forEach((name) => window.addEventListener(name, onActivity, { passive: true }));
    return () => ACTIVITY_EVENTS.forEach((name) => window.removeEventListener(name, onActivity));
  }, [remaining]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const idleFor = Date.now() - lastActivity.current; // solo interacciones del usuario
      if (idleFor >= idleMs) {
        window.clearInterval(timer);
        logout("Su sesión se cerró por inactividad. Inicie sesión de nuevo.");
      } else if (idleFor >= idleMs - warnMs) {
        setRemaining(Math.ceil((idleMs - idleFor) / 1000));
      } else if (remaining !== null) {
        setRemaining(null);
      }
    }, TICK_MS);
    return () => window.clearInterval(timer);
  }, [idleMs, warnMs, logout, remaining]);

  if (remaining === null) return null;
  return (
    <div className="modal-backdrop" role="presentation">
      <div className="modal modal--sm" role="alertdialog" aria-modal="true" aria-labelledby="idle-title" aria-describedby="idle-desc">
        <h2 id="idle-title" className="section-title">¿Sigue ahí?</h2>
        <p id="idle-desc">
          Por seguridad, su sesión se cerrará en <strong>{remaining} s</strong> por inactividad.
        </p>
        <div className="actions">
          <button type="button" className="button" onClick={keepAlive} autoFocus>
            Seguir conectado
          </button>
          <button type="button" className="button button--ghost" onClick={() => logout()}>
            Cerrar sesión
          </button>
        </div>
      </div>
    </div>
  );
}
