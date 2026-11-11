import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext.jsx";
import { fmtDuration } from "../../modules/acd/api.js";
import { useAgentPresence, useTicker } from "../../modules/acd/AgentPresenceContext.jsx";

const OFFLINE_COLOR = "#94a3b8";
const canHover = () => typeof window !== "undefined" && window.matchMedia?.("(hover: hover) and (pointer: fine)").matches;
const INLINE_SUBMENUS = "(max-width: 640px)"; // debe coincidir con la media query de layout.css
const VIEWPORT_MARGIN = 8;

/** Cronómetro hh:mm:ss desde `since` (ISO), corregido con el reloj del servidor. */
export function Elapsed({ since, offset = 0, maxMinutes = null, className = "" }) {
  const now = useTicker(Boolean(since));
  if (!since) return null;
  const ms = now + offset - new Date(since).getTime();
  const over = maxMinutes && ms > maxMinutes * 60_000;
  return (
    <span className={`${className}${over ? " is-over" : ""}`} title={over ? `Excede el máximo de ${maxMinutes} min` : undefined}>
      {fmtDuration(ms)}
    </span>
  );
}

function initials(user) {
  const base = (user?.employee_name || user?.display_name || user?.username || "?").trim();
  const parts = base.split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase() || "?";
}

/** Foto circular (o iniciales) con el indicador del estado ACD actual. */
export function Avatar({ user, color, size = "md", statusLabel }) {
  const [broken, setBroken] = useState(false);
  const src = !broken ? user?.photo_url : null;
  return (
    <span className={`avatar avatar--${size}`} style={{ "--status-color": color }}>
      {src ? <img className="avatar__img" src={src} alt="" onError={() => setBroken(true)} /> : <span className="avatar__initials">{initials(user)}</span>}
      {statusLabel !== undefined && <span className="avatar__status" title={statusLabel} aria-hidden="true" />}
    </span>
  );
}

/** Botón principal de turno: «Iniciar Tiempo en Turno» (Available) o finalizar (Offline). */
function ShiftButton() {
  const p = useAgentPresence();
  if (!p.enabled || p.loading || (!p.data && !p.error)) return null;
  if (!p.loggedIn) {
    return (
      <button
        type="button"
        className="shift-button"
        disabled={p.busy || !p.canOperate}
        title={p.canOperate ? "Inicia su sesión de agente en estado Available" : "No pertenece a un grupo ACD activo: pida a Workforce que lo asigne."}
        onClick={() => p.login()}
      >
        <span className="shift-button__icon" aria-hidden="true">▶</span>
        <span className="shift-button__text">Iniciar Tiempo en Turno</span>
      </button>
    );
  }
  const end = () => {
    if (window.confirm("¿Finalizar su tiempo en turno? Pasará a Offline y se registrará el tiempo trabajado.")) p.logout();
  };
  return (
    <button type="button" className="shift-button shift-button--on" disabled={p.busy} onClick={end} title="Finalizar tiempo en turno (Offline)">
      <span className="shift-button__icon" aria-hidden="true">■</span>
      <span className="shift-button__text">
        <span className="shift-button__word">En turno </span>
        <Elapsed since={p.data.session?.login_at} offset={p.offset} className="shift-button__timer" />
      </span>
      <span className="shift-button__end">Finalizar</span>
    </button>
  );
}

/** Mueve el foco entre los elementos hermanos de un menú (flechas arriba/abajo, Inicio, Fin). */
function focusSibling(target, key) {
  const list = target.closest("[role=menu]");
  if (!list) return false;
  const items = [...list.querySelectorAll(":scope > li > [role=menuitem]")].filter((el) => !el.disabled);
  const i = items.indexOf(target);
  const next = { ArrowDown: items[i + 1] ?? items[0], ArrowUp: items[i - 1] ?? items[items.length - 1], Home: items[0], End: items[items.length - 1] }[key];
  if (!next) return false;
  next.focus();
  return true;
}

/**
 * Submenú en cascada con posición fija calculada contra la ventana: se abre a la izquierda del elemento (el panel
 * está pegado al borde derecho) y, si no cabe, a la derecha; verticalmente se desplaza para no salirse por abajo y,
 * si es más alto que la ventana, su lista hace scroll interno. Al ser `position: fixed`, el scroll del panel no lo
 * recorta. Se recalcula al hacer scroll (panel o submenú padre) y al redimensionar. En pantallas angostas no se
 * posiciona: el CSS lo muestra en línea (acordeón).
 */
