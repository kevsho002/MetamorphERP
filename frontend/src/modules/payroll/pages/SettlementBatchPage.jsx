import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { formatDate, formatMoney } from "../../hcm/lib/format.js";
import { num, payrollApi } from "../api.js";

/**
 * Fase 21 — Lote de pago de liquidaciones (separado de la planilla): números de cheque, cierre, impresión de cheques /
 * comprobantes (uno por página, con el monto en letras) y registro del pago.
 */
export default function SettlementBatchPage() {
  const { id } = useParams();
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [reload, setReload] = useState(0);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [printing, setPrinting] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    payrollApi
      .settlementBatch(id, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [id, reload]);

  useEffect(() => {
    if (!printing) return undefined;
    const t = setTimeout(() => {
      window.print();
      setPrinting(false);
    }, 150);
    return () => clearTimeout(t);
  }, [printing]);

  const run = (promise) => {
    setBusy(true);
    setNotice(null);
    promise
      .then((b) => {
        setNotice({ ok: true, text: b.feedback });
        setReload((k) => k + 1);
      })
      .catch((err) => setNotice({ ok: false, text: err.message }))
      .finally(() => setBusy(false));
  };

  const b = state.data?.batch;
  const canManage = state.data?.can_manage;
  const open = b?.status === "OPEN";
  return (
    <section className={`card card--wide${printing ? " settle-printing" : ""}`}>
      <header className="card__header pay-print__bar">
        <div>
          <p className="muted small">
            <Link to="/payroll/settlements">Liquidaciones</Link> ›
          </p>
          <h1 className="page-title">Lote {b?.code ?? "…"}</h1>
          {b && (
            <p className="muted page-subtitle">
              {b.method_label} · pago {formatDate(b.payment_date)} · {b.count} liquidación(es) · total {num(b.total)} · {b.status_label}
            </p>
          )}
        </div>
        {b && canManage && (
          <div className="pay-actions">
            {open && (
              <button type="button" className="button button--sm" disabled={busy} onClick={() => run(payrollApi.settlementBatchAction(id, "close"))}>
                Cerrar lote
              </button>
            )}
            {b.status === "CLOSED" && (
              <>
                <button type="button" className="button button--ghost button--sm" onClick={() => setPrinting(true)}>
                  {b.method === "CHECK" ? "Imprimir cheques" : "Imprimir comprobantes"}
                </button>
                <button type="button" className="button button--ghost button--sm" disabled={busy} onClick={() => run(payrollApi.settlementBatchAction(id, "reopen"))}>
                  Reabrir
                </button>
                <button type="button" className="button button--sm" disabled={busy}
                  onClick={() => window.confirm("Marcar el lote como pagado deja pagadas sus liquidaciones. ¿Continuar?") && run(payrollApi.settlementBatchAction(id, "pay"))}>
                  Marcar pagado
                </button>
              </>
            )}
            {b.status === "PAID" && (
              <button type="button" className="button button--ghost button--sm" onClick={() => setPrinting(true)}>
                Reimprimir
              </button>
            )}
          </div>
        )}
      </header>
      {notice && <p className={notice.ok ? "alert alert--ok" : "error-box"}>{notice.text}</p>}
      {state.error && <p className="error-box">{state.error}</p>}
      {b && (
        <div className="table-wrap pay-print__bar">
          <table className="table pay-settlements">
            <thead>
              <tr>
                <th scope="col">Folio</th>
                <th scope="col">Beneficiario</th>
                <th scope="col" className="num">
                  Líquido
                </th>
                <th scope="col">{b.method === "CHECK" ? "N.º de cheque" : "Referencia"}</th>
                {open && canManage && <th scope="col" />}
              </tr>
            </thead>
            <tbody>
              {b.settlements.map((s) => (
                <tr key={s.id}>
                  <td className="pay-folio">
                    <Link to={`/payroll/settlements/${s.id}`}>{s.folio}</Link>
                  </td>
                  <td>
                    {s.full_name}
                    <div className="muted small">{s.employee_code}</div>
                  </td>
                  <td className="num">{formatMoney(s.net, s.currency)}</td>
                  <td>
                    {open && canManage ? (
                      <CheckInput settlement={s} onSave={(value) => run(payrollApi.settlementAction(s.id, "check", { check_number: value }))} />
                    ) : (
                      s.check_number || "—"
                    )}
                  </td>
                  {open && canManage && (
                    <td>
                      <button type="button" className="button button--ghost button--sm" disabled={busy}
                        onClick={() => run(payrollApi.settlementBatchAction(id, "remove", { settlement_id: s.id }))}>
                        Quitar
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {b && (
        <div className="settle-checks" aria-hidden={!printing}>
          {b.settlements.map((s) => (
            <article key={s.id} className="settle-check">
              <header className="settle-check__head">
                <strong>Metamorph ERP</strong>
                <span>
                  {b.method === "CHECK" ? `Cheque N.º ${s.check_number || "—"}` : `Transferencia ${s.check_number || ""}`} · {formatDate(b.payment_date)}
                </span>
              </header>
              <p className="settle-check__payee">
                Páguese a la orden de: <strong>{s.full_name}</strong>
              </p>
              <p className="settle-check__amount">
                <span>La suma de:</span> <strong>{formatMoney(s.net, s.currency)}</strong>
              </p>
              <p className="settle-check__words">{s.net_in_words}</p>
              <p className="settle-check__memo">
                Concepto: liquidación {s.folio} ({s.reason_label}) · lote {b.code}
              </p>
              <footer className="settle-check__sign">
                <div>
                  <span className="payslip__line" />
                  <span className="small">Firma autorizada</span>
                </div>
                <div>
                  <span className="payslip__line" />
                  <span className="small">Recibí conforme ({s.employee_code})</span>
                </div>
              </footer>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function CheckInput({ settlement, onSave }) {
  const [value, setValue] = useState(settlement.check_number ?? "");
  return (
    <form className="pay-actions" onSubmit={(e) => { e.preventDefault(); onSave(value); }}>
      <input className="settle-check-input" value={value} maxLength={30} onChange={(e) => setValue(e.target.value)} aria-label={`Cheque de ${settlement.folio}`} />
      {value !== (settlement.check_number ?? "") && (
        <button type="submit" className="button button--ghost button--sm">
          Guardar
        </button>
      )}
    </form>
  );
}
