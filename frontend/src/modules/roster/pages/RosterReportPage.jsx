import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Pagination from "../../../components/ui/Pagination.jsx";
import StatusBadge from "../../hcm/components/StatusBadge.jsx";
import { useCatalogs } from "../../hcm/hooks/useCatalogs.js";
import { formatDate, todayIso } from "../../hcm/lib/format.js";
import { CHAIN_LEVELS, leadersApi, rosterApi } from "../api.js";
import { useRosterConfig } from "../hooks/useRosterConfig.js";

const PAGE_SIZE = 50;
const STATUSES = [
  { value: "ALL", label: "Todos" },
  { value: "ACTIVE", label: "Activos" },
  { value: "INACTIVE", label: "Inactivos" },
  { value: "TERMINATED", label: "Terminados" },
];

function Cell({ intervals }) {
  if (!intervals?.length) return <span className="muted">—</span>;
  return (
    <ul className="roster-cell">
      {intervals.map((i) => (
        <li key={`${i.value}-${i.effective_start}`}>
          <strong>{i.label}</strong>
          <span className="muted small">
            {" "}
            {formatDate(i.effective_start)} → {i.is_now ? "Now" : formatDate(i.effective_end)}
          </span>
        </li>
      ))}
    </ul>
  );
}

/**
 * Consulta cruzada ficha + roster: empleados vigentes en un rango de fechas y sus asignaciones
 * (cliente, marca, línea, wave, fechas clave...) que se cruzan con ese rango. Exportable a CSV.
 */