function Flyout({ label, children }) {
  const ref = useRef(null);

  useLayoutEffect(() => {
    const el = ref.current;
    const anchor = el?.parentElement;
    if (!el || !anchor) return undefined;
    let frame = 0;
    const place = () => {
      const st = el.style;
      if (window.matchMedia?.(INLINE_SUBMENUS).matches) {
        st.cssText = "";
        el.removeAttribute("data-side");
        return;
      }
      const vw = document.documentElement.clientWidth;
      const vh = window.innerHeight;
      const a = anchor.getBoundingClientRect();
      const { width, height } = el.getBoundingClientRect();
      let side = "left";
      let x = a.left - width; // el ancho incluye el relleno que cubre el hueco con el elemento
      if (x < VIEWPORT_MARGIN) {
        const right = a.right;
        if (right + width <= vw - VIEWPORT_MARGIN) {
          side = "right";
          x = right;
        } else {
          x = Math.max(VIEWPORT_MARGIN, Math.min(x, vw - VIEWPORT_MARGIN - width));
        }
      }
      let y = a.top - 5;
      if (y + height > vh - VIEWPORT_MARGIN) y = vh - VIEWPORT_MARGIN - height;
      y = Math.max(VIEWPORT_MARGIN, y);
      el.setAttribute("data-side", side);
      st.left = `${Math.round(x)}px`;
      st.top = `${Math.round(y)}px`;
    };
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(place);
    };
    place();
    window.addEventListener("resize", schedule);
    document.addEventListener("scroll", schedule, true); // captura: también el scroll interno del panel y submenús
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", schedule);
      document.removeEventListener("scroll", schedule, true);
    };
  }, []);

  return (
    <div ref={ref} className="status-flyout">
      <ul className="status-menu status-menu--sub" role="menu" aria-label={label}>
        {children}
      </ul>
    </div>
  );
}

/**
 * Lista única de estados → auxiliares → sub-auxiliares. Con mouse, el submenú en cascada se despliega al pasar el
 * cursor; con toque o teclado, al hacer clic / Enter / flecha. En pantallas angostas los submenús se abren en línea.
 */
