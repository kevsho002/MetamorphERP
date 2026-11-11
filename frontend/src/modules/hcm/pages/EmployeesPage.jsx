import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../../../auth/AuthContext.jsx";
import Pagination from "../../../components/ui/Pagination.jsx";
import { employeesApi } from "../api.js";
import StatusBadge from "../components/StatusBadge.jsx";
import { useCatalogs } from "../hooks/useCatalogs.js";
import { formatDate, formatMoney } from "../lib/format.js";

const PAGE_SIZE = 25;
const DEFAULT_FILTERS = { search: "", country: "", status: "ACTIVE", cost_center: "", ordering: "employee_code", page: 1 };
const STATUS_FILTERS = [
  { value: "", label: "Todos los estados" },
  { value: "ACTIVE", label: "Activos" },
  { value: "INACTIVE", label: "Inactivos (suspendidos y retirados)" },
  { value: "SUSPENDED", label: "Suspendidos" },
  { value: "TERMINATED", label: "Retirados" },
];
const SORTS = [
  { value: "employee_code", label: "ID corporativo" },
  { value: "name", label: "Apellido (A-Z)" },
  { value: "-name", label: "Apellido (Z-A)" },
  { value: "-hire_date", label: "Ingreso más reciente" },
  { value: "hire_date", label: "Ingreso más antiguo" },
  { value: "country", label: "País" },
  { value: "cost_center", label: "Centro de costos" },
];

