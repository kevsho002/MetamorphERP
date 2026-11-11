import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import Pagination from "../../../components/ui/Pagination.jsx";
import { employeesApi } from "../api.js";
import StatusBadge from "../components/StatusBadge.jsx";
import { formatDateTime } from "../lib/format.js";

const PAGE_SIZE = 25; // paginación por defecto de la API

/** Historial de cargas masivas (más recientes primero). */
export default function ImportHistoryPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const page = Number(params.get("page") ?? 1) || 1;
  const [state, setState] = useState({ loading: true, data: null, error: null });

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true }));
    employeesApi
      .imports({ page }, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [page]);

  const rows = state.data?.results ?? [];

  return (
    <section className="card card--wide">
      <nav className="breadcrumb" aria-label="Ruta">
        <Link to="/hcm/employees">Empleados</Link>
        <span aria-hidden="true">/</span>
        <span>Historial de cargas</span>
      </nav>
      <header className="card__header">
        <div>
          <h1 className="page-title">Historial de cargas masivas</h1>
          <p className="muted page-subtitle">Cada carga conserva su reporte fila por fila.</p>
        </div>
        <Link className="button" to="/hcm/employees/import">
          Nueva carga
        </Link>
      </header>
      {state.error && <p className="error-box">{state.error}</p>}
      <div className="table-wrap" aria-busy={state.loading}>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Lote</th>
              <th scope="col">Archivo</th>
              <th scope="col">Fecha</th>
              <th scope="col">Usuario</th>
              <th scope="col">Estado</th>
              <th scope="col" className="num">
                Filas
              </th>
              <th scope="col" className="num">
                Creados
              </th>
              <th scope="col" className="num">
                Errores
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((b) => (
              <tr key={b.id} className="table__row--link" onClick={() => navigate(`/hcm/employees/imports/${b.id}`)}>
                <td>
                  <Link to={`/hcm/employees/imports/${b.id}`} onClick={(e) => e.stopPropagation()}>
                    #{b.id}
                  </Link>
                </td>
                <td>
                  {b.file_name}
                  <div className="muted small">
                    {b.source_format} · {b.atomicity === "COUNTRY" ? "Todo o nada por país" : "Fila por fila"}
                  </div>
                </td>
                <td>{formatDateTime(b.finished_at)}</td>
                <td>{b.created_by ?? "—"}</td>
                <td>
                  <StatusBadge type="batch" value={b.status} />
                </td>
                <td className="num">{b.total_rows}</td>
                <td className="num">{b.created_rows}</td>
                <td className="num">{b.error_rows}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!state.loading && rows.length === 0 && !state.error && (
          <div className="empty">
            <p>Aún no se han realizado cargas masivas.</p>
          </div>
        )}
      </div>
      {state.data && (
        <Pagination
          page={page}
          pageSize={PAGE_SIZE}
          count={state.data.count}
          onPage={(p) => setParams(p > 1 ? { page: String(p) } : {}, { replace: true })}
        />
      )}
    </section>
  );
}