function StatusCascade({ onDone }) {
  const p = useAgentPresence();
  const [openPrimary, setOpenPrimary] = useState(null);
  const [openAux, setOpenAux] = useState(null);
  const disabled = !p.loggedIn || p.busy;
  const current = p.current;

  const choose = async (primary, aux) => {
    const ok = await p.setStatus(primary, aux);
    if (ok) onDone();
  };
  const hoverOpen = (fn) => () => canHover() && !disabled && fn();
  const keyNav = (e, { onOpen, onClose } = {}) => {
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key) && focusSibling(e.currentTarget, e.key)) e.preventDefault();
    else if (e.key === "ArrowLeft" && onOpen) {
      e.preventDefault();
      onOpen();
      requestAnimationFrame(() => e.target.parentElement?.querySelector("[role=menu] [role=menuitem]")?.focus());
    } else if (e.key === "ArrowRight" && onClose) {
      e.preventDefault();
      onClose();
    }
  };

  return (
    <ul className="status-menu" role="menu" aria-label="Cambiar estado">
      {p.options.map((o) => {
        const hasAux = o.aux_codes.length > 0;
        const isOpen = openPrimary === o.code;
        const isCurrent = current?.primary_status === o.code;
        const backToPrimary = () => {
          setOpenPrimary(null);
          document.getElementById(`status-${o.code}`)?.focus();
        };
        return (
          <li key={o.code} className="status-menu__li" onMouseEnter={hoverOpen(() => { setOpenPrimary(hasAux ? o.code : null); setOpenAux(null); })}>
            <button
              id={`status-${o.code}`}
              type="button"
              role="menuitem"
              className={`status-menu__item${isOpen ? " is-open" : ""}${isCurrent ? " is-current" : ""}`}
              style={{ "--status-color": o.color }}
              disabled={disabled}
              aria-haspopup={hasAux ? "menu" : undefined}
              aria-expanded={hasAux ? isOpen : undefined}
              onClick={() => {
                if (!hasAux) return choose(o.code);
                setOpenAux(null);
                setOpenPrimary(isOpen && !canHover() ? null : o.code);
                return undefined;
              }}
              onKeyDown={(e) => keyNav(e, hasAux ? { onOpen: () => setOpenPrimary(o.code) } : {})}
            >
              <span className="status-menu__dot" aria-hidden="true" />
              <span className="status-menu__text">
                <span className="status-menu__label">{o.label}</span>
                <span className="status-menu__name">{o.name}</span>
              </span>
              {isCurrent && !hasAux && <span className="status-menu__check" aria-label="estado actual">✓</span>}
              {hasAux && <span className="status-menu__chevron" aria-hidden="true">‹</span>}
            </button>
            {hasAux && isOpen && (
              <Flyout label={`Auxiliares de ${o.label}`}>
                <li className="status-menu__li" onMouseEnter={hoverOpen(() => setOpenAux(null))}>
                  <button type="button" role="menuitem" className={`status-menu__item${isCurrent && !current?.aux_code ? " is-current" : ""}`}
                    style={{ "--status-color": o.color }} disabled={disabled}
                    onClick={() => choose(o.code)} onKeyDown={(e) => keyNav(e, { onClose: backToPrimary })}>
                    <span className="status-menu__text">
                      <span className="status-menu__label">{o.label}</span>
                      <span className="status-menu__name">sin auxiliar</span>
                    </span>
                  </button>
                </li>
                {o.aux_codes.map((a) => {
                  const hasKids = a.children.length > 0;
                  const auxOpen = openAux === a.code;
                  const auxCurrent = isCurrent && (current?.aux_code === a.code || a.children.some((c) => c.code === current?.aux_code));
                  return (
                    <li key={a.code} className="status-menu__li" onMouseEnter={hoverOpen(() => setOpenAux(hasKids ? a.code : null))}>
                      <button
                        id={`aux-${a.code}`}
                        type="button"
                        role="menuitem"
                        className={`status-menu__item${auxOpen ? " is-open" : ""}${auxCurrent ? " is-current" : ""}`}
                        style={{ "--status-color": o.color }}
                        disabled={disabled}
                        aria-haspopup={hasKids ? "menu" : undefined}
                        aria-expanded={hasKids ? auxOpen : undefined}
                        onClick={() => (hasKids ? setOpenAux(auxOpen && !canHover() ? null : a.code) : choose(o.code, a.code))}
                        onKeyDown={(e) => keyNav(e, { onOpen: hasKids ? () => setOpenAux(a.code) : undefined, onClose: backToPrimary })}
                      >
                        <span className="status-menu__text">
                          <span className="status-menu__label">{a.name}</span>
                          {(a.max_minutes || !a.is_paid) && (
                            <span className="status-menu__name">
                              {[a.max_minutes ? `máx. ${a.max_minutes} min` : null, a.is_paid ? null : "no pagado"].filter(Boolean).join(" · ")}
                            </span>
                          )}
                        </span>
                        {auxCurrent && !hasKids && <span className="status-menu__check" aria-label="estado actual">✓</span>}
                        {hasKids && <span className="status-menu__chevron" aria-hidden="true">‹</span>}
                      </button>
                      {hasKids && auxOpen && (
                        <Flyout label={`Sub-auxiliares de ${a.name}`}>
                          {a.children.map((c) => (
                            <li key={c.code} className="status-menu__li">
                              <button type="button" role="menuitem"
                                className={`status-menu__item${isCurrent && current?.aux_code === c.code ? " is-current" : ""}`}
                                style={{ "--status-color": o.color }} disabled={disabled}
                                onClick={() => choose(o.code, c.code)}
                                onKeyDown={(e) => keyNav(e, { onClose: () => { setOpenAux(null); document.getElementById(`aux-${a.code}`)?.focus(); } })}>
                                <span className="status-menu__text">
                                  <span className="status-menu__label">{c.name}</span>
                                  {c.max_minutes ? <span className="status-menu__name">máx. {c.max_minutes} min</span> : null}
                                </span>
                                {isCurrent && current?.aux_code === c.code && <span className="status-menu__check" aria-label="estado actual">✓</span>}
                              </button>
                            </li>
                          ))}
                        </Flyout>
                      )}
                    </li>
                  );
                })}
              </Flyout>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Zona derecha de la barra superior (estilo Genesys Cloud): botón de turno + avatar circular con el indicador del estado.
 * Al hacer clic en el avatar se abre el panel con el estado actual, la lista unificada de estados / auxiliares y la cuenta.
 */
export default function UserPresenceMenu() {
  const { user, logout } = useAuth();
  const p = useAgentPresence();
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  const triggerRef = useRef(null);
  const location = useLocation();

  const close = useCallback((focus = false) => {
    setOpen(false);
    if (focus) triggerRef.current?.focus();
  }, []);

  useEffect(() => close(), [location.pathname, close]);
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => !rootRef.current?.contains(e.target) && close();
    const onKey = (e) => e.key === "Escape" && close(true);
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);

  const current = p.current;
  const color = current?.color ?? OFFLINE_COLOR;
  const statusText = p.enabled
    ? current
      ? `${current.primary_label}${current.secondary_status ? ` · ${current.secondary_status}` : ""}`
      : "Offline"
    : undefined;

  return (
    <div className="presence" ref={rootRef}>
      <ShiftButton />
      <button
        ref={triggerRef}
        type="button"
        className="presence__trigger"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls="presence-panel"
        aria-label={`Menú de ${user?.display_name ?? "usuario"}${statusText ? ` — estado: ${statusText}` : ""}`}
        title={statusText ? `${user?.display_name} · ${statusText}` : user?.display_name}
        onClick={() => setOpen((v) => !v)}
      >
        <Avatar user={user} color={color} statusLabel={p.enabled ? statusText : undefined} />
      </button>

      {open && (
        <div id="presence-panel" className="presence__panel" role="dialog" aria-label="Estado y cuenta">
          <div className="presence__head">
            <Avatar user={user} color={color} size="lg" statusLabel={p.enabled ? statusText : undefined} />
            <div className="presence__who">
              <strong>{user?.employee_name || user?.display_name}</strong>
              <span className="muted small">
                {user?.role_label}
                {user?.employee_code ? ` · ${user.employee_code}` : ""}
              </span>
            </div>
          </div>

          {p.enabled && (
            <div className="presence__now" style={{ "--status-color": color }}>
              <span className="acd-pill">{statusText}</span>
              {current && <Elapsed since={current.start_at} offset={p.offset} maxMinutes={current.max_minutes} className="presence__timer" />}
              {p.data?.group && <span className="muted small presence__group">Grupo {p.data.group.name}</span>}
            </div>
          )}

          {p.enabled && p.error && <p className="error-box small">{p.error}</p>}
          {p.enabled && p.data && !p.canOperate && (
            <p className="presence__hint">No pertenece a un grupo ACD activo. Pida a Workforce que lo asigne para usar estados y auxiliares.</p>
          )}
          {p.enabled && p.canOperate && (
            <>
              {!p.loggedIn && (
                <div className="presence__hint">
                  <span>Inicie su tiempo en turno para elegir un estado.</span>
                  <button type="button" className="button button--sm" disabled={p.busy} onClick={() => p.login()}>
                    Iniciar Tiempo en Turno
                  </button>
                </div>
              )}
              <StatusCascade onDone={() => close(true)} />
            </>
          )}
          {!p.enabled && <p className="presence__hint muted">Su usuario no tiene expediente de agente vinculado: el control de estados ACD no aplica.</p>}

          <div className="presence__links">
            {p.enabled && (
              <NavLink to="/acd/console" className="presence__link">
                Mi estado (consola del agente)
              </NavLink>
            )}
            {p.loggedIn ? (
              <>
                <button type="button" className="presence__link" disabled={p.busy}
                  onClick={async () => { if (await p.logout()) logout(); }}>
                  Finalizar turno y salir del sistema
                </button>
                <button type="button" className="presence__link presence__link--muted" onClick={() => logout()}>
                  Salir sin finalizar el turno
                </button>
              </>
            ) : (
              <button type="button" className="presence__link" onClick={() => logout()}>
                Cerrar sesión del sistema
              </button>
            )}
          </div>
        </div>
      )}

      {p.notice && (
        <div className={`presence__toast${p.notice.ok ? "" : " presence__toast--error"}`} role="status">
          <span>{p.notice.text}</span>
          <button type="button" className="presence__toast-close" aria-label="Cerrar aviso" onClick={p.dismissNotice}>
            ×
          </button>
        </div>
      )}
    </div>
  );
}
