import { useState } from "react";
import { Link } from "react-router-dom";
import { KIND_LABELS, markNotifications, refreshNotifications, timeAgo, useNotifications } from "../../../app/notifications.js";
import { formatDateTime } from "../../hcm/lib/format.js";

const SEVERITY = { warn: "notif__dot--warn", danger: "notif__dot--danger" };

/**
 * Fase 22 — Centro de notificaciones operativas: AP pendientes de su firma, solicitudes de planilla y de WFM, altas de
 * nuevos empleados bajo su jerarquía y el ausentismo (no-shows) del día. Se actualiza solo cada 30 segundos.
 */
export default function NotificationsPage() {
  const n = useNotifications();
  const [kind, setKind] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const rows = n.results.filter((i) => (!kind || i.kind === kind) && (!unreadOnly || !i.read));
  const kinds = Object.keys(KIND_LABELS).filter((k) => n.results.some((i) => i.kind === k));

  return (
    <section className="card card--wide notif-page">
      <header className="card__header">
        <div>
          <h1 className="page-title">Notificaciones</h1>
          <p className="muted page-subtitle">
            Alertas operativas en tiempo real según su rol y su cadena de mando. Actualizado {n.generated_at ? timeAgo(n.generated_at) : "…"}.
          </p>
        </div>
        <div className="pay-actions">
          <button type="button" className="button button--ghost button--sm" onClick={refreshNotifications}>
            Actualizar
          </button>
          <button type="button" className="button button--sm" disabled={!n.unread} onClick={() => markNotifications([], true)}>
            Marcar todas como leídas
          </button>
        </div>
      </header>
      <dl className="kpis">
        <div className="kpi kpi--warn">
          <dt>Sin leer</dt>
          <dd>{n.unread}</dd>
        </div>
        {Object.entries(KIND_LABELS).map(([k, label]) => (
          <div key={k} className="kpi">
            <dt>{label}</dt>
            <dd>{n.by_kind?.[k] ?? 0}</dd>
          </div>
        ))}
      </dl>
      <div className="notif-page__filters">
        <button type="button" className={`button button--sm${kind ? " button--ghost" : ""}`} onClick={() => setKind("")}>
          Todas ({n.total})
        </button>
        {kinds.map((k) => (
          <button key={k} type="button" className={`button button--sm${kind === k ? "" : " button--ghost"}`} onClick={() => setKind(k)}>
            {KIND_LABELS[k]}
          </button>
        ))}
        <label className="checkbox">
          <input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} /> Solo sin leer
        </label>
      </div>
      {n.error && <p className="error-box">{n.error}</p>}
      {!n.loading && rows.length === 0 && <p className="empty">Sin notificaciones con ese filtro.</p>}
      {rows.length > 0 && (
        <ul className="notif__list">
          {rows.map((i) => (
            <li key={i.key} className={`notif__item${i.read ? " is-read" : ""}`}>
              <span className={`notif__dot ${SEVERITY[i.severity] ?? ""}`} aria-hidden="true" />
              <span>
                <span className="notif__title">
                  <Link to={i.link} onClick={() => !i.read && markNotifications([i.key]).catch(() => {})}>
                    {i.title}
                  </Link>{" "}
                  <span className="badge badge--muted">{KIND_LABELS[i.kind] ?? i.kind}</span>
                </span>
                <span className="notif__body">{i.body}</span>
                <span className="notif__body">
                  {formatDateTime(i.at)} · {timeAgo(i.at)}
                  {!i.read && (
                    <>
                      {" · "}
                      <button type="button" className="link-button small" onClick={() => markNotifications([i.key])}>
                        Marcar como leída
                      </button>
                    </>
                  )}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
