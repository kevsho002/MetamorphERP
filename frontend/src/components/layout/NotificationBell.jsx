import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { markNotifications, timeAgo, useNotifications } from "../../app/notifications.js";

const SEVERITY = { warn: "notif__dot--warn", danger: "notif__dot--danger" };

/** Fase 22 — Campana de la barra superior: notificaciones operativas en tiempo real (sondeo de 30 s). */
export default function NotificationBell() {
  const n = useNotifications();
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false);
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const go = (item) => {
    setOpen(false);
    if (!item.read) markNotifications([item.key]).catch(() => {});
    navigate(item.link);
  };
  const items = n.results.slice(0, 8);

  return (
    <div className="notif" ref={ref}>
      <button type="button" className="notif__button" aria-haspopup="true" aria-expanded={open}
        aria-label={`Notificaciones${n.unread ? `: ${n.unread} sin leer` : ""}`} onClick={() => setOpen((v) => !v)}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 9a6 6 0 1 1 12 0c0 6 2.5 7.5 2.5 7.5h-17S6 15 6 9" />
          <path d="M10 20a2 2 0 0 0 4 0" />
        </svg>
        {n.unread > 0 && <span className="notif__count">{n.unread > 99 ? "99+" : n.unread}</span>}
      </button>
      {open && (
        <div className="notif__panel" role="dialog" aria-label="Notificaciones">
          <div className="notif__head">
            <span>Notificaciones</span>
            {n.unread > 0 && (
              <button type="button" className="link-button small" onClick={() => markNotifications([], true).catch(() => {})}>
                Marcar todas como leídas
              </button>
            )}
          </div>
          {n.error && <p className="error-box">{n.error}</p>}
          {!n.loading && items.length === 0 && <p className="empty notif__foot">Sin novedades. Todo al día.</p>}
          <ul className="notif__list">
            {items.map((i) => (
              <li key={i.key}>
                <a href={i.link} className={`notif__item${i.read ? " is-read" : ""}`} onClick={(e) => { e.preventDefault(); go(i); }}>
                  <span className={`notif__dot ${SEVERITY[i.severity] ?? ""}`} aria-hidden="true" />
                  <span>
                    <span className="notif__title">{i.title}</span>
                    <span className="notif__body">{i.body}</span>
                    <span className="notif__body">{timeAgo(i.at)}</span>
                  </span>
                </a>
              </li>
            ))}
          </ul>
          <div className="notif__foot">
            <Link to="/portal/notifications" onClick={() => setOpen(false)}>
              Ver el centro de notificaciones ({n.total})
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
