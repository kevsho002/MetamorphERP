import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Pagination from "../../../components/ui/Pagination.jsx";
import { formatDate, todayIso } from "../../hcm/lib/format.js";
import { schedulingApi } from "../api.js";
import { useSchedulingCatalogs } from "../hooks/useSchedulingCatalogs.js";
import { FLAG_CLASS, addDays, fmtMinutes, mondayOf } from "../lib/time.js";

const PAGE_SIZE = 100;

/** Horas teóricas (turno asignado) frente a reales (registros de tiempo), por FECHA DE OCURRENCIA. */
export default function HoursReportPage() {
  const catalogs = useSchedulingCatalogs();
  const [params, setParams] = useSearchParams();
  const monday = mondayOf(todayIso());
  const filters = useMemo(
    () => ({
      period: params.get("period") ?? "",
      basis: params.get("basis") ?? "cutoff",
      from: params.get("from") ?? monday,
      to: params.get("to") ?? addDays(params.get("from") ?? monday, 6),
      country: params.get("country") ?? "",
      flag: params.get("flag") ?? "",
      tolerance: params.get("tolerance") ?? "0",
      search: params.get("search") ?? "",
      page: Number(params.get("page") ?? 1) || 1,
    }),
    [params, monday],
  );
  const [searchText, setSearchText] = useState(filters.search);
  const [periodsState, setPeriodsState] = useState({ cycles: [] });
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [view, setView] = useState("days");

  const update = (changes) => {
    const next = { ...filters, page: 1, ...changes };
    const query = {};
    Object.entries(next).forEach(([k, v]) => {
      if (v !== "" && v !== null && !(k === "page" && v === 1) && !(k === "basis" && !next.period) && !(k === "tolerance" && v === "0")) query[k] = String(v);
    });
    if (next.period) {
      delete query.from;
      delete query.to;
    }
    setParams(query, { replace: true });
  };

  useEffect(() => {
    if (searchText === filters.search) return undefined;
    const timer = setTimeout(() => update({ search: searchText.trim() }), 350);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchText]);

  useEffect(() => {
    const controller = new AbortController();
    schedulingApi
      .payCycles({ year: (filters.from || todayIso()).slice(0, 4) }, { signal: controller.signal })
      .then((data) => setPeriodsState({ cycles: data.results }))
      .catch(() => {});
    return () => controller.abort();
  }, [filters.from]);

  const query = useMemo(() => {
    const q = { ...filters, page_size: PAGE_SIZE };
    if (filters.period) {
      delete q.from;
      delete q.to;
    } else delete q.basis;
    return q;
  }, [filters]);

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    schedulingApi
      .report(query, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [query]);

  const data = state.data;
  const totals = data?.totals ?? {};

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Horas teóricas vs reales</h1>
          <p className="muted page-subtitle">
            Cada hora cuenta en el día calendario en que ocurrió: un turno de 22:00 a 06:00 aporta 2 h a su fecha de inicio y 6 h
            al día siguiente, y ambas porciones conservan la fecha del turno. Fuente en SQL: <code>dbo.vw_SchTimeByOccurrenceDate</code>.
          </p>
        </div>
        <a className="button button--ghost" href={schedulingApi.reportCsvUrl(query)} download>
          Exportar CSV
        </a>
      </header>

      <div className="filters" role="search">
        <label className="field">
          <span className="field__label">Corte de nómina</span>
          <select value={filters.period} onChange={(e) => update({ period: e.target.value })}>
            <option value="">Rango libre</option>
            {periodsState.cycles.map((c) => (
              <optgroup key={c.code} label={`${c.name} (${c.country})`}>
                {c.periods.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.code} · asistencia {formatDate(p.cutoff_start)}–{formatDate(p.cutoff_end)}
                    {p.status === "CLOSED" ? " · cerrado" : ""}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </label>
        {filters.period ? (
          <label className="field">
            <span className="field__label">Fechas</span>
            <select value={filters.basis} onChange={(e) => update({ basis: e.target.value })}>
              <option value="cutoff">Ventana del corte (asistencia)</option>
              <option value="period">Fechas del periodo de pago</option>
            </select>
          </label>
        ) : (
          <>
            <label className="field">
              <span className="field__label">Desde</span>
              <input type="date" value={filters.from} onChange={(e) => e.target.value && update({ from: e.target.value, to: filters.to < e.target.value ? e.target.value : filters.to })} />
            </label>
            <label className="field">
              <span className="field__label">Hasta</span>
              <input type="date" value={filters.to} min={filters.from} onChange={(e) => e.target.value && update({ to: e.target.value })} />
            </label>
          </>
        )}
        <label className="field">
          <span className="field__label">País</span>
          <select value={filters.country} onChange={(e) => update({ country: e.target.value })}>
            <option value="">Todos</option>
            {catalogs.countries.map((c) => (
              <option key={c.code} value={c.code}>
                {c.code} — {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Resultado</span>
          <select value={filters.flag} onChange={(e) => update({ flag: e.target.value })}>
            <option value="">Todos</option>
            {catalogs.flags.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Tolerancia (min)</span>
          <input type="number" min={0} max={240} value={filters.tolerance} onChange={(e) => update({ tolerance: e.target.value || "0" })} />
        </label>
        <label className="field filters__search">
          <span className="field__label">Buscar</span>
          <input type="search" placeholder="Nombre o ID corporativo" value={searchText} onChange={(e) => setSearchText(e.target.value)} />
        </label>
      </div>

      {state.error && <p className="error-box">{state.error}</p>}
      {data && (
        <>
          <dl className="kpis">
            <div className="kpi">
              <dt>Período</dt>
              <dd>
                {formatDate(data.from)} – {formatDate(data.to)}
              </dd>
            </div>
            <div className="kpi">
              <dt>Teórico</dt>
              <dd>{fmtMinutes(totals.scheduled_minutes ?? 0)}</dd>
            </div>
            <div className="kpi">
              <dt>Real</dt>
              <dd>{fmtMinutes(totals.worked_minutes ?? 0)}</dd>
            </div>
            <div className={`kpi ${(totals.variance_minutes ?? 0) < 0 ? "kpi--warn" : "kpi--ok"}`}>
              <dt>Diferencia</dt>
              <dd>{fmtMinutes(totals.variance_minutes ?? 0)}</dd>
            </div>
            <div className="kpi">
              <dt>Nocturno real</dt>
              <dd>{fmtMinutes(totals.worked_night_minutes ?? 0)}</dd>
            </div>
            <div className={`kpi ${totals.days_absent ? "kpi--error" : "kpi--muted"}`}>
              <dt>Días sin registro</dt>
              <dd>{totals.days_absent ?? 0}</dd>
            </div>
          </dl>
          <div className="segmented" role="tablist" aria-label="Vista">
            <button type="button" className={`segmented__item${view === "days" ? " segmented__item--active" : ""}`} onClick={() => setView("days")}>
              Por fecha de ocurrencia
            </button>
            <button type="button" className={`segmented__item${view === "employees" ? " segmented__item--active" : ""}`} onClick={() => setView("employees")}>
              Totales por empleado ({data.by_employee.length})
            </button>
          </div>
        </>
      )}

      {view === "days" ? (
        <div className="table-wrap" aria-busy={state.loading}>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Empleado</th>
                <th scope="col">Fecha de ocurrencia</th>
                <th scope="col">AP de horario</th>
                <th scope="col">Teórico</th>
                <th scope="col">Real</th>
                <th scope="col">Nocturno (teórico / real)</th>
                <th scope="col">Recargo nocturno</th>
                <th scope="col">Diferencia</th>
                <th scope="col">Resultado</th>
              </tr>
            </thead>
            <tbody>
              {(data?.results ?? []).map((r) => (
                <tr key={`${r.employee_code}-${r.occurrence_date}`}>
                  <td>
                    <strong>{r.full_name}</strong>
                    <br />
                    <Link to={`/hcm/employees/${r.employee_code}?tab=schedule`}>
                      <code>{r.employee_code}</code>
                    </Link>
                  </td>
                  <td>
                    <Link className="occurrence-link" to={`/scheduling/employees/${r.employee_code}/days/${r.occurrence_date}`} title="Ver el desglose del día">
                      <span className="small">{r.weekday}</span> {formatDate(r.occurrence_date)}
                    </Link>
                  </td>
                  <td className="small">
                    {r.actions.length
                      ? r.actions.map((f, i) => (
                          <span key={f}>
                            {i > 0 && " + "}
                            <Link to={`/personnel-actions/${f}`}>
                              <code>{f}</code>
                            </Link>
                          </span>
                        ))
                      : "—"}
                    {r.shift_dates.some((s) => s !== r.occurrence_date) && (
                      <span className="muted"> (turno del {r.shift_dates.filter((s) => s !== r.occurrence_date).map(formatDate).join(", ")})</span>
                    )}
                  </td>
                  <td>{fmtMinutes(r.scheduled_minutes)}</td>
                  <td>{fmtMinutes(r.worked_minutes)}</td>
                  <td>
                    {fmtMinutes(r.scheduled_night_minutes)} / {fmtMinutes(r.worked_night_minutes)}
                  </td>
                  <td className="small">
                    {r.worked_night_minutes ? `+${fmtMinutes(r.night_premium_minutes)} (${r.night_surcharge_percent ?? 0} %)` : "—"}
                  </td>
                  <td className={r.variance_minutes < 0 ? "text-error" : undefined}>{fmtMinutes(r.variance_minutes)}</td>
                  <td>
                    <span className={`badge ${FLAG_CLASS[r.flag] ?? "badge--muted"}`}>{r.flag_label}</span>
                  </td>
                </tr>
              ))}
              {!state.loading && data && data.results.length === 0 && (
                <tr>
                  <td colSpan={9} className="empty">
                    No hay horas programadas ni registradas con estos filtros.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Empleado</th>
                <th scope="col">Teórico</th>
                <th scope="col">Real</th>
                <th scope="col">Diferencia</th>
                <th scope="col">Nocturno real</th>
                <th scope="col">Recargo nocturno (equivalente)</th>
                <th scope="col">Días sin registro</th>
                <th scope="col">Días con menos / más horas</th>
              </tr>
            </thead>
            <tbody>
              {(data?.by_employee ?? []).map((e) => (
                <tr key={e.employee_code}>
                  <td>
                    <strong>{e.full_name}</strong>
                    <br />
                    <code>{e.employee_code}</code> <span className="muted small">{e.country}</span>
                  </td>
                  <td>{fmtMinutes(e.scheduled_minutes ?? 0)}</td>
                  <td>{fmtMinutes(e.worked_minutes ?? 0)}</td>
                  <td className={(e.variance_minutes ?? 0) < 0 ? "text-error" : undefined}>{fmtMinutes(e.variance_minutes ?? 0)}</td>
                  <td>{fmtMinutes(e.worked_night_minutes ?? 0)}</td>
                  <td>{fmtMinutes(e.night_premium_minutes ?? 0)}</td>
                  <td>{e.days_absent ?? 0}</td>
                  <td>
                    {e.days_short ?? 0} / {e.days_over ?? 0}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && view === "days" && <Pagination page={filters.page} pageSize={PAGE_SIZE} count={data.count} onPage={(page) => update({ page })} />}
    </section>
  );
}
