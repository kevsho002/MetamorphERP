import { useEffect, useState } from "react";
import { formatDate, formatDateTime, formatMoney } from "../../hcm/lib/format.js";
import { payrollApi } from "../../payroll/api.js";
import PayslipDocument, { previewContent } from "../../payroll/components/PayslipDocument.jsx";

const STATUS_CLASS = { OPEN: "badge--warn", RESOLVED: "badge--ok", REJECTED: "badge--muted" };

/**
 * Fase 21 — Portal del colaborador: boletas PRELIMINARES de la planilla en curso (se actualizan con cada corrida del motor
 * antes del cierre) y boletas finales. Si algo no coincide, el agente reporta una excepción a su supervisor antes del freeze.
 */
export default function MyPayslipsPage() {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [reload, setReload] = useState(0);
  const [openFinal, setOpenFinal] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    payrollApi
      .myPayslips({ signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [reload]);

  const data = state.data;
  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Mis boletas</h1>
          <p className="muted page-subtitle">
            La boleta preliminar muestra el cálculo en curso de su planilla (horas programadas, horas pagadas, recargos y
            retenciones) y se actualiza con cada corrida antes del cierre. Si algo no coincide, repórtelo a su supervisor.
          </p>
        </div>
      </header>
      {state.loading && <p className="muted">Cargando…</p>}
      {state.error && <p className="error-box">{state.error}</p>}
      {data && (
        <>
          <h2 className="section-title">Boletas preliminares</h2>
          {data.preliminary.length === 0 && <p className="empty">No hay planillas en pre-cierre con su boleta publicada.</p>}
          {data.preliminary.map((b) => (
            <div key={b.run.id} className="portal-slip">
              <p className="muted small">
                Planilla {b.run.code} · corrida {b.run.iterations} · actualizada {formatDateTime(b.run.calculated_at)}
              </p>
              <PayslipDocument content={previewContent(b)} preliminary pdfHref={payrollApi.myPayslipPdfUrl("preliminary", b.run.id)} />
              <ExceptionForm payrollId={b.run.payroll_id} categories={data.categories} onDone={() => setReload((k) => k + 1)} />
              {b.exceptions.length > 0 && (
                <ul className="portal-exceptions">
                  {b.exceptions.map((x) => (
                    <li key={x.id}>
                      <span className={`badge ${STATUS_CLASS[x.status] ?? ""}`}>{x.status_label}</span> {x.category_label}
                      {x.work_date ? ` (${formatDate(x.work_date)})` : ""}: {x.description}
                      {x.response && <div className="muted small">Respuesta: {x.response}</div>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}

          <h2 className="section-title">Boletas finales</h2>
          {data.final.length === 0 && <p className="empty">Aún no tiene boletas de planillas cerradas.</p>}
          {data.final.length > 0 && (
            <div className="table-wrap">
              <table className="table table--compact">
                <thead>
                  <tr>
                    <th scope="col">Folio</th>
                    <th scope="col">Periodo</th>
                    <th scope="col">Pago</th>
                    <th scope="col" className="num">
                      Líquido
                    </th>
                    <th scope="col" />
                  </tr>
                </thead>
                <tbody>
                  {data.final.map((s) => (
                    <tr key={s.id}>
                      <td className="pay-nowrap">{s.folio}</td>
                      <td>
                        {formatDate(s.period_start)} – {formatDate(s.period_end)}
                      </td>
                      <td>{formatDate(s.payment_date)}</td>
                      <td className="num">{formatMoney(s.net_pay, s.content?.currency)}</td>
                      <td className="pay-nowrap">
                        <button type="button" className="button button--ghost button--sm" onClick={() => setOpenFinal(openFinal === s.id ? null : s.id)}>
                          {openFinal === s.id ? "Ocultar" : "Ver"}
                        </button>{" "}
                        <a className="button button--ghost button--sm" href={payrollApi.myPayslipPdfUrl("final", s.id)} download>
                          PDF
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {openFinal && (() => {
            const s = data.final.find((x) => x.id === openFinal);
            return s ? <PayslipDocument content={s.content} hash={s.content_hash} pdfHref={payrollApi.myPayslipPdfUrl("final", s.id)} /> : null;
          })()}
        </>
      )}
    </section>
  );
}

function ExceptionForm({ payrollId, categories, onDone }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ category: "HOURS", work_date: "", description: "" });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const submit = (e) => {
    e.preventDefault();
    setBusy(true);
    setNotice(null);
    payrollApi
      .reportException({ payroll_id: payrollId, ...form, work_date: form.work_date || undefined })
      .then((b) => {
        setNotice({ ok: true, text: b.feedback });
        setOpen(false);
        setForm({ category: "HOURS", work_date: "", description: "" });
        onDone();
      })
      .catch((err) => setNotice({ ok: false, text: err.message }))
      .finally(() => setBusy(false));
  };
  return (
    <div className="portal-exception-form">
      {notice && <p className={notice.ok ? "alert alert--ok" : "error-box"}>{notice.text}</p>}
      {!open ? (
        <button type="button" className="button button--ghost button--sm" onClick={() => setOpen(true)}>
          Reportar una excepción
        </button>
      ) : (
        <form className="pay-inline-form" onSubmit={submit}>
          <label className="field">
            <span className="field__label">Tipo</span>
            <select value={form.category} onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}>
              {categories.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field__label">Fecha (opcional)</span>
            <input type="date" value={form.work_date} onChange={(e) => setForm((f) => ({ ...f, work_date: e.target.value }))} />
          </label>
          <label className="field portal-exception-form__text">
            <span className="field__label">¿Qué no coincide?</span>
            <textarea rows={2} minLength={10} maxLength={1000} required value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} />
          </label>
          <button type="submit" className="button button--sm" disabled={busy}>
            {busy ? "Enviando…" : "Enviar a mi supervisor"}
          </button>
          <button type="button" className="button button--ghost button--sm" onClick={() => setOpen(false)}>
            Cancelar
          </button>
        </form>
      )}
    </div>
  );
}
