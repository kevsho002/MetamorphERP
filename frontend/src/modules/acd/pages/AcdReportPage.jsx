import { formatSeconds, useTimeFormat } from "../../../app/timeFormat.js";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import Pagination from "../../../components/ui/Pagination.jsx";
import { todayIso } from "../../hcm/lib/format.js";
import { acdApi } from "../api.js";

const PAGE_SIZE = 100;

/**
 * Reporte de estados de agentes con el formato de exportación estándar de Genesys Cloud: Interval Start, Interval End,
 * Interval Complete, Employee Id, Employee Name, Division Id, Division Name, Start Time, End Time, Primary Status,
 * Secondary Status y Duration (milisegundos). Cada segmento se recorta a cada intervalo que toca.
 */
export default function AcdReportPage() {
  useTimeFormat(); // Fase 21: re-render al cambiar HH:MM:SS / horas decimales
  const [params, setParams] = useSearchParams();
  const today = todayIso();
  const filters = useMemo(
    () => ({
      from: params.get("from") ?? today,
      to: params.get("to") ?? params.get("from") ?? today,
      interval: params.get("interval") ?? "30",
      group: params.get("group") ?? "",
      division: params.get("division") ?? "",
      status: params.get("status") ?? "",
      employee: params.get("employee") ?? "",
      tz: params.get("tz") ?? "",
      page: Number(params.get("page") ?? 1) || 1,
    }),
    [params, today],
  );
  const [catalogs, setCatalogs] = useState(null);
  const [state, setState] = useState({ loading: true, data: null, error: null });

  useEffect(() => {
    const controller = new AbortController();
    acdApi.catalogs({ signal: controller.signal }).then(setCatalogs).catch(() => {});
    return () => controller.abort();
  }, []);

  const query = useMemo(() => ({ ...filters, page_size: PAGE_SIZE }), [filters]);

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    acdApi
      .report(query, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [query]);

  const update = (changes) => {
    const next = { ...filters, page: 1, ...changes };
    setParams(Object.fromEntries(Object.entries(next).filter(([k, v]) => v !== "" && !(k === "page" && v === 1)).map(([k, v]) => [k, String(v)])), {
      replace: true,
    });
  };

  const data = state.data;
  const columns = data?.columns ?? catalogs?.report_columns ?? [];

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Reporte de estados de agentes</h1>
          <p className="muted page-subtitle">
            Formato de exportación de Genesys Cloud (Agent Status Detail). Duration en milisegundos; horas ISO-8601 con la zona {data?.tz ?? "de la operación"}.
            Fuente en SQL: <code>dbo.vw_AcdStatusSegment</code>.
          </p>
        </div>
        <a className="button button--ghost" href={acdApi.reportCsvUrl(query)} download>
          Exportar CSV
        </a>
      </header>
      <div className="filters" role="search">
        <label className="field">
          <span className="field__label">Desde</span>
          <input type="date" value={filters.from} onChange={(e) => e.target.value && update({ from: e.target.value, to: filters.to < e.target.value ? e.target.value : filters.to })} />
        </label>
        <label className="field">
          <span className="field__label">Hasta</span>
          <input type="date" value={filters.to} min={filters.from} onChange={(e) => e.target.value && update({ to: e.target.value })} />
        </label>
        <label className="field">
          <span className="field__label">Intervalo</span>
          <select value={filters.interval} onChange={(e) => update({ interval: e.target.value })}>
            {(catalogs?.intervals ?? [{ value: "30", label: "30 minutos" }]).map((i) => (
              <option key={i.value} value={i.value}>
                {i.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Grupo</span>
          <select value={filters.group} onChange={(e) => update({ group: e.target.value })}>
            <option value="">Todos</option>
            {(catalogs?.groups ?? []).map((g) => (
              <option key={g.code} value={g.code}>
                {g.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">División</span>
          <select value={filters.division} onChange={(e) => update({ division: e.target.value })}>
            <option value="">Todas</option>
            {(catalogs?.divisions ?? []).map((d) => (
              <option key={d.code} value={d.code}>
                {d.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Primary Status</span>
          <select value={filters.status} onChange={(e) => update({ status: e.target.value })}>
            <option value="">Todos</option>
            {(catalogs?.primary_statuses ?? []).map((s) => (
              <option key={s.code} value={s.code}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Employee Id</span>
          <input type="search" defaultValue={filters.employee} placeholder="SV-2026-000001-7" onKeyDown={(e) => e.key === "Enter" && update({ employee: e.currentTarget.value.trim() })} />
        </label>
      </div>
      {state.error && <p className="error-box">{state.error}</p>}
      {data && data.summary.length > 0 && (
        <details className="form-section">
          <summary>Resumen por agente ({data.summary.length})</summary>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Agente</th>
                  <th scope="col">Total</th>
                  <th scope="col">Por estado</th>
                </tr>
              </thead>
              <tbody>
                {data.summary.map((s) => (
                  <tr key={s.employee_code}>
                    <th scope="row">
                      {s.full_name} <code className="small">{s.employee_code}</code>
                    </th>
                    <td>{formatSeconds((s.total_ms ?? 0) / 1000)}</td>
                    <td className="small">
                      {Object.entries(s.by_status_ms)
                        .map(([k, v]) => `${k} ${formatSeconds((v ?? 0) / 1000)}`)
                        .join(" · ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
      <div className="table-wrap" aria-busy={state.loading}>
        <table className="table table--compact acd-report">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c} scope="col">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(data?.results ?? []).map((r, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c}>{String(r[c])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data?.count === 0 && <p className="empty">Sin segmentos de estado en el rango.</p>}
      {data && data.count > PAGE_SIZE && (
        <Pagination page={filters.page} pageSize={PAGE_SIZE} count={data.count} onPage={(page) => update({ page })} />
      )}
    </section>
  );
}
