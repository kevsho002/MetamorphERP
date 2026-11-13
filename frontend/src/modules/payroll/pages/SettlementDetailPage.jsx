import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { formatDate, formatDateTime, formatMoney } from "../../hcm/lib/format.js";
import { SETTLEMENT_STATUS, num, payrollApi, pct } from "../api.js";

const GROUPS = [
  ["EARNING", "Devengado"],
  ["LEGAL", "Retenciones de ley"],
  ["DEDUCTION", "Descuentos"],
  ["INFO", "Información"],
];

/** Fase 21 — Detalle de una liquidación: cálculo por componente, ajustes manuales, aprobación (sello) y pago en lote. */
export default function SettlementDetailPage() {
  const { id } = useParams();
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [reload, setReload] = useState(0);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(null);
  const [line, setLine] = useState({ kind: "EARNING", label: "", amount: "", affects_social_security: false, affects_income_tax: false });
  const [reason, setReason] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    payrollApi
      .settlement(id, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [id, reload]);

  const act = (action, payload) => {
    setBusy(action);
    setNotice(null);
    payrollApi
      .settlementAction(id, action, payload)
      .then((b) => {
        const warnings = b.settlement?.warnings ?? [];
        setNotice({ ok: true, text: b.feedback + (warnings.length ? ` ${warnings.join(" ")}` : "") });
        setReload((k) => k + 1);
      })
      .catch((err) => setNotice({ ok: false, text: err.message }))
      .finally(() => setBusy(null));
  };

  const s = state.data?.settlement;
  const canManage = state.data?.can_manage;
  const editable = canManage && s && ["DRAFT", "CALCULATED"].includes(s.status);
  const st = s ? SETTLEMENT_STATUS[s.status] : null;
  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <p className="muted small">
            <Link to="/payroll/settlements">Liquidaciones</Link> ›
          </p>
          <h1 className="page-title">
            Liquidación {s?.folio ?? "…"} {st && <span className={`badge ${st.cls}`}>{st.label}</span>}
          </h1>
          {s && (
            <p className="muted page-subtitle">
              {s.full_name} ({s.employee_code}) · {s.reason_label} · ingreso {formatDate(s.hire_date)} · terminación {formatDate(s.termination_date)} ·
              {` ${num(s.service_years)} años de servicio (sin suspensiones)`} · salario base {num(s.base_salary)}
              {s.termination_folio ? ` · AP ${s.termination_folio}` : ""}
            </p>
          )}
        </div>
        {s && (
          <div className="pay-actions">
            {editable && (
              <button type="button" className="button button--ghost button--sm" disabled={!!busy} onClick={() => act("calculate")}>
                {busy === "calculate" ? "Calculando…" : "Recalcular"}
              </button>
            )}
            {canManage && s.status === "CALCULATED" && (
              <button type="button" className="button button--sm" disabled={!!busy}
                onClick={() => window.confirm("Aprobar sella el contenido de la liquidación: ya no admite ajustes. ¿Continuar?") && act("approve")}>
                Aprobar y sellar
              </button>
            )}
            {s.batch_id && (
              <Link className="button button--ghost button--sm" to={`/payroll/settlement-batches/${s.batch_id}`}>
                Lote {s.batch}
              </Link>
            )}
          </div>
        )}
      </header>
      {notice && <p className={notice.ok ? "alert alert--ok" : "error-box"}>{notice.text}</p>}
      {state.error && <p className="error-box">{state.error}</p>}
      {s && (
        <>
          <dl className="kpis">
            <div className="kpi">
              <dt>Devengado</dt>
              <dd>{formatMoney(s.gross, s.currency)}</dd>
            </div>
            <div className="kpi kpi--warn">
              <dt>Descuentos</dt>
              <dd>{formatMoney(s.deductions, s.currency)}</dd>
            </div>
            <div className="kpi kpi--ok">
              <dt>Líquido a pagar</dt>
              <dd>{formatMoney(s.net, s.currency)}</dd>
            </div>
          </dl>
          <p className="small settle-words">
            <strong>En letras:</strong> {s.net_in_words}
          </p>
          {GROUPS.map(([kind, title]) => {
            const rows = s.lines.filter((l) => l.kind === kind);
            if (!rows.length) return null;
            return (
              <div key={kind} className="table-wrap">
                <table className="table table--compact settle-lines">
                  <caption>{title}</caption>
                  <thead>
                    <tr>
                      <th scope="col">Concepto</th>
                      <th scope="col" className="num">
                        Cantidad
                      </th>
                      <th scope="col" className="num">
                        Valor / tasa
                      </th>
                      <th scope="col" className="num">
                        Monto
                      </th>
                      {editable && <th scope="col" />}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((l) => (
                      <tr key={l.id}>
                        <td>
                          {l.label}
                          {l.is_manual && <span className="badge badge--muted settle-manual">Ajuste</span>}
                          {l.notes && <div className="muted small">{l.notes}</div>}
                        </td>
                        <td className="num">{l.quantity !== null ? `${num(l.quantity, 2)} ${l.unit}` : ""}</td>
                        <td className="num">{l.rate !== null ? (kind === "LEGAL" ? pct(l.rate) : num(l.rate, 4)) : ""}</td>
                        <td className="num">{kind === "INFO" ? "" : num(l.amount)}</td>
                        {editable && (
                          <td>
                            {l.is_manual && (
                              <button type="button" className="button button--ghost button--sm" disabled={!!busy} onClick={() => act("remove-line", { line_id: l.id })}>
                                Quitar
                              </button>
                            )}
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          })}
          {editable && (
            <form className="pay-inline-form" onSubmit={(e) => { e.preventDefault(); act("lines", line); }}>
              <strong className="small">Ajuste manual</strong>
              <label className="field">
                <span className="field__label">Tipo</span>
                <select value={line.kind} onChange={(e) => setLine((x) => ({ ...x, kind: e.target.value }))}>
                  <option value="EARNING">Devengo (bono pendiente, monto pactado…)</option>
                  <option value="DEDUCTION">Descuento (saldo de préstamo, anticipo…)</option>
                </select>
              </label>
              <label className="field">
                <span className="field__label">Descripción</span>
                <input required maxLength={200} value={line.label} onChange={(e) => setLine((x) => ({ ...x, label: e.target.value }))} />
              </label>
              <label className="field">
                <span className="field__label">Monto</span>
                <input type="number" min="0.01" step="0.01" required value={line.amount} onChange={(e) => setLine((x) => ({ ...x, amount: e.target.value }))} />
              </label>
              {line.kind === "EARNING" && (
                <>
                  <label className="checkbox">
                    <input type="checkbox" checked={line.affects_social_security} onChange={(e) => setLine((x) => ({ ...x, affects_social_security: e.target.checked }))} />
                    <span>Cotiza ISSS / AFP</span>
                  </label>
                  <label className="checkbox">
                    <input type="checkbox" checked={line.affects_income_tax} onChange={(e) => setLine((x) => ({ ...x, affects_income_tax: e.target.checked }))} />
                    <span>Gravado (Renta)</span>
                  </label>
                </>
              )}
              <button type="submit" className="button button--sm" disabled={!!busy}>
                Agregar
              </button>
            </form>
          )}
          {editable && (
            <form className="pay-inline-form" onSubmit={(e) => { e.preventDefault(); act("cancel", { reason }); }}>
              <label className="field">
                <span className="field__label">Motivo para anular</span>
                <input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
              </label>
              <button type="submit" className="button button--danger button--sm" disabled={!!busy || !reason.trim()}>
                Anular liquidación
              </button>
            </form>
          )}
          <p className="muted small settle-meta">
            {s.calculated_at && `Calculada ${formatDateTime(s.calculated_at)}`}
            {s.approved_at && ` · aprobada ${formatDateTime(s.approved_at)}`}
            {s.paid_at && ` · pagada ${formatDateTime(s.paid_at)}`}
            {s.cancel_reason && ` · anulada: ${s.cancel_reason}`}
            {s.content_hash && ` · sello SHA-256 ${s.content_hash}`}
          </p>
        </>
      )}
    </section>
  );
}
