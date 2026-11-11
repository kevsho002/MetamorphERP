import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Pagination from "../../../components/ui/Pagination.jsx";
import StatusBadge from "../../hcm/components/StatusBadge.jsx";
import { useCatalogs } from "../../hcm/hooks/useCatalogs.js";
import { formatDate, todayIso } from "../../hcm/lib/format.js";
import { generalIdsApi } from "../api.js";
import { useGeneralIdCatalogs } from "../hooks/useGeneralIdCatalogs.js";

const PAGE_SIZE = 50;

/** «¿A quién pertenece este ID en esta fecha?» — la misma resolución que hace un JOIN de reportería. */
function Lookup({ types }) {
  const [form, setForm] = useState({ type: "", value: "", date: todayIso() });
  const [state, setState] = useState({ busy: false, data: null, error: null });

  const submit = async (e) => {
    e.preventDefault();
    setState({ busy: true, data: null, error: null });
    try {
      setState({ busy: false, data: await generalIdsApi.lookup(form), error: null });
    } catch (err) {
      setState({ busy: false, data: null, error: err.message });
    }
  };

  return (
    <form className="form-section" onSubmit={submit} role="search" aria-label="Buscar a quién pertenece un ID">
      <h2 className="section-title">¿A quién pertenece un ID?</h2>
      <div className="filters">
        <label className="field">
          <span className="field__label">Tipo de ID</span>
          <select value={form.type} onChange={(e) => setForm((f) => ({ ...f, type: e.target.value }))} required>
            <option value="">— Seleccione —</option>
            {types.map((t) => (
              <option key={t.code} value={t.code}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Valor</span>
          <input value={form.value} onChange={(e) => setForm((f) => ({ ...f, value: e.target.value }))} required autoComplete="off" />
        </label>
        <label className="field">
          <span className="field__label">En la fecha</span>
          <input type="date" value={form.date} onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))} required />
        </label>
        <button type="submit" className="button" disabled={state.busy || !form.type || !form.value.trim()}>
          {state.busy ? "Buscando…" : "Buscar"}
        </button>
      </div>
      {state.error && <p className="error-box">{state.error}</p>}
      {state.data &&
        (state.data.matches.length ? (
          <ul className="lookup-results">
            {state.data.matches.map((m) => (
              <li key={m.id}>
                <Link to={`/hcm/employees/${m.employee_code}?tab=general_ids`}>
                  <code>{m.employee_code}</code>
                </Link>{" "}
                <strong>{m.full_name}</strong> · {m.country}
                {m.client_name && ` · ${m.client_name}${m.brand_name ? ` › ${m.brand_name}` : ""}`}
                <span className="muted small">
                  {" "}
                  ({formatDate(m.effective_start)} → {m.is_now ? "Now" : formatDate(m.effective_end)})
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted">
            Nadie tiene el {state.data.type} «{state.data.value}» vigente al {formatDate(state.data.date)}
            {state.data.history.length > 0 && ` (estuvo asignado en ${state.data.history.length} período(s) distinto(s))`}.
          </p>
        ))}
    </form>
  );
}

/** Consulta de General IDs vigentes en un rango, con filtros y exportación CSV (llaves para cruces de reportes). */
export default function GeneralIdsReportPage() {
  const config = useGeneralIdCatalogs();
  const catalogs = useCatalogs();
  const [params, setParams] = useSearchParams();
  const today = todayIso();
  const filters = useMemo(
    () => ({
      from: params.get("from") ?? today,
      to: params.get("to") ?? params.get("from") ?? today,
      type: params.get("type") ?? "",
      tool: params.get("tool") ?? "",
      client: params.get("client") ?? "",
      brand: params.get("brand") ?? "",
      country: params.get("country") ?? "",
      search: params.get("search") ?? "",
      page: Number(params.get("page") ?? 1) || 1,
    }),
    [params, today],
  );
  const [searchText, setSearchText] = useState(filters.search);
  const [state, setState] = useState({ loading: true, data: null, error: null });

  const update = (changes) => {
    const next = { ...filters, page: 1, ...changes };
    const query = {};
    Object.entries(next).forEach(([k, v]) => {
      if (v && !(k === "page" && v === 1)) query[k] = String(v);
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
    generalIdsApi
      .report(query, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [query]);

  const client = config.clients.find((c) => c.code === filters.client);
  const rows = state.data?.results ?? [];

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">General IDs</h1>
          <p className="muted page-subtitle">
            Identificadores de los empleados en herramientas externas (ACD, planilla…) vigentes en un rango: las llaves
            para cruzar reportes. En SQL: <code>dbo.vw_EmployeeGeneralId</code>.
          </p>
        </div>
        <a className="button button--ghost" href={generalIdsApi.reportCsvUrl(query)} download>
          Exportar CSV
        </a>
      </header>

      <Lookup types={config.types} />

      <div className="filters" role="search">
        <label className="field">
          <span className="field__label">Desde</span>
          <input
            type="date"
            value={filters.from}
            onChange={(e) => e.target.value && update({ from: e.target.value, to: filters.to < e.target.value ? e.target.value : filters.to })}
          />
        </label>
        <label className="field">
          <span className="field__label">Hasta</span>
          <input type="date" value={filters.to} min={filters.from} onChange={(e) => e.target.value && update({ to: e.target.value })} />
        </label>
        <label className="field">
          <span className="field__label">Herramienta</span>
          <select value={filters.tool} onChange={(e) => update({ tool: e.target.value })}>
            <option value="">Todas</option>
            {config.tools.map((t) => (
              <option key={t.code} value={t.code}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Tipo de ID</span>
          <select value={filters.type} onChange={(e) => update({ type: e.target.value })}>
            <option value="">Todos</option>
            {config.types
              .filter((t) => !filters.tool || t.tool === filters.tool)
              .map((t) => (
                <option key={t.code} value={t.code}>
                  {t.name}
                </option>
              ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Cliente</span>
          <select value={filters.client} onChange={(e) => update({ client: e.target.value, brand: "" })}>
            <option value="">Todos</option>
            {config.clients.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        {client && (
          <label className="field">
            <span className="field__label">Marca</span>
            <select value={filters.brand} onChange={(e) => update({ brand: e.target.value })}>
              <option value="">Todas</option>
              {client.brands.map((b) => (
                <option key={b.code} value={b.code}>
                  {b.name}
                </option>
              ))}
            </select>
          </label>
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
        <label className="field filters__search">
          <span className="field__label">Buscar</span>
          <input type="search" placeholder="Valor, nombre o ID corporativo" value={searchText} onChange={(e) => setSearchText(e.target.value)} />
        </label>
      </div>

      {(state.error || config.error) && <p className="error-box">No se pudo cargar la consulta: {state.error || config.error}</p>}

      <div className="table-wrap" aria-busy={state.loading}>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Empleado</th>
              <th scope="col">Estado</th>
              <th scope="col">Tipo · herramienta</th>
              <th scope="col">Valor</th>
              <th scope="col">Cliente / marca</th>
              <th scope="col">Vigencia</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>
                  <strong>{r.full_name}</strong>
                  <br />
                  <Link to={`/hcm/employees/${r.employee_code}?tab=general_ids`}>
                    <code>{r.employee_code}</code>
                  </Link>{" "}
                  <span className="muted small">{r.country}</span>
                </td>
                <td>
                  <StatusBadge value={r.employment_status} />
                </td>
                <td>
                  {r.id_type_name}
                  <br />
                  <span className="muted small">{r.tool_name}</span>
                </td>
                <td>
                  <code>{r.value}</code>
                </td>
                <td>{r.client_name ? `${r.client_name}${r.brand_name ? ` › ${r.brand_name}` : ""}` : <span className="muted">—</span>}</td>
                <td>
                  {formatDate(r.effective_start)} → {r.is_now ? <strong>Now</strong> : formatDate(r.effective_end)}
                </td>
              </tr>
            ))}
            {!state.loading && rows.length === 0 && (
              <tr>
                <td colSpan={6} className="empty">
                  No hay General IDs vigentes con estos filtros entre el {formatDate(filters.from)} y el {formatDate(filters.to)}.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {state.data && <Pagination page={filters.page} pageSize={PAGE_SIZE} count={state.data.count} onPage={(page) => update({ page })} />}
    </section>
  );
}
