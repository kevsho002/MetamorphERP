import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { PENDING_EVENT, newsApi } from "../../modules/announcements/api.js";

const POLL_MS = 120000;

/** Fase 25 — Aviso persistente mientras el usuario tenga comunicados críticos sin acuse de recibo. */
export default function PendingAckBanner() {
  const location = useLocation();
  const [pending, setPending] = useState(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      newsApi
        .pending()
        .then((p) => alive && setPending(p))
        .catch(() => alive && setPending(null));
    load();
    const timer = setInterval(() => document.visibilityState === "visible" && load(), POLL_MS);
    window.addEventListener(PENDING_EVENT, load);
    return () => {
      alive = false;
      clearInterval(timer);
      window.removeEventListener(PENDING_EVENT, load);
    };
  }, []);

  if (!pending?.count || location.pathname.startsWith("/announcements")) return null;
  const first = pending.results[0];
  return (
    <div className={`announcement announcement--${pending.overdue ? "error" : "warn"} ack-banner`} role="status">
      <span>
        <strong>{pending.count === 1 ? "Un comunicado requiere" : `${pending.count} comunicados requieren`} su acuse de recibo</strong>
        {pending.overdue ? ` (${pending.overdue} vencido${pending.overdue === 1 ? "" : "s"})` : ""}: {first?.title}
        {pending.count > 1 ? "…" : ""}
      </span>
      <Link className="button button--sm" to={pending.count === 1 ? `/announcements/${first.id}` : "/announcements?pending=1"}>
        Leer y confirmar
      </Link>
    </div>
  );
}
