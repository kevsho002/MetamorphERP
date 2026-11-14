import { useEffect, useState } from "react";
import { formatDate, formatDateTime, formatMoney } from "../../hcm/lib/format.js";
import { payrollApi } from "../../payroll/api.js";
import PayslipDocument, { previewContent } from "../../payroll/components/PayslipDocument.jsx";
import DailyPayslip, { DailyDaysTable } from "../../payroll/components/DailyPayslip.jsx";
import Pagination from "../../../components/ui/Pagination.jsx";
import { formatHours, useTimeFormat } from "../../../app/timeFormat.js";

const STATUS_CLASS = { OPEN: "badge--warn", RESOLVED: "badge--ok", REJECTED: "badge--muted" };
const CUTOFF_STATE = { FINAL: "badge--ok", PRELIMINARY: "badge--warn", PENDING: "badge--muted" };
const PAGE_SIZES = [3, 6, 12, 24];

/**
 * Fase 21 — Portal del colaborador: boletas PRELIMINARES de la planilla en curso (se actualizan con cada corrida del motor
 * antes del cierre) y boletas finales. Si algo no coincide, el agente reporta una excepción a su supervisor antes del freeze.
 */
export default function MyPayslipsPage() {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [reload, setReload] = useState(0);
  const [openFinal, setOpenFinal] = useState(null);
  const [finalQuery, setFinalQuery] = useState({ year: "", page: 1 }); // Fase 27: boletas finales por año y página

  useEffect(() => {
    const controller = new AbortController();
    payrollApi
      .myPayslips({ year: finalQuery.year || undefined, page: finalQuery.page, page_size: 6 }, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [reload, finalQuery]);

  const data = state.data;
  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Mis boletas</h1>
          <p className="muted page-subtitle">
            La boleta preliminar muestra el cálculo en curso de su planilla (horas programadas, horas pagadas, recargos y
            retenciones) y se actualiza con cada corrida antes del cierre. Debajo de cada boleta está el desglose DÍA POR DÍA
            de los cortes internos con lo que cada día suma en dinero. Si algo no coincide, repórtelo a su supervisor.
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
              <DailyPayslip daily={b.daily} currency={b.run.currency} />
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

          <CutoffHistory reload={reload} currency={data.preliminary[0]?.run.currency ?? data.final[0]?.content?.currency} />

          <div className="slip-history__head">
            <h2 className="section-title">Boletas finales</h2>
            {data.final_page?.years?.length > 0 && (
              <label className="field field--inline">
                <span className="field__label">Año</span>
                <select value={finalQuery.year} onChange={(e) => { setOpenFinal(null); setFinalQuery({ year: e.target.value, page: 1 }); }}>
                  <option value="">Todos</option>
                  {data.final_page.years.map((y) => (
                    <option key={y} value={y}>
                      {y}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          {data.final.length === 0 && <p className="empty">Aún no tiene boletas de planillas cerradas{finalQuery.year ? ` en ${finalQuery.year}` : ""}.</p>}
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
          {data.final_page && (
            <Pagination page={data.final_page.page} pageSize={data.final_page.page_size} count={data.final_page.count}
              onPage={(n) => { setOpenFinal(null); setFinalQuery((q) => ({ ...q, page: n })); }} />
          )}
          {openFinal && (() => {
            const s = data.final.find((x) => x.id === openFinal);
            return s ? (
              <>
                <PayslipDocument content={s.content} hash={s.content_hash} pdfHref={payrollApi.myPayslipPdfUrl("final", s.id)} />
                {s.content?.daily ? (
                  <DailyPayslip daily={s.content.daily} currency={s.content.currency} />
                ) : (
                  <p className="muted small">Boleta cerrada antes de la Fase 25: no incluye el desglose diario.</p>
                )}
              </>
            ) : null;
          })()}
        </>
      )}
    </section>
  );
}

/**
 * Fase 27 — Historial de la boleta por CORTE interno de asistencia: cada corte en el que el colaborador estuvo activo
 * es una sub-sección desplegable con su desglose diario. Se filtra por año y se navega por páginas (el servidor
 * devuelve solo la página pedida).
 */
function CutoffHistory({ reload, currency }) {
  useTimeFormat();
  const [query, setQuery] = useState({ year: "", page: 1, size: 6 });
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [onlyPaid, setOnlyPaid] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    payrollApi
      .myCutoffs({ year: query.year || undefined, page: query.page, page_size: query.size }, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [query, reload]);

  const data = state.data;
  return (
    <section className="slip-history" aria-label="Historial por corte">
      <div className="slip-history__head">
        <div>
          <h2 className="section-title">Historial por corte de asistencia</h2>
          <p className="muted small">Cada corte en el que estuvo activo, del más reciente al más antiguo, con lo que cada día sumó a su pago.</p>
        </div>
        <div className="slip-history__filters">
          <label className="field field--inline">
            <span className="field__label">Año</span>
            <select value={query.year} onChange={(e) => setQuery((q) => ({ ...q, year: e.target.value, page: 1 }))}>
              <option value="">Todos</option>
              {(data?.years ?? []).map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </label>
          <label className="field field--inline">
            <span className="field__label">Por página</span>
            <select value={query.size} onChange={(e) => setQuery((q) => ({ ...q, size: Number(e.target.value), page: 1 }))}>
              {PAGE_SIZES.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <label className="checkbox small">
            <input type="checkbox" checked={onlyPaid} onChange={(e) => setOnlyPaid(e.target.checked)} /> Solo días con pago o descuento
          </label>
        </div>
      </div>
      {state.error && <p className="error-box">{state.error}</p>}
      {state.loading && !data && <p className="muted">Cargando cortes…</p>}
      {data && data.results.length === 0 && (
        <p className="empty">{query.year ? `No estuvo activo en cortes de ${query.year}.` : "Aún no tiene cortes de asistencia."}</p>
      )}
      {data?.results.map((c, i) => {
        const days = c.days.filter((d) => !onlyPaid || Number(d.total) !== 0);
        return (
          <details key={c.id} className="slip-cutoff" open={i === 0 && data.page === 1}>
            <summary className="slip-cutoff__summary">
              <span className="slip-cutoff__title">
                <strong>Corte {c.code}</strong>
                <span className="muted small">
                  {formatDate(c.start)} al {formatDate(c.end)}
                </span>
              </span>
              <span className={`badge ${CUTOFF_STATE[c.state] ?? ""}`}>{c.state_label}</span>
              <span className="slip-cutoff__figures small">
                {c.state === "PENDING" ? (
                  <span className="muted">Se paga el {formatDate(c.pay_period.payment_date)}</span>
                ) : (
                  <>
                    {formatHours(c.paid_h)} h pagables · <strong>{formatMoney(c.total, c.currency ?? currency)}</strong>
                  </>
                )}
              </span>
            </summary>
            <div className="slip-cutoff__body">
              <p className="muted small">
                Periodo de pago {c.pay_period.code} · pago {formatDate(c.pay_period.payment_date)}
                {c.payroll_code ? ` · planilla ${c.payroll_code}` : ""} · corte {c.status_label.toLowerCase()}
              </p>
              {c.state === "PENDING" ? (
                <p className="empty">El desglose aparecerá cuando Planillas calcule y publique la boleta de este corte.</p>
              ) : days.length === 0 ? (
                <p className="empty">Sin días con pago en este corte.</p>
              ) : (
                <DailyDaysTable days={days} currency={c.currency ?? currency} />
              )}
            </div>
          </details>
        );
      })}
      {data && (
        <Pagination page={data.page} pageSize={data.page_size} count={data.count} onPage={(n) => setQuery((q) => ({ ...q, page: n }))} />
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
