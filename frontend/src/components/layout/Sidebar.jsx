import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";

const PIN_KEY = "metamorph.sidebar.pinned";
const OPEN_DELAY_MS = 120; // evita que se abra al cruzar el menú con el cursor de camino a otro lado
const CLOSE_DELAY_MS = 280;

/** Íconos de línea (24×24) por módulo; un módulo nuevo sin ícono muestra sus iniciales. */
const ICONS = {
  hcm: "M16 19v-1a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v1M9 10a3 3 0 1 0 0-6 3 3 0 0 0 0 6M22 19v-1a4 4 0 0 0-3-3.9M16 4.1a3 3 0 0 1 0 5.8",
  roster: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  "general-ids": "M3 5h18v14H3zM7 15c.6-1.5 1.7-2 2.5-2s1.9.5 2.5 2M9.5 11a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3M15 9h3M15 13h3",
  "personnel-actions": "M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M9 15l2 2 4-4",
  scheduling: "M4 5h16v15H4zM4 10h16M9 3v4M15 3v4M8 14h2M14 14h2M8 17h2",
  acd: "M4 14v-2a8 8 0 0 1 16 0v2M4 14a2 2 0 0 1 2-2h1v6H6a2 2 0 0 1-2-2zM20 14a2 2 0 0 0-2-2h-1v6h1a2 2 0 0 0 2-2zM18 18a4 4 0 0 1-4 3h-2",
  wfm: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  payroll: "M3 6h18v12H3zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6M6 9v.01M18 15v.01",
  system: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2V21a2 2 0 1 1-4 0v-.1A1.7 1.7 0 0 0 7 19.4l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.7 1.7 0 0 0 3 13.7H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 7l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.7 1.7 0 0 0 10.3 3V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 2.9 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0 1.2 2.9h.1a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1",
};

function ModuleIcon({ module }) {
  const d = ICONS[module.id];
  if (!d) {
    const letters = module.label.replace(/[^A-Za-zÁÉÍÓÚÑáéíóúñ ]/g, "").split(/\s+/).filter(Boolean);
    return <span className="sidebar__icon sidebar__icon--text">{letters.slice(0, 2).map((w) => w[0]).join("").toUpperCase()}</span>;
  }
  return (
    <svg className="sidebar__icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

function readPinned() {
  try {
    return window.localStorage.getItem(PIN_KEY) !== "0";
  } catch {
    return true;
  }
}

/** Preferencia «menú fijo» del usuario (se recuerda en este navegador). */
export function useSidebarPin() {
  const [pinned, setPinned] = useState(readPinned);
  const toggle = useCallback(() => {
    setPinned((v) => {
      try {
        window.localStorage.setItem(PIN_KEY, v ? "0" : "1");
      } catch {
        // almacenamiento bloqueado: la preferencia dura solo esta visita
      }
      return !v;
    });
  }, []);
  return [pinned, toggle];
}

/**
 * Menú lateral. En escritorio puede estar fijo (pin) o contraído a una barra de íconos que se expande sobre el
 * contenido al pasar el cursor o al recibir el foco del teclado, y se vuelve a contraer al salir. En móvil es el
 * panel deslizable de siempre (botón ☰).
 */
export default function Sidebar({ modules, hasPermission, pinned, onTogglePin, mobileOpen }) {
  const [expanded, setExpanded] = useState(false);
  const timer = useRef(null);
  const location = useLocation();

  const schedule = (value, delay) => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setExpanded(value), delay);
  };
  useEffect(() => () => clearTimeout(timer.current), []);
  // Al navegar desde el menú expandido por hover, este se contrae.
  useEffect(() => {
    clearTimeout(timer.current);
    setExpanded(false);
  }, [location.pathname]);

  const collapsed = !pinned && !expanded;
  const peek = !pinned && expanded;
  const className = ["sidebar", mobileOpen && "sidebar--open", collapsed && "sidebar--collapsed", peek && "sidebar--peek"].filter(Boolean).join(" ");

  return (
    <nav
      id="sidebar"
      className={className}
      aria-label="Módulos"
      onMouseEnter={() => !pinned && schedule(true, OPEN_DELAY_MS)}
      onMouseLeave={() => !pinned && schedule(false, CLOSE_DELAY_MS)}
      onFocus={() => !pinned && schedule(true, 0)}
      onBlur={(e) => !pinned && !e.currentTarget.contains(e.relatedTarget) && schedule(false, 0)}
      onKeyDown={(e) => e.key === "Escape" && peek && (e.currentTarget.ownerDocument.activeElement?.blur(), setExpanded(false))}
    >
      <div className="sidebar__panel">
        <div className="sidebar__head">
          <button
            type="button"
            className={`sidebar__pin${pinned ? " is-pinned" : ""}`}
            onClick={onTogglePin}
            aria-pressed={pinned}
            title={pinned ? "Contraer menú (se abrirá al pasar el cursor)" : "Fijar menú expandido"}
            aria-label={pinned ? "Desfijar y contraer el menú" : "Fijar el menú expandido"}
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"
              strokeLinejoin="round" aria-hidden="true">
              {pinned ? <path d="M15 18l-6-6 6-6M20 18l-6-6 6-6" /> : <path d="M12 17v5M9 3h6l-1 6 3 3v2H7v-2l3-3z" />}
            </svg>
          </button>
          <span className="sidebar__head-label">{pinned ? "Menú fijo" : "Menú"}</span>
        </div>
        {modules.map((m) => {
          const items = m.menu.filter((item) => hasPermission(item.permission));
          const activeModule = items.some((item) => (item.end ? location.pathname === item.to : location.pathname.startsWith(item.to)));
          return (
            <section key={m.id} className={`sidebar__group${activeModule ? " is-active" : ""}`}>
              <h2 className="sidebar__title" title={m.label}>
                <ModuleIcon module={m} />
                <span className="sidebar__title-text">{m.label}</span>
              </h2>
              <div className="sidebar__links">
                {items.map((item) => (
                  <NavLink key={item.to} to={item.to} end={item.end} className="sidebar__link">
                    {item.label}
                  </NavLink>
                ))}
              </div>
            </section>
          );
        })}
        {modules.length === 0 && <p className="muted sidebar__empty">Su rol aún no tiene módulos habilitados.</p>}
      </div>
    </nav>
  );
}