/** Vista general de empleados: filtros por país, estado y centro de costos (en la URL). */
export default function EmployeesPage() {
  const { hasPermission } = useAuth();
  const canManage = hasPermission("hcm.manage");
  const canSeeSalary = hasPermission("payroll.view");
  const navigate = useNavigate();
  const catalogs = useCatalogs();
  const [params, setParams] = useSearchParams();
  const filters = useMemo(
    () => ({
      search: params.get("search") ?? DEFAULT_FILTERS.search,
      country: params.get("country") ?? DEFAULT_FILTERS.country,
      status: params.get("status") ?? DEFAULT_FILTERS.status, // "ALL" = todos los estados
      cost_center: params.get("cost_center") ?? DEFAULT_FILTERS.cost_center,
      ordering: params.get("ordering") ?? DEFAULT_FILTERS.ordering,
      page: Number(params.get("page") ?? 1) || 1,
    }),
    [params],
  );
  const [searchText, setSearchText] = useState(filters.search);
  const [state, setState] = useState({ loading: true, data: null, error: null });

  // Los filtros viven en la URL: se pueden compartir y sobreviven al botón «atrás».
  const update = (changes) => {
    const next = { ...filters, page: 1, ...changes };
    const query = {};
    Object.entries(next).forEach(([k, v]) => {
      if (v !== "" && v !== DEFAULT_FILTERS[k]) query[k] = String(v);
    });
    setParams(query, { replace: true });
  };

  // Búsqueda con espera breve para no consultar en cada tecla.
  useEffect(() => {
    if (searchText === filters.search) return undefined;
    const timer = setTimeout(() => update({ search: searchText.trim() }), 350);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchText]);

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    employeesApi
      .list(
        {
          search: filters.search,
          country: filters.country,
          status: filters.status === "ALL" ? "" : filters.status,
          cost_center: filters.cost_center,
          ordering: filters.ordering,
          page: filters.page,
          page_size: PAGE_SIZE,
        },
        { signal: controller.signal },
      )
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => {
        if (err.name === "AbortError") return;
        // Página fuera de rango (p. ej. tras filtrar): volver a la primera.
        if (err.status === 404 && filters.page > 1) update({ page: 1 });
        else setState({ loading: false, data: null, error: err.message });
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  const statusValue = filters.status === "ALL" ? "" : filters.status;
  const costCenters = catalogs.costCentersFor(filters.country, { includeInactive: true });
  const hasFilters = filters.search || filters.country || filters.cost_center || statusValue !== "ACTIVE";
  const rows = state.data?.results ?? [];

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Empleados</h1>
          <p className="muted page-subtitle">Consulta de colaboradores por país, estado y centro de costos.</p>
        </div>
        {canManage && (
          <div className="actions">
            <Link className="button button--ghost" to="/hcm/employees/import">
              Carga masiva
            </Link>
            <Link className="button" to="/hcm/employees/new">
              + Nuevo empleado
            </Link>
          </div>
        )}
      </header>

      <div className="filters" role="search">
        <label className="field filters__search">
          <span className="field__label">Buscar</span>
          <input
            type="search"
            placeholder="Nombre, ID corporativo, documento o correo"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
          />
        </label>
        <label className="field">
          <span className="field__label">País</span>
          <select value={filters.country} onChange={(e) => update({ country: e.target.value, cost_center: "" })}>
            <option value="">Todos los países</option>
            {catalogs.countries.map((c) => (
              <option key={c.code} value={c.code}>
                {c.code} — {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Estado</span>
          <select value={statusValue} onChange={(e) => update({ status: e.target.value || "ALL" })}>
            {STATUS_FILTERS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Centro de costos</span>
          <select value={filters.cost_center} onChange={(e) => update({ cost_center: e.target.value })}>
            <option value="">Todos</option>
            {costCenters.map((cc) => (
              <option key={cc.code} value={cc.code}>
                {cc.code} — {cc.name}
                {cc.is_active ? "" : " (inactivo)"}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Ordenar por</span>
          <select value={filters.ordering} onChange={(e) => update({ ordering: e.target.value })}>
            {SORTS.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        {hasFilters && (
          <button
            type="button"
            className="button button--ghost button--sm filters__clear"
            onClick={() => {
              setSearchText("");
              setParams({}, { replace: true });
            }}
          >
            Limpiar filtros
          </button>
        )}
      </div>

      {state.error && <p className="error-box">No se pudo cargar la lista: {state.error}</p>}

      <div className="table-wrap" aria-busy={state.loading}>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">ID corporativo</th>
              <th scope="col">Nombre</th>
              <th scope="col">País</th>
              <th scope="col">Centro de costos</th>
              <th scope="col">Documento</th>
              <th scope="col">Ingreso</th>
              <th scope="col">Estado</th>
              {canSeeSalary && (
                <th scope="col" className="num">
                  Salario base
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr
                key={e.employee_code}
                className="table__row--link"
                onClick={() => navigate(`/hcm/employees/${e.employee_code}`)}
              >
                <td>
                  <Link to={`/hcm/employees/${e.employee_code}`} onClick={(ev) => ev.stopPropagation()}>
                    <code>{e.employee_code}</code>
                  </Link>
                </td>
                <td>
                  <strong>{e.full_name}</strong>
                  {e.work_email && <div className="muted small">{e.work_email}</div>}
                </td>
                <td title={e.country_name}>{e.country}</td>
                <td title={e.cost_center_name ?? undefined}>{e.cost_center ?? <span className="muted">—</span>}</td>
                <td>
                  <span className="muted small">{e.national_id_type}</span> {e.national_id_number}
                </td>
                <td>{formatDate(e.hire_date)}</td>
                <td>
                  <StatusBadge value={e.employment_status} label={e.employment_status_label} />
                </td>
                {canSeeSalary && <td className="num">{formatMoney(e.base_salary, e.currency)}</td>}
              </tr>
            ))}
          </tbody>
        </table>
        {!state.loading && !state.error && rows.length === 0 && (
          <div className="empty">
            <p>{hasFilters ? "Ningún empleado coincide con los filtros." : "Aún no hay empleados registrados."}</p>
            {canManage && !hasFilters && (
              <p>
                <Link to="/hcm/employees/new">Registre el primero</Link> o use la{" "}
                <Link to="/hcm/employees/import">carga masiva</Link>.
              </p>
            )}
          </div>
        )}
        {state.loading && <p className="muted loading-row">Cargando…</p>}
      </div>

      {state.data && (
        <Pagination page={filters.page} pageSize={PAGE_SIZE} count={state.data.count} onPage={(page) => update({ page })} />
      )}
    </section>
  );
}
