import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { formatDate, formatDateTime } from "../../hcm/lib/format.js";
import { payrollApi } from "../../payroll/api.js";

const STATUS_CLASS = { OPEN: "badge--warn", RESOLVED: "badge--ok", REJECTED: "badge--muted" };
const SCOPE = {
  all: "Todas las excepciones (Planillas).",
  team: "Excepciones de su equipo (cadena de mando) y las suyas.",
  mine: "Sus excepciones.",
  none: "Su usuario no está vinculado a un colaborador.",
};

/**
 * Fase 21 — Excepciones de planilla reportadas por los agentes sobre su boleta preliminar. Las atiende el supervisor
 * (Team Manager vigente o su cadena) o Planillas; el cierre de la planilla exige que no queden abiertas.
 */
export default function PayrollExceptionsPage() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "OPEN";
  const payroll = params.get("payroll") ?? "";
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [reload, setReload] = useState(0);
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true }));
    payrollApi
      .exceptions({ status: status || undefined, payroll: payroll || undefined }, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [status, payroll, reload]);

  const setFilter = (k, v) =>
    setParams((p) => {
      const next = new URLSearchParams(p);
      if (v) next.set(k, v);
      else next.delete(k);
      return next;
    }, { replace: true });

  const data = state.data;
  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Excepciones de planilla</h1>
          <p className="muted page-subtitle">{data ? SCOPE[data.scope] : "Reportes de los agentes sobre su boleta preliminar."}</p>
        </div>
      </header>
      <div className="filters" role="search">
        <label className="field">
          <span className="field__label">Estado</span>
          <select value={status} onChange={(e) => setFilter("status", e.target.value)}>
            <option value="">Todas</option>
            <option value="OPEN">Abiertas</option>
            <option value="RESOLVED">Resueltas</option>
            <option value="REJECTED">Rechazadas</option>
          </select>
        </label>
        {payroll && (
          <button type="button" className="button button--ghost button--sm" onClick={() => setFilter("payroll", "")}>
            Quitar filtro de planilla
          </button>
        )}
      </div>
      {notice && <p className={notice.ok ? "alert alert--ok" : "error-box"}>{notice.text}</p>}
      {state.error && <p className="error-box">{state.error}</p>}
      <div className="table-wrap" aria-busy={state.loading}>
        <table className="table pay-exceptions">
          <thead>
            <tr>
              <th scope="col">Colaborador</th>
              <th scope="col">Planilla</th>
              <th scope="col">Excepción</th>
              <th scope="col">Estado</th>
              <th scope="col">Atención</th>
            </tr>
          </thead>
          <tbody>
            {(data?.results ?? []).map((x) => (
              <ExceptionRow key={x.id} x={x} onDone={(text) => { setNotice({ ok: true, text }); setReload((k) => k + 1); }}
                onError={(text) => setNotice({ ok: false, text })} />
            ))}
            {!state.loading && data && data.results.length === 0 && (
              <tr>
                <td colSpan={5} className="empty">
                  No hay excepciones con estos filtros.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ExceptionRow({ x, onDone, onError }) {
  const [response, setResponse] = useState("");
  const [busy, setBusy] = useState(false);
  const resolve = (statusValue) => {
    setBusy(true);
    payrollApi
      .resolveException(x.id, { status: statusValue, response })
      .then((b) => onDone(b.feedback))
      .catch((err) => onError(err.message))
      .finally(() => setBusy(false));
  };
  return (
    <tr>
      <td>
        <strong>{x.full_name}</strong>
        <div className="muted small">
          {x.employee_code}
          {x.supervisor_code ? ` · supervisor ${x.supervisor_code}` : ""}
        </div>
      </td>
      <td className="pay-nowrap small">{x.payroll_code}</td>
      <td>
        <strong>{x.category_label}</strong>
        {x.work_date ? ` · ${formatDate(x.work_date)}` : ""}
        <div className="small">{x.description}</div>
        <div className="muted small">Reportada {formatDateTime(x.created_at)}</div>
      </td>
      <td>
        <span className={`badge ${STATUS_CLASS[x.status] ?? ""}`}>{x.status_label}</span>
      </td>
      <td>
        {x.can_resolve ? (
          <div className="pay-exception-actions">
            <textarea rows={2} maxLength={1000} placeholder="Respuesta para el colaborador" value={response}
              onChange={(e) => setResponse(e.target.value)} aria-label={`Respuesta a la excepción de ${x.full_name}`} />
            <div className="pay-actions">
              <button type="button" className="button button--sm" disabled={busy || !response.trim()} onClick={() => resolve("RESOLVED")}>
                Resolver
              </button>
              <button type="button" className="button button--ghost button--sm" disabled={busy || !response.trim()} onClick={() => resolve("REJECTED")}>
                Rechazar
              </button>
            </div>
          </div>
        ) : x.response ? (
          <span className="small">
            {x.response}
            <span className="muted"> — {x.resolved_by}</span>
          </span>
        ) : (
          <span className="muted small">Pendiente del supervisor</span>
        )}
      </td>
    </tr>
  );
}
