import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { adhApi, fmtDuration, hhmm } from "../api.js";
import ActivityModal from "../components/ActivityModal.jsx";

const STATUSES = [
  ["PENDING", "Pendientes"],
  ["APPROVED", "Aprobadas"],
  ["REJECTED", "Rechazadas"],
  ["CANCELLED", "Anuladas"],
  ["", "Todas"],
];
const STATUS_CLS = { PENDING: "badge--warn", APPROVED: "badge--ok", REJECTED: "badge--error", CANCELLED: "badge--muted" };

function when(iso) {
  return iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)} ${iso.slice(11, 16)}` : "—";
}

/**
 * Cola de aprobación de WFM (Fase 19): correcciones de segmentos que pidieron los agentes, sus supervisores (cadena de
 * mando del roster) o usuarios WFM de solo lectura. Aprobar aplica el cambio al plan (origen «solicitud aprobada») y
 * recalcula la adherencia; rechazar exige un comentario. Los cambios del día completo no llegan aquí: van por AP.
 */
export default function ChangeRequestsPage() {
  const [status, setStatus] = useState("PENDING");
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [reload, setReload] = useState(0);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(null);
  const [comments, setComments] = useState({});
  const [modal, setModal] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    adhApi
      .requests({ status }, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [status, reload]);

  const decide = (r, decision) => {
    setBusy(r.id);
    setNotice(null);
    adhApi
      .decideRequest(r.id, { decision, comment: comments[r.id] ?? "" })
      .then((b) => {
        setNotice({ ok: true, text: b.feedback });
        setReload((k) => k + 1);
      })
      .catch((err) => setNotice({ ok: false, text: err.message }))
      .finally(() => setBusy(null));
  };
  const closeModal = useCallback(() => setModal(null), []);
  const data = state.data;
  const rows = data?.results ?? [];

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Cola de aprobación WFM</h1>
          <p className="muted page-subtitle">
            Correcciones de segmentos solicitadas desde la ventana de detalle del día. Aprobar aplica el cambio al plan; los cambios del día completo requieren AP.
          </p>
        </div>
        {data && <span className="badge badge--warn">{data.pending} pendientes</span>}
      </header>
      <div className="iex__views" role="tablist" aria-label="Estado">
        {STATUSES.map(([value, label]) => (
          <button key={value || "all"} type="button" role="tab" aria-selected={status === value} className={`iex__tab${status === value ? " is-active" : ""}`}
            onClick={() => setStatus(value)}>
            {label}
          </button>
        ))}
      </div>
      {notice && (
        <div className={`alert ${notice.ok ? "alert--ok" : "alert--error"} flash`} role="status">
          <p className="alert__text">{notice.text}</p>
        </div>
      )}
      {state.error && <p className="error-box">{state.error}</p>}
      <div className="table-wrap" aria-busy={state.loading}>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">Agente · fecha</th>
              <th scope="col">Solicitud</th>
              <th scope="col">Motivo</th>
              <th scope="col">Solicitó</th>
              <th scope="col">Estado</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="num">{r.id}</td>
                <td>
                  <button type="button" className="link-button" onClick={() => setModal({ employee_code: r.employee_code, full_name: r.full_name, date: r.shift_date,
                    focus: r.segment_id ?? "container" })}>
                    {r.full_name}
                  </button>
                  <div className="muted small">
                    {r.employee_code} · {r.shift_date}
                  </div>
                </td>
                <td>
                  <strong>{r.kind_label}</strong>
                  {r.before && (
                    <div className="small">
                      Antes: {r.before.activity_name} {hhmm(r.before.start)}–{hhmm(r.before.end)}
                      {r.before.is_locked ? " (bloqueado)" : ""}
                    </div>
                  )}
                  {r.activity_name && (
                    <div className="small">
                      Propuesta: {r.activity_name} {hhmm(r.start)}–{hhmm(r.end)} ({fmtDuration(r.seconds)})
                    </div>
                  )}
                  {r.folio && (
                    <div className="small">
                      AP <Link to={`/personnel-actions/${r.folio}`}>{r.folio}</Link>
                    </div>
                  )}
                </td>
                <td className="small">{r.reason}</td>
                <td className="small">
                  {r.requester_role_label}
                  <div className="muted">
                    {r.requested_by} · {when(r.requested_at)}
                  </div>
                </td>
                <td>
                  <span className={`badge ${STATUS_CLS[r.status]}`}>{r.status_label}</span>
                  {r.decided_by && (
                    <div className="muted small">
                      {r.decided_by} · {when(r.decided_at)}
                      {r.decision_comment ? ` · «${r.decision_comment}»` : ""}
                    </div>
                  )}
                  {r.status === "PENDING" && data.can_decide && (
                    <div className="queue-decide">
                      <input aria-label={`Comentario para la solicitud ${r.id}`} placeholder="Comentario (obligatorio al rechazar)" maxLength={500}
                        value={comments[r.id] ?? ""} onChange={(e) => setComments((c) => ({ ...c, [r.id]: e.target.value }))} />
                      <button type="button" className="button button--sm" disabled={busy === r.id} onClick={() => decide(r, "APPROVE")}>
                        Aprobar
                      </button>
                      <button type="button" className="button button--sm button--danger" disabled={busy === r.id} onClick={() => decide(r, "REJECT")}>
                        Rechazar
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
            {!state.loading && rows.length === 0 && (
              <tr>
                <td colSpan={6} className="empty">
                  No hay solicitudes en este estado.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {modal && <ActivityModal key={`${modal.employee_code}-${modal.date}`} target={modal} onClose={closeModal} onChanged={() => setReload((k) => k + 1)} />}
    </section>
  );
}
