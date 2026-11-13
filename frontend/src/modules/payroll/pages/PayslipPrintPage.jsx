import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAuth } from "../../../auth/AuthContext.jsx";
import { payrollApi } from "../api.js";
import PayslipDocument from "../components/PayslipDocument.jsx";

/**
 * Impresión de boletas (Fase 20): una o varias (`?ids=1,2`) o un lote completo (`?batch=ID`), una por página.
 * «Imprimir y registrar» marca las boletas como impresas en el inventario (suma una impresión) y abre el diálogo de
 * impresión del navegador; la firma del colaborador se registra después, al recibir la boleta firmada.
 */
export default function PayslipPrintPage() {
  const [params] = useSearchParams();
  const { hasPermission } = useAuth();
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [notice, setNotice] = useState(null);
  const ids = params.get("ids") ?? "";
  const batch = params.get("batch") ?? "";

  useEffect(() => {
    const controller = new AbortController();
    payrollApi
      .printable({ ids: ids || undefined, batch: batch || undefined }, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [ids, batch]);

  const slips = state.data?.results ?? [];
  const printAndRecord = () => {
    setNotice(null);
    payrollApi
      .payslipAction({ ids: slips.map((s) => s.id), action: "PRINT" })
      .then((b) => {
        setNotice({ ok: true, text: b.feedback });
        window.print();
      })
      .catch((err) => setNotice({ ok: false, text: err.message }));
  };

  return (
    <section className="card card--wide pay-print">
      <header className="card__header pay-print__bar">
        <div>
          <p className="muted small">
            <Link to="/payroll/inventory">Inventario de boletas</Link> ›
          </p>
          <h1 className="page-title">Impresión de boletas</h1>
          <p className="muted page-subtitle">
            {slips.length} boleta(s){batch && slips[0] ? ` del lote ${slips[0].batch}` : ""}. Cada boleta sale en su propia página con el espacio de firma
            del colaborador.
          </p>
        </div>
        <div className="pay-actions">
          {hasPermission("payroll.manage") && (
            <button type="button" className="button button--sm" disabled={!slips.length} onClick={printAndRecord}>
              Imprimir y registrar impresión
            </button>
          )}
          <button type="button" className="button button--ghost button--sm" disabled={!slips.length} onClick={() => window.print()}>
            Solo imprimir
          </button>
        </div>
      </header>
      {notice && (
        <div className={`alert ${notice.ok ? "alert--ok" : "alert--error"} flash pay-print__bar`} role="status">
          <p className="alert__text">{notice.text}</p>
        </div>
      )}
      {state.error && <p className="error-box">{state.error}</p>}
      {state.loading && <p className="muted">Cargando…</p>}
      {!state.loading && !slips.length && !state.error && <p className="empty">No hay boletas que imprimir.</p>}
      <div className="pay-print__pages">
        {slips.map((s) => (
          <PayslipDocument key={s.id} content={s.content} hash={s.content_hash} />
        ))}
      </div>
    </section>
  );
}
