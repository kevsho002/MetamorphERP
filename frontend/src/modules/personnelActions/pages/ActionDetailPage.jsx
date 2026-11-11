import { useCallback, useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { formatDate, formatDateTime } from "../../hcm/lib/format.js";
import { actionsApi } from "../api.js";
import ActionStatusBadge from "../components/ActionStatusBadge.jsx";
import { ScheduleTable } from "../components/WeeklyScheduleEditor.jsx";

/** Detalle de una AP: datos, valores EAV, cadena de firmas (con verificación de integridad) y acciones posibles. */
export default function ActionDetailPage() {
  const { folio } = useParams();
  const location = useLocation();
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [notice, setNotice] = useState(location.state?.feedback ? { ok: true, text: location.state.feedback } : null);
  const [busy, setBusy] = useState(null);
  const [comment, setComment] = useState("");
  const [cancelReason, setCancelReason] = useState("");

  const load = useCallback(
    (signal) =>
      actionsApi
        .get(folio, { signal })
        .then((data) => setState({ loading: false, data, error: null }))
        .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.status === 404 ? "La AP no existe o su rol no puede verla." : err.message })),
    [folio],
  );

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const act = async (key, fn) => {
    setBusy(key);
    setNotice(null);
    try {
      const body = await fn();
      setState({ loading: false, data: body.action, error: null });
      setNotice({ ok: true, text: body.feedback });
      setComment("");
    } catch (err) {
      setNotice({ ok: false, text: err.message });
    } finally {
      setBusy(null);
    }
  };

  if (state.loading) return <p className="muted">Cargando acción de personal…</p>;
  if (!state.data) return <p className="error-box">{state.error}</p>;
  const a = state.data;

  return (
    <section className="card card--wide">
      <nav className="breadcrumb" aria-label="Ruta">
        <Link to="/personnel-actions">Acciones de personal</Link> › <span>{a.folio}</span>
      </nav>
      <header className="card__header">
        <div>
          <h1 className="page-title">
            {a.action_type_name} <code>{a.folio}</code>
          </h1>
          <p className="muted page-subtitle">
            {a.can_view_employee ? <Link to={`/hcm/employees/${a.employee_code}?tab=actions`}>{a.full_name}</Link> : a.full_name} ·{" "}
            <code>{a.employee_code}</code> · efectiva desde el <strong>{formatDate(a.effective_date)}</strong>
            {a.is_initial && " · AP fundacional de horario"}
          </p>
        </div>
        <ActionStatusBadge status={a.status} label={a.status_label} />
      </header>
      {notice && (
        <div className={`alert ${notice.ok ? "alert--ok" : "alert--error"} flash`} role="status">
          <p className="alert__text">{notice.text}</p>
        </div>
      )}

      <dl className="detail-grid">
        <div className="detail-item">
          <dt>Elaborada por</dt>
          <dd>
            {a.created_by ?? "sistema"} · {formatDateTime(a.created_at)}
          </dd>
        </div>
        <div className="detail-item">
          <dt>Enviada</dt>
          <dd>{a.submitted_at ? formatDateTime(a.submitted_at) : "—"}</dd>
        </div>
        <div className="detail-item">
          <dt>Resuelta</dt>
          <dd>{a.decided_at ? formatDateTime(a.decided_at) : "—"}</dd>
        </div>
        <div className="detail-item">
          <dt>Efecto aplicado</dt>
          <dd>{a.applied_at ? formatDateTime(a.applied_at) : a.status === "APPROVED" ? "Se aplicará en la fecha efectiva" : "—"}</dd>
        </div>
      </dl>
      <h2 className="section-title">Observaciones / justificación</h2>
      <p className="pre-wrap">{a.justification}</p>
      {a.cancel_reason && <p className="alert alert--warn">Motivo de anulación: {a.cancel_reason}</p>}

      <h2 className="section-title">Datos de la acción</h2>
      <dl className="detail-grid">
        {a.values
          .filter((v) => v.data_type !== "SCHEDULE")
          .map((v) => (
            <div key={v.key} className="detail-item">
              <dt>{v.label}</dt>
              <dd>{v.display}</dd>
            </div>
          ))}
      </dl>
      {a.values
        .filter((v) => v.data_type === "SCHEDULE")
        .map((v) => (
          <div key={v.key}>
            <h3 className="section-title">{v.label}</h3>
            {v.schedule ? <ScheduleTable summary={v.schedule} /> : <p className="muted">Sin horario.</p>}
          </div>
        ))}

      <h2 className="section-title">Firmas de aprobación</h2>
      {a.integrity?.sealed && (
        <p className={`small ${a.integrity.valid ? "muted" : "error-box"}`}>
          {a.integrity.valid
            ? `Contenido sellado (SHA-256 ${a.integrity.content_hash.slice(0, 16)}…): las firmas verifican.`
            : "¡Atención! El contenido o alguna firma no verifica: la AP fue alterada después de firmarse."}
        </p>
      )}
      <ol className="signature-chain">
        {a.steps.map((s) => (
          <li key={s.order} className={`signature-chain__step${s.is_next ? " signature-chain__step--next" : ""}`}>
            <strong>
              {s.order}. {s.label}
            </strong>{" "}
            <span className="muted small">({s.role_label})</span>
            {s.signature ? (
              <p className="small">
                <span className={`badge ${s.signature.decision === "APPROVED" ? "badge--ok" : "badge--error"}`}>{s.signature.decision_label}</span>{" "}
                {s.signature.signer_name || s.signature.signer} ({s.signature.signer_role}) · {formatDateTime(s.signature.signed_at)}
                {s.signature.comment && ` — «${s.signature.comment}»`}
                <br />
                <code className="muted">firma {s.signature.signature.slice(0, 24)}…</code>
              </p>
            ) : (
              <p className="small muted">{s.is_next ? "Pendiente de firma" : a.status === "PENDING" ? "En espera" : "Sin firma"}</p>
            )}
          </li>
        ))}
        {a.steps.length === 0 && <li className="muted">Este tipo no requiere firmas.</li>}
      </ol>

      {a.status === "PENDING" && (
        <div className="form-section">
          {a.can_sign ? (
            <>
              <label className="field">
                <span className="field__label">Comentario (obligatorio para rechazar)</span>
                <input value={comment} maxLength={500} onChange={(e) => setComment(e.target.value)} />
              </label>
              <div className="form-actions form-actions--start">
                <button type="button" className="button button--success" disabled={Boolean(busy)} onClick={() => act("approve", () => actionsApi.sign(a.folio, "APPROVED", comment))}>
                  {busy === "approve" ? "Firmando…" : `Aprobar y firmar (${a.next_step.label})`}
                </button>
                <button type="button" className="button button--danger" disabled={Boolean(busy) || !comment.trim()} onClick={() => act("reject", () => actionsApi.sign(a.folio, "REJECTED", comment))}>
                  Rechazar
                </button>
              </div>
            </>
          ) : (
            <p className="muted small">{a.sign_block_reason}</p>
          )}
        </div>
      )}

      {(a.can_submit || a.can_cancel) && (
        <div className="form-section">
          {a.can_submit && (
            <button type="button" className="button" disabled={Boolean(busy)} onClick={() => act("submit", () => actionsApi.submit(a.folio))}>
              {busy === "submit" ? "Enviando…" : "Enviar a aprobación"}
            </button>
          )}
          {a.can_cancel && (
            <div className="form-actions form-actions--start">
              <input value={cancelReason} onChange={(e) => setCancelReason(e.target.value)} placeholder="Motivo de la anulación" aria-label="Motivo de la anulación" maxLength={500} />
              <button type="button" className="button button--ghost" disabled={Boolean(busy) || !cancelReason.trim()} onClick={() => act("cancel", () => actionsApi.cancel(a.folio, cancelReason))}>
                Anular AP
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
