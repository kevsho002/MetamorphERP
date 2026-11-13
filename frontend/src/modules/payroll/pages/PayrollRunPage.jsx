import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { formatDate, formatDateTime, formatMoney } from "../../hcm/lib/format.js";
import { useTimeFormat } from "../../../app/timeFormat.js";
import { RUN_STATUS, num, payrollApi } from "../api.js";
import PayslipDocument, { previewContent } from "../components/PayslipDocument.jsx";

/**
 * Planilla de un periodo (Fase 20): totales, advertencias del cálculo y detalle por colaborador. Clic en un colaborador
 * abre su boleta (vista previa mientras la planilla está abierta). Cerrar exige los cortes de asistencia cerrados,
 * congela la planilla en SQL Server y genera las boletas en masa (un lote por departamento).
 */
export default function PayrollRunPage() {
  const { id } = useParams();
  const time = useTimeFormat();
  const [showIterations, setShowIterations] = useState(false);
  const [filters, setFilters] = useState({ search: "", cost_center: "" });
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [catalogs, setCatalogs] = useState(null);
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(null);
  const [notice, setNotice] = useState(null);
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    payrollApi.catalogs({ signal: controller.signal }).then(setCatalogs).catch(() => {});
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    const t = setTimeout(() => {
      payrollApi
        .run(id, { search: filters.search || undefined, cost_center: filters.cost_center || undefined }, { signal: controller.signal })
        .then((data) => setState({ loading: false, data, error: null }))
        .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    }, 200);
    return () => {
      clearTimeout(t);
      controller.abort();
    };
  }, [id, filters, reload]);

  const act = (action, payload) => {
    setBusy(action);
    setNotice(null);
    payrollApi
      .runAction(id, action, payload)
      .then((b) => {
        setNotice({ ok: true, text: b.feedback });
        setCancelling(false);
        setReload((k) => k + 1);
      })
      .catch((err) => setNotice({ ok: false, text: err.message }))
      .finally(() => setBusy(null));
  };
  const closeModal = useCallback(() => setSelected(null), []);

  const data = state.data;
  const run = data?.run;
  const st = run ? RUN_STATUS[run.status] : null;
  const open = run && (run.status === "CALCULATED" || run.status === "DRAFT");
  const canManage = data?.can_manage;
  const ccOptions = (catalogs?.cost_centers ?? []).filter((c) => !run || c.country === run.country);

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <p className="muted small">
            <Link to="/payroll">Cálculo de planilla</Link> ›
          </p>
          <h1 className="page-title">
            Planilla {run?.code ?? "…"} {st && <span className={`badge ${st.cls}`}>{st.label}</span>}
          </h1>
          {run && (
            <p className="muted page-subtitle">
              {run.pay_frequency_label} del {formatDate(run.period_start)} al {formatDate(run.period_end)} · pago {formatDate(run.payment_date)} ·
              asistencia {run.windows.map((w) => `${formatDate(w.start)}–${formatDate(w.end)}`).join(", ")} · parámetros «{run.setting}»
            </p>
          )}
        </div>
        {run && (
          <div className="pay-actions">
            <a className="button button--ghost button--sm" href={payrollApi.runCsvUrl(id, {})}>
              Exportar CSV
            </a>
            {run.payslips?.total > 0 && (
              <Link className="button button--ghost button--sm" to={`/payroll/inventory?payroll=${encodeURIComponent(run.code)}`}>
                Boletas ({run.payslips.total})
              </Link>
            )}
            {canManage && open && (
              <>
                <button type="button" className="button button--ghost button--sm" disabled={!!busy} onClick={() => act("recalculate")}>
                  {busy === "recalculate" ? "Recalculando…" : "Recalcular"}
                </button>
                <button type="button" className="button button--sm" disabled={!!busy}
                  onClick={() => window.confirm("Cerrar la planilla la congela y genera las boletas de todos los colaboradores. ¿Continuar?") && act("approve")}>
                  {busy === "approve" ? "Cerrando…" : "Cerrar y generar boletas"}
                </button>
                <button type="button" className="button button--danger button--sm" disabled={!!busy} onClick={() => setCancelling((v) => !v)}>
                  Anular
                </button>
              </>
            )}
            {canManage && run.status === "APPROVED" && (
              <button type="button" className="button button--sm" disabled={!!busy} onClick={() => act("pay")}>
                Marcar pagada
              </button>
            )}
          </div>
        )}
      </header>

      {cancelling && (
        <form className="pay-inline-form" onSubmit={(e) => { e.preventDefault(); act("cancel", { reason }); }}>
          <label className="field">
            <span className="field__label">Motivo de la anulación</span>
            <input value={reason} maxLength={500} required onChange={(e) => setReason(e.target.value)} />
          </label>
          <button type="submit" className="button button--danger button--sm" disabled={!!busy || !reason.trim()}>
            Anular planilla
          </button>
        </form>
      )}
      {notice && (
        <div className={`alert ${notice.ok ? "alert--ok" : "alert--error"} flash`} role="status">
          <p className="alert__text">{notice.text}</p>
        </div>
      )}
      {state.error && <p className="error-box">{state.error}</p>}

      {run && (
        <>
          <dl className="kpis">
            <div className="kpi">
              <dt>Colaboradores</dt>
              <dd>{run.employees}</dd>
            </div>
            <div className="kpi">
              <dt>Devengado</dt>
              <dd>{formatMoney(run.total_gross, run.currency)}</dd>
            </div>
            <div className="kpi kpi--warn">
              <dt>Descuentos</dt>
              <dd>{formatMoney(run.total_deductions, run.currency)}</dd>
            </div>
            <div className="kpi kpi--ok">
              <dt>Líquido a pagar</dt>
              <dd>{formatMoney(run.total_net, run.currency)}</dd>
            </div>
            <div className="kpi kpi--muted" title="Devengado + aportes patronales (ISSS, AFP, INSAFORP)">
              <dt>Costo patronal</dt>
              <dd>{formatMoney(run.total_employer_cost, run.currency)}</dd>
            </div>
            {run.hours && (
              <>
                <div className="kpi" title="Horas programadas del horario vigente en los cortes del periodo (base del rate por hora)">
                  <dt>Horas programadas</dt>
                  <dd>{time.seconds(run.hours.scheduled_seconds)}</dd>
                </div>
                <div className="kpi" title="Horas pagables validadas (Web Timer / adherencia y AP)">
                  <dt>Horas pagadas</dt>
                  <dd>{time.seconds(run.hours.paid_seconds)}</dd>
                </div>
              </>
            )}
            <div className={`kpi${run.open_exceptions ? " kpi--warn" : ""}`} title="Excepciones reportadas por los agentes sobre su boleta preliminar">
              <dt>Excepciones abiertas</dt>
              <dd>
                <Link to={`/portal/exceptions?payroll=${run.payroll_id}`}>{run.open_exceptions}</Link>
              </dd>
            </div>
          </dl>
          {open && (
            <p className="muted small pay-preliminary">
              Pre-cierre: {run.iterations} corrida(s) del motor
              {run.preliminary_published_at ? ` · boletas preliminares publicadas en el portal ${formatDateTime(run.preliminary_published_at)}` : ""}.
              El cierre (freeze) exige resolver las excepciones abiertas.{" "}
              <button type="button" className="link-button" onClick={() => setShowIterations((v) => !v)}>
                {showIterations ? "Ocultar corridas" : "Ver corridas"}
              </button>
            </p>
          )}
          {showIterations && <IterationsPanel runId={id} currency={run.currency} reload={reload} />}
          <p className="muted small">
            Calculada {formatDateTime(run.calculated_at)} por {run.calculated_by ?? "el sistema"}
            {run.approved_at ? ` · cerrada ${formatDateTime(run.approved_at)} por ${run.approved_by}` : ""}
            {run.paid_at ? ` · pagada ${formatDateTime(run.paid_at)}` : ""}
            {run.cancel_reason ? ` · anulada: ${run.cancel_reason}` : ""}
          </p>
          {run.warnings.length > 0 && (
            <details className="pay-warnings">
              <summary>{run.warnings.length} advertencias del cálculo</summary>
              <ul>
                {run.warnings.map((w, i) => (
                  <li key={i}>
                    {w.employee_code && <strong>{w.employee_code}: </strong>}
                    {w.message}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}

      <div className="filters" role="search">
        <label className="field filters__search">
          <span className="field__label">Buscar</span>
          <input type="search" placeholder="ID o nombre" value={filters.search} onChange={(e) => setFilters((f) => ({ ...f, search: e.target.value }))} />
        </label>
        <label className="field">
          <span className="field__label">Departamento</span>
          <select value={filters.cost_center} onChange={(e) => setFilters((f) => ({ ...f, cost_center: e.target.value }))}>
            <option value="">Todos</option>
            {ccOptions.map((c) => (
              <option key={c.code} value={c.code}>
                {c.code} · {c.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="table-wrap" aria-busy={state.loading}>
        <table className="table pay-detail">
          <thead>
            <tr>
              <th scope="col">Colaborador</th>
              <th scope="col" className="num">
                Rate / h
              </th>
              <th scope="col" className="num">
                Programadas
              </th>
              <th scope="col" className="num">
                Pagadas
              </th>
              <th scope="col" className="num">
                Nocturnas
              </th>
              <th scope="col" className="num">
                Feriado
              </th>
              <th scope="col" className="num">
                Horas extra ($)
              </th>
              <th scope="col" className="num">
                Otros devengos
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
              <th scope="col">Boleta</th>
            </tr>
          </thead>
          <tbody>
            {(data?.rows ?? []).map((r) => (
              <tr key={r.detail_id}>
                <td>
                  <button type="button" className="link-button" onClick={() => setSelected(r.employee_code)}>
                    {r.full_name}
                  </button>
                  <div className="muted small">
                    {r.employee_code} · {r.cost_center ?? "sin centro de costos"} · base {num(r.base_salary)}
                  </div>
                </td>
                <td className="num">{num(r.hourly_rate, 4)}</td>
                <td className="num">{time.hours(r.horas_programadas_hours ?? 0)}</td>
                <td className={`num${Number(r.horas_no_pagadas_hours) > 0 ? " text-error" : ""}`}
                  title={Number(r.horas_no_pagadas_hours) > 0 ? `No laboradas: ${time.hours(r.horas_no_pagadas_hours)}` : undefined}>
                  {time.hours(r.horas_pagadas_hours ?? 0)}
                </td>
                <td className="num">{r.nocturnidad_hours ? time.hours(r.nocturnidad_hours) : "—"}</td>
                <td className="num">{r.feriado_hours ? time.hours(r.feriado_hours) : "—"}</td>
                <td className="num">{num(r.overtime_amount)}</td>
                <td className="num">{num(r.other_earnings)}</td>
                <td className="num">{num(r.gross_pay)}</td>
                <td className="num">{num(r.total_deductions)}</td>
                <td className="num">
                  <strong>{num(r.net_pay)}</strong>
                </td>
                <td className="small">
                  {r.payslip ? (
                    <>
                      {r.payslip.folio}
                      <div className="muted">
                        {r.payslip.printed ? "Impresa" : "Por imprimir"} · {r.payslip.signed ? "firmada" : "sin firma"}
                      </div>
                    </>
                  ) : (
                    <span className="muted">Al cerrar</span>
                  )}
                </td>
              </tr>
            ))}
            {!state.loading && data && data.rows.length === 0 && (
              <tr>
                <td colSpan={12} className="empty">
                  No hay colaboradores con estos filtros.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {selected && <BreakdownModal runId={id} code={selected} onClose={closeModal} />}
    </section>
  );
}

/** Corridas del motor antes del cierre (manuales y diarias automáticas) con su evolución de horas y montos. */
function IterationsPanel({ runId, currency, reload }) {
  const time = useTimeFormat();
  const [rows, setRows] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    payrollApi
      .iterations(runId, { signal: controller.signal })
      .then((d) => setRows(d.results))
      .catch(() => setRows([]));
    return () => controller.abort();
  }, [runId, reload]);
  if (!rows) return <p className="muted">Cargando corridas…</p>;
  return (
    <div className="table-wrap">
      <table className="table table--compact pay-iterations">
        <caption className="muted small">Corridas preliminares (pre-cierre)</caption>
        <thead>
          <tr>
            <th scope="col">#</th>
            <th scope="col">Fecha</th>
            <th scope="col">Origen</th>
            <th scope="col" className="num">Colaboradores</th>
            <th scope="col" className="num">Programadas</th>
            <th scope="col" className="num">Pagadas</th>
            <th scope="col" className="num">Devengado</th>
            <th scope="col" className="num">Líquido</th>
            <th scope="col" className="num">Excepciones</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((i) => (
            <tr key={i.number}>
              <td>{i.number}</td>
              <td className="pay-nowrap">{formatDateTime(i.calculated_at)}</td>
              <td>
                {i.trigger_label}
                {i.calculated_by ? ` · ${i.calculated_by}` : ""}
              </td>
              <td className="num">{i.employees}</td>
              <td className="num">{time.seconds(i.scheduled_seconds)}</td>
              <td className="num">{time.seconds(i.paid_seconds)}</td>
              <td className="num">{formatMoney(i.gross, currency)}</td>
              <td className="num">{formatMoney(i.net, currency)}</td>
              <td className="num">{i.open_exceptions}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BreakdownModal({ runId, code, onClose }) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const ref = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    payrollApi
      .breakdown(runId, code, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [runId, code]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const data = state.data;
  return (
    <div className="pay-modal__backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="pay-modal" role="dialog" aria-modal="true" aria-label={`Boleta de ${code}`} tabIndex={-1} ref={ref}>
        <div className="pay-modal__bar">
          <strong>{data ? `${data.employee.name} · ${data.employee.code}` : code}</strong>
          <div className="pay-actions">
            {data?.payslip && (
              <Link className="button button--ghost button--sm" to={`/payroll/payslips/print?ids=${data.payslip.id}`}>
                Imprimir
              </Link>
            )}
            <button type="button" className="button button--ghost button--sm" onClick={onClose} aria-label="Cerrar">
              ✕
            </button>
          </div>
        </div>
        <div className="pay-modal__body">
          {state.loading && <p className="muted">Cargando…</p>}
          {state.error && <p className="error-box">{state.error}</p>}
          {data && <PayslipDocument content={previewContent(data)} preview={!data.payslip} />}
        </div>
      </div>
    </div>
  );
}
