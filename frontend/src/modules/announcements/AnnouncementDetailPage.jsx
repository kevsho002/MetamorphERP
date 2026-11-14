import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { formatDate, formatDateTime } from "../hcm/lib/format.js";
import { CATEGORY_TONE, newsApi, notifyChanged } from "./api.js";
import Body from "./Body.jsx";

const ROLE_LABELS = { ADMIN: "Administradores", HR: "RRHH", WFM: "WFM", EMPLOYEE: "Empleados" };

/** Fase 25 — Comunicado completo con el acuse de recibo (obligatorio en seguridad y cambios organizacionales). */
export default function AnnouncementDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    newsApi
      .get(id, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [id]);

  const run = async (fn, after) => {
    setBusy(true);
    setNotice(null);
    try {
      const body = await fn();
      if (body?.announcement) setState({ loading: false, data: body.announcement, error: null });
      setNotice({ ok: true, text: body?.feedback ?? "Listo." });
      notifyChanged();
      after?.();
    } catch (err) {
      setNotice({ ok: false, text: err.message });
    } finally {
      setBusy(false);
    }
  };

  const a = state.data;
  if (state.loading) return <section className="card card--wide"><p className="muted">Cargando…</p></section>;
  if (!a) {
    return (
      <section className="card card--wide">
        <p className="error-box">{state.error ?? "Comunicado no encontrado."}</p>
        <Link to="/announcements">← Volver al periódico</Link>
      </section>
    );
  }

  return (
    <section className="card card--wide news-detail">
      <p className="small">
        <Link to="/announcements">← Periódico virtual</Link>
      </p>
      <header className="news-detail__head">
        <div className="news__meta">
          <span className={`badge badge--${CATEGORY_TONE[a.category] ?? "info"}`}>{a.category_label}</span>
          {a.pinned && <span className="badge badge--warn">Destacado</span>}
          {a.status !== "PUBLISHED" && <span className="badge badge--muted">{a.status_label}</span>}
          {a.requires_ack && <span className="badge badge--info">Acuse de recibo obligatorio</span>}
        </div>
        <h1 className="page-title">{a.title}</h1>
        <p className="muted small">
          {a.author} · {a.published_at ? `publicado ${formatDateTime(a.published_at)}` : "sin publicar"}
          {a.audience_roles?.length ? ` · dirigido a ${a.audience_roles.map((r) => ROLE_LABELS[r] ?? r).join(", ")}` : " · para todos"}
          {a.expires_at ? ` · visible hasta ${formatDate(a.expires_at)}` : ""}
        </p>
      </header>

      {notice && (
        <div className={`alert ${notice.ok ? "alert--ok" : "alert--error"}`} role="status">
          <p className="alert__text">{notice.text}</p>
        </div>
      )}

      {a.summary && <p className="news-detail__summary">{a.summary}</p>}
      <div className="news-detail__body">
        <Body text={a.body} />
      </div>
      {a.link_url && (
        <p>
          <a className="button button--ghost" href={a.link_url} target="_blank" rel="noopener noreferrer">
            {a.link_label || "Abrir enlace"} ↗
          </a>
        </p>
      )}

      {a.requires_ack && a.status === "PUBLISHED" && (
        <div className={`news-ack${a.my_ack ? " is-done" : a.ack_overdue ? " is-overdue" : ""}`}>
          {a.my_ack ? (
            <>
              <strong>Acuse de recibo registrado</strong>
              <p className="small">
                Confirmó la lectura el {formatDateTime(a.my_ack.at)}. Huella del contenido confirmado: <code title={a.my_ack.sha256}>{a.my_ack.sha256.slice(0, 16)}…</code>
              </p>
            </>
          ) : a.ack_pending ? (
            <>
              <strong>{a.ack_overdue ? "Su acuse de recibo está VENCIDO" : "Este comunicado requiere su acuse de recibo"}</strong>
              <p className="small">
                {a.ack_due_date ? `Plazo: ${formatDate(a.ack_due_date)}. ` : ""}Su confirmación queda registrada con fecha, hora, IP y la huella
                SHA-256 del texto que leyó, para los reportes de cumplimiento.
              </p>
              <label className="checkbox">
                <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} /> He leído y comprendo este comunicado.
              </label>
              <div className="form-actions form-actions--start">
                <button type="button" className="button" disabled={!confirm || busy} onClick={() => run(() => newsApi.ack(a.id))}>
                  {busy ? "Registrando…" : "Confirmar acuse de recibo"}
                </button>
              </div>
            </>
          ) : (
            <p className="small muted">Este comunicado no está dirigido a su rol: no requiere su acuse.</p>
          )}
        </div>
      )}

      {a.compliance && (
        <div className="news-compliance">
          <div className="news-compliance__bar" aria-hidden="true">
            <span style={{ width: `${Number(a.compliance.compliance_pct)}%` }} />
          </div>
          <p className="small">
            <strong>{a.compliance.compliance_pct} %</strong> de cumplimiento · {a.compliance.acknowledged} de {a.compliance.audience} confirmados ·{" "}
            {a.compliance.pending} pendiente(s){a.compliance.overdue ? ` · ${a.compliance.overdue} vencido(s)` : ""}{" "}
            {a.can_report && <Link to={`/announcements/${a.id}/compliance`}>Ver reporte →</Link>}
          </p>
        </div>
      )}

      {a.can_manage && (
        <div className="news-detail__admin">
          <span className="muted small">
            Gestión{a.content_frozen ? " · contenido congelado (cada acuse prueba el texto confirmado)" : ""}
            {a.content_hash ? (
              <>
                {" "}· SHA-256 <code title={a.content_hash}>{a.content_hash.slice(0, 12)}…</code>
              </>
            ) : null}
          </span>
          <div className="pay-actions">
            {a.can_edit && (
              <Link className="button button--ghost button--sm" to={`/announcements/${a.id}/edit`}>
                Editar
              </Link>
            )}
            {a.status === "DRAFT" && (
              <>
                <button type="button" className="button button--sm" disabled={busy} onClick={() => run(() => newsApi.publish(a.id))}>
                  Publicar
                </button>
                <button type="button" className="button button--danger button--sm" disabled={busy}
                  onClick={() => window.confirm("¿Eliminar este borrador?") && run(() => newsApi.remove(a.id), () => navigate("/announcements?scope=draft"))}>
                  Eliminar borrador
                </button>
              </>
            )}
            {a.status === "PUBLISHED" && (
              <button type="button" className="button button--ghost button--sm" disabled={busy}
                onClick={() => window.confirm("¿Archivar el comunicado? Dejará de mostrarse en el periódico.") && run(() => newsApi.archive(a.id))}>
                Archivar
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