export default function RosterReportPage() {
  const config = useRosterConfig();
  const catalogs = useCatalogs();
  const [params, setParams] = useSearchParams();
  const today = todayIso();
  const filters = useMemo(
    () => ({
      from: params.get("from") ?? today,
      to: params.get("to") ?? params.get("from") ?? today,
      country: params.get("country") ?? "",
      status: params.get("status") ?? "ALL",
      attribute: params.get("attribute") ?? "",
      value: params.get("value") ?? "",
      search: params.get("search") ?? "",
      assigned: params.get("assigned") ?? "",
      director: params.get("director") ?? "",
      manager: params.get("manager") ?? "",
      supervisor: params.get("supervisor") ?? "",
      team_manager: params.get("team_manager") ?? "",
      page: Number(params.get("page") ?? 1) || 1,
    }),
    [params, today],
  );
  const [searchText, setSearchText] = useState(filters.search);
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [leaders, setLeaders] = useState([]);

  useEffect(() => {
    const controller = new AbortController();
    leadersApi
      .list({}, { signal: controller.signal })
      .then((d) => setLeaders(d.results))
      .catch(() => setLeaders([]));
    return () => controller.abort();
  }, []);

  // Cadena de mando encadenada (Fase 18): cada nivel solo ofrece los líderes bajo el nivel superior elegido.
  const chainOptions = useMemo(() => {
    const out = {};
    let parents = null;
    CHAIN_LEVELS.forEach(([param, level]) => {
      const list = leaders.filter((l) => l.level === level && (parents === null || parents.has(l.reports_to_id)));
      out[param] = list;
      const chosen = list.find((l) => l.employee_code === filters[param]);
      parents = chosen ? new Set([chosen.id]) : parents === null ? null : new Set(list.map((l) => l.id));
    });
    return out;
  }, [leaders, filters]);
  const setLevel = (param, value) => {
    const idx = CHAIN_LEVELS.findIndex(([p]) => p === param);
    const changes = { [param]: value };
    CHAIN_LEVELS.slice(idx + 1).forEach(([p]) => { changes[p] = ""; });
    update(changes);
  };

  const update = (changes) => {
    const next = { ...filters, page: 1, ...changes };
    const query = {};
    Object.entries(next).forEach(([k, v]) => {
      if (v && !(k === "page" && v === 1) && !(k === "status" && v === "ALL")) query[k] = String(v);
    });
    setParams(query, { replace: true });
  };

  useEffect(() => {
    if (searchText === filters.search) return undefined;
    const timer = setTimeout(() => update({ search: searchText.trim() }), 350);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchText]);

  const query = useMemo(() => ({ ...filters, page_size: PAGE_SIZE }), [filters]);

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    rosterApi
      .report(query, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [query]);

  const dimensionAttrs = config.attributes.filter((a) => a.data_type === "DIMENSION");
  const filterAttr = config.byCode[filters.attribute];
  const valueOptions = filterAttr ? config.dimensions[filterAttr.dimension]?.items ?? [] : [];
  const columns = state.data?.attributes ?? config.attributes;
  const rows = state.data?.results ?? [];

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Consulta de roster</h1>
          <p className="muted page-subtitle">
            Ficha del empleado y asignaciones de roster vigentes en un rango de fechas (WFM, RRHH y QA).
          </p>
        </div>
        <a className="button button--ghost" href={rosterApi.reportCsvUrl(query)} download>
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
          <span className="field__label">Estado</span>
          <select value={filters.status} onChange={(e) => update({ status: e.target.value })}>
            {STATUSES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Filtrar por</span>
          <select value={filters.attribute} onChange={(e) => update({ attribute: e.target.value, value: "" })}>
            <option value="">— Ninguno —</option>
            {dimensionAttrs.map((a) => (
              <option key={a.code} value={a.code}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        {filterAttr && (
          <label className="field">
            <span className="field__label">{filterAttr.name}</span>
            <select value={filters.value} onChange={(e) => update({ value: e.target.value })}>
              <option value="">Con cualquier valor</option>
              {valueOptions.map((o) => (
                <option key={o.code} value={o.code}>
                  {o.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="field filters__search">
          <span className="field__label">Buscar</span>
          <input type="search" placeholder="Nombre o ID corporativo" value={searchText} onChange={(e) => setSearchText(e.target.value)} />
        </label>
        {leaders.length > 0 &&
          CHAIN_LEVELS.map(([param, , label]) => (
            <label key={param} className="field">
              <span className="field__label">{label}</span>
              <select value={filters[param]} onChange={(e) => setLevel(param, e.target.value)} disabled={chainOptions[param].length === 0 && !filters[param]}>
                <option value="">Todos</option>
                {chainOptions[param].map((l) => (
                  <option key={l.id} value={l.employee_code}>
                    {l.full_name}
                  </option>
                ))}
              </select>
            </label>
          ))}
        <label className="checkbox roster-filter-check">
          <input type="checkbox" checked={filters.assigned === "1"} onChange={(e) => update({ assigned: e.target.checked ? "1" : "" })} />
          <span>Solo con asignaciones en el rango</span>
        </label>
      </div>

      {(state.error || config.error) && <p className="error-box">No se pudo cargar la consulta: {state.error || config.error}</p>}

      <div className="table-wrap" aria-busy={state.loading}>
        <table className="table roster-report">
          <thead>
            <tr>
              <th scope="col">Empleado</th>
              <th scope="col">País</th>
              <th scope="col">Estado</th>
              <th scope="col">Cadena de mando al {formatDate(filters.to)}</th>
              {columns.map((a) => (
                <th key={a.code} scope="col">
                  {a.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ employee: e, assignments, chain_of_command: chain }) => (
              <tr key={e.employee_code}>
                <td>
                  <strong>{e.full_name}</strong>
                  <br />
                  <Link to={`/hcm/employees/${e.employee_code}?tab=roster`}>
                    <code>{e.employee_code}</code>
                  </Link>
                </td>
                <td>{e.country}</td>
                <td>
                  <StatusBadge value={e.employment_status} label={e.employment_status_label} />
                </td>
                <td>
                  {chain ? (
                    <ul className="roster-cell">
                      {CHAIN_LEVELS.slice().reverse().map(([, level, label]) =>
                        chain[level] ? (
                          <li key={level}>
                            <span className="muted small">{label}: </span>
                            <strong>{chain[level].full_name}</strong>
                          </li>
                        ) : null,
                      )}
                    </ul>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                {columns.map((a) => (
                  <td key={a.code}>
                    <Cell intervals={assignments[a.code]} />
                  </td>
                ))}
              </tr>
            ))}
            {!state.loading && rows.length === 0 && (
              <tr>
                <td colSpan={4 + columns.length} className="empty">
                  No hay empleados vigentes con estos filtros entre el {formatDate(filters.from)} y el {formatDate(filters.to)}.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {state.data && (
        <Pagination page={filters.page} pageSize={PAGE_SIZE} count={state.data.count} onPage={(page) => update({ page })} />
      )}
    </section>
  );
}
