import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import Pagination from "../../../components/ui/Pagination.jsx";
import { employeesApi } from "../api.js";
import { Completeness } from "../components/DocumentsPanel.jsx";
import EmployeePhoto from "../components/EmployeePhoto.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import { useCatalogs } from "../hooks/useCatalogs.js";

const PAGE_SIZE = 25;
const STATUSES = [
  { value: "ACTIVE", label: "Activos" },
  { value: "INACTIVE", label: "Inactivos" },
  { value: "TERMINATED", label: "Terminados" },
  { value: "ALL", label: "Todos" },
];

/**
 * Expedientes digitales: avance de la documentación obligatoria (según la plantilla
 * vigente del país a la fecha de ingreso) y fotografía de cada empleado.
 */
export default function DigitalFilesPage() {
  const catalogs = useCatalogs();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const filters = useMemo(
    () => ({
      search: params.get("search") ?? "",
      country: params.get("country") ?? "",
      status: params.get("status") ?? "ACTIVE",
      page: Number(params.get("page") ?? 1) || 1,
    }),
    [params],
  );
  const [searchText, setSearchText] = useState(filters.search);
  const [state, setState] = useState({ loading: true, data: null, error: null });

  const update = (changes) => {
    const next = { ...filters, page: 1, ...changes };
    const query = {};
    if (next.search) query.search = next.search;
    if (next.country) query.country = next.country;
    if (next.status !== "ACTIVE") query.status = next.status;
    if (next.page > 1) query.page = String(next.page);
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
    setState((s) => ({ ...s, loading: true, error: null }));
    employeesApi
      .digitalFiles({ ...filters, page_size: PAGE_SIZE }, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => {
        if (err.name === "AbortError") return;
        if (err.status === 404 && filters.page > 1) update({ page: 1 });
        else setState({ loading: false, data: null, error: err.message });
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]);

  const rows = state.data?.results ?? [];
  const open = (code) => navigate(`/hcm/employees/${code}?tab=documents`);

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Expedientes digitales</h1>
          <p className="muted page-subtitle">
            Documentación obligatoria por país (según la plantilla vigente a la fecha de ingreso), vencimientos y fotografía.
          </p>
        </div>
      </header>

      <div className="filters" role="search">
        <label className="field filters__search">
          <span className="field__label">Buscar</span>
          <input
            type="search"
            placeholder="Nombre o ID corporativo"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
          />
        </label>
        <label className="field">
          <span className="field__label">País</span>
          <select value={filters.country} onChange={(e) => update({ country: e.target.value })}>
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
          <select value={filters.status} onChange={(e) => update({ status: e.target.value })}>
            {STATUSES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {state.error && <p className="error-box">No se pudo cargar la lista: {state.error}</p>}

      <div className="table-wrap" aria-busy={state.loading}>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Empleado</th>
              <th scope="col">País</th>
              <th scope="col">Estado</th>
              <th scope="col">Documentos obligatorios</th>
              <th scope="col">Pendientes / vencidos</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.employee_code} className="table__row--link" onClick={() => open(e.employee_code)}>
                <td>
                  <div className="person-cell">
                    <EmployeePhoto url={e.photo_url} name={e.full_name} size="sm" />
                    <div>
                      <strong>{e.full_name}</strong>
                      <br />
                      <Link to={`/hcm/employees/${e.employee_code}?tab=documents`} onClick={(ev) => ev.stopPropagation()}>
                        <code>{e.employee_code}</code>
                      </Link>
                    </div>
                  </div>
                </td>
                <td>{e.country}</td>
                <td>
                  <StatusBadge value={e.employment_status} label={e.employment_status_label} />
                </td>
                <td>
                  <Completeness
                    ok={e.documents.required_ok}
                    total={e.documents.required_total}
                    percent={e.documents.percent}
                    compact
                  />
                </td>
                <td className="small">
                  {e.documents.missing.length === 0 && e.documents.expired.length === 0 ? (
                    <span className="muted">Completo</span>
                  ) : (
                    <>
                      {e.documents.missing.length > 0 && <span>Falta: {e.documents.missing.join(", ")}</span>}
                      {e.documents.expired.length > 0 && (
                        <span className="text-danger">
                          {e.documents.missing.length > 0 && <br />}
                          Vencido: {e.documents.expired.join(", ")}
                        </span>
                      )}
                    </>
                  )}
                </td>
              </tr>
            ))}
            {!state.loading && rows.length === 0 && (
              <tr>
                <td colSpan={5} className="empty">
                  No hay empleados con estos filtros.
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
