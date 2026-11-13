import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { formatDate, formatMoney, todayIso } from "../../hcm/lib/format.js";
import { MONTHS, RUN_STATUS, payrollApi } from "../api.js";

/**
 * Cálculo automático de planilla (Fase 20): un renglón por periodo de pago (quincena / mes) de los ciclos
 * predeterminados. «Calcular» toma el salario base, el Web Timer, los segmentos de WFM (ausencias, Lateness, permisos
 * sin goce), la adherencia guardada y las AP de pago aprobadas; la planilla se puede recalcular hasta cerrarla.
 */
export default function PayrollPage() {
  const [params, setParams] = useSearchParams();
  const thisYear = Number(todayIso().slice(0, 4));
  const year = Number(params.get("year")) || thisYear;
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [catalogs, setCatalogs] = useState(null);
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(null);
  const [notice, setNotice] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    const controller = new AbortController();
    payrollApi.catalogs({ signal: controller.signal }).then(setCatalogs).catch(() => {});
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    payrollApi
      .periods({ year }, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [year, reload]);

  const calculate = (p) => {
    setBusy(p.id);
    setNotice(null);
    payrollApi
      .calculate(p.id)
      .then((b) => {
        setNotice({ ok: true, text: b.feedback, runId: b.run.id });
        setReload((k) => k + 1);
      })
      .catch((err) => setNotice({ ok: false, text: err.message }))
      .finally(() => setBusy(null));
  };

  const data = state.data;
  const canManage = data?.can_manage;
  const years = useMemo(() => [...new Set([...(catalogs?.years ?? []), thisYear, year])].sort((a, b) => a - b), [catalogs, thisYear, year]);
  const byMonth = useMemo(() => {
    const out = new Map();
    for (const p of data?.results ?? []) {
      const m = Number(p.period_end.slice(5, 7)) - 1;
      if (!out.has(m)) out.set(m, []);
      out.get(m).push(p);
    }
    return [...out.entries()].sort((a, b) => a[0] - b[0]);
  }, [data]);
  const totals = useMemo(() => {
    const runs = (data?.results ?? []).map((p) => p.run).filter(Boolean);
    return {
      calculated: runs.filter((r) => r.status === "CALCULATED").length,
      closed: runs.filter((r) => r.status === "APPROVED" || r.status === "PAID").length,
      net: runs.filter((r) => r.status !== "CANCELLED").reduce((acc, r) => acc + Number(r.total_net), 0),
      currency: runs[0]?.currency ?? "USD",
    };
  }, [data]);

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Cálculo de planilla</h1>
          <p className="muted page-subtitle">
            Salario devengado y líquido por periodo de pago con el Web Timer, las AP de pago aprobadas, los segmentos de WFM y la adherencia guardada.
            Al cerrar la planilla se generan las boletas de todos los colaboradores y se envían al inventario de RRHH.
          </p>
        </div>
        <Link className="button button--ghost button--sm" to="/payroll/settings">
          Parámetros salariales
        </Link>
      </header>

      <div className="filters" role="search">
        <div className="field">
          <span className="field__label">Año</span>
          <div className="segmented" role="tablist" aria-label="Año">
            {years.map((y) => (
              <button key={y} type="button" role="tab" aria-selected={y === year} className={`segmented__item${y === year ? " segmented__item--active" : ""}`}
                onClick={() => setParams(y === thisYear ? {} : { year: String(y) }, { replace: true })}>
                {y}
              </button>
            ))}
          </div>
        </div>
      </div>

      <dl className="kpis">
        <div className="kpi">
          <dt>Planillas calculadas (abiertas)</dt>
          <dd>{totals.calculated}</dd>
        </div>
        <div className="kpi kpi--ok">
          <dt>Cerradas / pagadas</dt>
          <dd>{totals.closed}</dd>
        </div>
        <div className="kpi">
          <dt>Líquido total del año</dt>
          <dd>{formatMoney(totals.net, totals.currency)}</dd>
        </div>
      </dl>

      {notice && (
        <div className={`alert ${notice.ok ? "alert--ok" : "alert--error"} flash`} role="status">
          <p className="alert__text">
            {notice.text}{" "}
            {notice.runId && (
              <button type="button" className="link-button" onClick={() => navigate(`/payroll/runs/${notice.runId}`)}>
                Ver la planilla
              </button>
            )}
          </p>
        </div>
      )}
      {state.error && <p className="error-box">{state.error}</p>}
      {state.loading && !data && <p className="muted">Cargando periodos…</p>}
      {data && data.results.length === 0 && <p className="empty">No hay periodos de pago de ciclos predeterminados en {year}. Genérelos en Horarios › Ciclos de pago.</p>}

      {byMonth.map(([m, periods]) => (
        <section key={m} className="pay-month" aria-label={MONTHS[m]}>
          <h2 className="section-title">{MONTHS[m]}</h2>
          <div className="table-wrap">
            <table className="table pay-periods">
              <thead>
                <tr>
                  <th scope="col">Periodo</th>
                  <th scope="col">Asistencia (cortes)</th>
                  <th scope="col">Planilla</th>
                  <th scope="col" className="num">
                    Devengado
                  </th>
                  <th scope="col" className="num">
                    Líquido
                  </th>
                  <th scope="col">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {periods.map((p) => {
                  const run = p.run;
                  const st = run ? RUN_STATUS[run.status] : null;
                  const closed = run && (run.status === "APPROVED" || run.status === "PAID");
                  return (
                    <tr key={p.id}>
                      <td>
                        <strong>{p.code}</strong> <span className="muted small">{p.cycle}</span>
                        <div className="muted small">
                          {p.pay_frequency_label} · {formatDate(p.period_start)}–{formatDate(p.period_end)} · pago {formatDate(p.payment_date)}
                        </div>
                      </td>
                      <td className="small">
                        {p.cutoffs.length === 0 && <span className="muted">Fechas del periodo</span>}
                        {p.cutoffs.map((c) => (
                          <div key={c.code}>
                            {formatDate(c.start)}–{formatDate(c.end)}{" "}
                            <span className={`badge ${c.status === "CLOSED" ? "badge--ok" : "badge--warn"}`}>{c.status === "CLOSED" ? "Cerrado" : "Abierto"}</span>
                          </div>
                        ))}
                      </td>
                      <td>
                        {st ? <span className={`badge ${st.cls}`}>{st.label}</span> : <span className="muted small">Sin calcular</span>}
                        {run && <div className="muted small">{run.employees} colaboradores{run.warnings.length ? ` · ${run.warnings.length} advertencias` : ""}</div>}
                      </td>
                      <td className="num">{run ? formatMoney(run.total_gross, run.currency) : "—"}</td>
                      <td className="num">{run ? formatMoney(run.total_net, run.currency) : "—"}</td>
                      <td>
                        <div className="pay-actions">
                          {run && (
                            <Link className="button button--ghost button--sm" to={`/payroll/runs/${run.id}`}>
                              Ver
                            </Link>
                          )}
                          {canManage && !closed && (
                            <button type="button" className="button button--sm" disabled={busy === p.id} onClick={() => calculate(p)}>
                              {busy === p.id ? "Calculando…" : run && run.status !== "CANCELLED" ? "Recalcular" : "Calcular"}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </section>
  );
}
