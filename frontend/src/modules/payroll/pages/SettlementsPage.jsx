import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { formatDate, formatMoney, todayIso } from "../../hcm/lib/format.js";
import { SETTLEMENT_STATUS, num, payrollApi } from "../api.js";

/**
 * Fase 21 — Liquidaciones e indemnizaciones, separadas de la planilla ordinaria. Se abren solas al aplicarse la AP de
 * terminación / renuncia; RRHH revisa, ajusta, aprueba (contenido sellado) y las agrupa en LOTES de pago propios (cheques
 * o transferencias).
 */
export default function SettlementsPage() {
  const [tab, setTab] = useState("settlements");
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [batches, setBatches] = useState(null);
  const [filters, setFilters] = useState({ status: "", search: "" });
  const [selected, setSelected] = useState([]);
  const [batchForm, setBatchForm] = useState({ payment_date: todayIso(), method: "CHECK", first_check: "", bank_account: "" });
  const [notice, setNotice] = useState(null);
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    const t = setTimeout(() => {
      payrollApi
        .settlements({ status: filters.status || undefined, search: filters.search || undefined }, { signal: controller.signal })
        .then((data) => setState({ loading: false, data, error: null }))
        .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
      payrollApi.settlementBatches({ signal: controller.signal }).then(setBatches).catch(() => {});
    }, 200);
    return () => {
      clearTimeout(t);
      controller.abort();
    };
  }, [filters, reload]);

  const data = state.data;
  const canManage = data?.can_manage;
  const approvable = (data?.results ?? []).filter((s) => s.status === "APPROVED" && !s.batch_id);
  const toggle = (id) => setSelected((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]));
  const run = (promise) => {
    setBusy(true);
    setNotice(null);
    promise
      .then((b) => {
        setNotice({ ok: true, text: b.feedback ?? "Listo." });
        setSelected([]);
        setReload((k) => k + 1);
      })
      .catch((err) => setNotice({ ok: false, text: err.message }))
      .finally(() => setBusy(false));
  };

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Liquidaciones e indemnizaciones</h1>
          <p className="muted page-subtitle">
            Se abren al aplicarse la AP de terminación o renuncia: indemnización (despido sin causa), prestación por renuncia voluntaria,
            vacaciones y aguinaldo proporcionales. Se pagan en lotes propios (cheques o transferencias), fuera de la planilla ordinaria.
          </p>
        </div>
      </header>
      <div className="tabs" role="tablist">
        {[["settlements", "Liquidaciones"], ["batches", "Lotes de pago"]].map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={tab === id} className={`tab${tab === id ? " tab--active" : ""}`} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>
      {notice && <p className={notice.ok ? "alert alert--ok" : "error-box"}>{notice.text}</p>}
      {state.error && <p className="error-box">{state.error}</p>}

      {tab === "settlements" && (
        <>
          {canManage && data?.pending_terminations.length > 0 && (
            <details className="pay-warnings">
              <summary>{data.pending_terminations.length} colaborador(es) terminado(s) sin liquidación</summary>
              <ul>
                {data.pending_terminations.map((p) => (
                  <li key={p.employee_code}>
                    {p.employee_code} {p.full_name} · terminación {formatDate(p.termination_date)}{" "}
                    <select aria-label={`Motivo de ${p.full_name}`} defaultValue="RENUNCIA" id={`reason-${p.employee_code}`}>
                      {data.reasons.map((r) => (
                        <option key={r.value} value={r.value}>
                          {r.label}
                        </option>
                      ))}
                    </select>{" "}
                    <button type="button" className="button button--ghost button--sm" disabled={busy}
                      onClick={() => run(payrollApi.openSettlement({ employee_code: p.employee_code,
                        reason: document.getElementById(`reason-${p.employee_code}`).value }).then(() => ({ feedback: "Liquidación abierta." })))}>
                      Abrir liquidación
                    </button>
                  </li>
                ))}
              </ul>
            </details>
          )}
          <div className="filters" role="search">
            <label className="field filters__search">
              <span className="field__label">Buscar</span>
              <input type="search" placeholder="Folio, ID o nombre" value={filters.search} onChange={(e) => setFilters((f) => ({ ...f, search: e.target.value }))} />
            </label>
            <label className="field">
              <span className="field__label">Estado</span>
              <select value={filters.status} onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}>
                <option value="">Todos</option>
                {Object.entries(SETTLEMENT_STATUS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {canManage && approvable.length > 0 && (
            <form className="pay-inline-form" onSubmit={(e) => {
              e.preventDefault();
              run(payrollApi.createSettlementBatch({ ...batchForm, settlements: selected }));
            }}>
              <strong className="small">{selected.length} liquidación(es) aprobada(s) seleccionada(s)</strong>
              <label className="field">
                <span className="field__label">Fecha de pago</span>
                <input type="date" required value={batchForm.payment_date} onChange={(e) => setBatchForm((f) => ({ ...f, payment_date: e.target.value }))} />
              </label>
              <label className="field">
                <span className="field__label">Forma de pago</span>
                <select value={batchForm.method} onChange={(e) => setBatchForm((f) => ({ ...f, method: e.target.value }))}>
                  <option value="CHECK">Cheque</option>
                  <option value="TRANSFER">Transferencia</option>
                </select>
              </label>
              {batchForm.method === "CHECK" && (
                <label className="field">
                  <span className="field__label">N.º de cheque inicial</span>
                  <input inputMode="numeric" value={batchForm.first_check} onChange={(e) => setBatchForm((f) => ({ ...f, first_check: e.target.value }))} />
                </label>
              )}
              <button type="submit" className="button button--sm" disabled={busy || !selected.length}>
                Crear lote de pago
              </button>
            </form>
          )}
          <div className="table-wrap" aria-busy={state.loading}>
            <table className="table pay-settlements">
              <thead>
                <tr>
                  <th scope="col" className="pay-check" aria-label="Seleccionar" />
                  <th scope="col">Folio</th>
                  <th scope="col">Colaborador</th>
                  <th scope="col">Motivo</th>
                  <th scope="col" className="num">
                    Años
                  </th>
                  <th scope="col" className="num">
                    Devengado
                  </th>
                  <th scope="col" className="num">
                    Descuentos
                  </th>
                  <th scope="col" className="num">
                    Líquido
                  </th>
                  <th scope="col">Estado</th>
                  <th scope="col">Lote / cheque</th>
                </tr>
              </thead>
              <tbody>
                {(data?.results ?? []).map((s) => {
                  const st = SETTLEMENT_STATUS[s.status];
                  const can = canManage && s.status === "APPROVED" && !s.batch_id;
                  return (
                    <tr key={s.id} className={selected.includes(s.id) ? "is-selected" : ""}>
                      <td className="pay-check">
                        {can && <input type="checkbox" checked={selected.includes(s.id)} onChange={() => toggle(s.id)} aria-label={`Seleccionar ${s.folio}`} />}
                      </td>
                      <td className="pay-folio">
                        <Link to={`/payroll/settlements/${s.id}`}>{s.folio}</Link>
                      </td>
                      <td>
                        {s.full_name}
                        <div className="muted small">
                          {s.employee_code} · terminación {formatDate(s.termination_date)}
                        </div>
                      </td>
                      <td className="small">{s.reason_label}</td>
                      <td className="num">{num(s.service_years)}</td>
                      <td className="num">{num(s.gross)}</td>
                      <td className="num">{num(s.deductions)}</td>
                      <td className="num">
                        <strong>{formatMoney(s.net, s.currency)}</strong>
                      </td>
                      <td>
                        <span className={`badge ${st?.cls ?? ""}`}>{st?.label ?? s.status}</span>
                      </td>
                      <td className="small">
                        {s.batch ? (
                          <Link to={`/payroll/settlement-batches/${s.batch_id}`}>
                            {s.batch}
                            {s.check_number ? ` · ch. ${s.check_number}` : ""}
                          </Link>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  );
                })}
                {!state.loading && data && data.results.length === 0 && (
                  <tr>
                    <td colSpan={10} className="empty">
                      No hay liquidaciones con estos filtros.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}

      {tab === "batches" && (
        <div className="table-wrap">
          <table className="table pay-batches">
            <thead>
              <tr>
                <th scope="col">Lote</th>
                <th scope="col">Pago</th>
                <th scope="col">Forma</th>
                <th scope="col" className="num">
                  Liquidaciones
                </th>
                <th scope="col" className="num">
                  Total
                </th>
                <th scope="col">Estado</th>
              </tr>
            </thead>
            <tbody>
              {(batches?.results ?? []).map((b) => (
                <tr key={b.id}>
                  <td className="pay-folio">
                    <Link to={`/payroll/settlement-batches/${b.id}`}>{b.code}</Link>
                  </td>
                  <td>{formatDate(b.payment_date)}</td>
                  <td>{b.method_label}</td>
                  <td className="num">{b.count}</td>
                  <td className="num">{num(b.total)}</td>
                  <td>
                    <span className={`badge ${b.status === "PAID" ? "badge--ok" : b.status === "CLOSED" ? "badge--info" : "badge--muted"}`}>{b.status_label}</span>
                  </td>
                </tr>
              ))}
              {batches && batches.results.length === 0 && (
                <tr>
                  <td colSpan={6} className="empty">
                    Aún no hay lotes de pago: seleccione liquidaciones aprobadas y cree uno.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
