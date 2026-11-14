import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAuth } from "../../../auth/AuthContext.jsx";
import Pagination from "../../../components/ui/Pagination.jsx";
import { formatDate } from "../../hcm/lib/format.js";
import { actionsApi } from "../api.js";
import ActionStatusBadge from "../components/ActionStatusBadge.jsx";

const PAGE_SIZE = 25;
const STATUSES = [
  ["DRAFT", "Borrador"],
  ["PENDING", "En aprobación"],
  ["APPROVED", "Aprobada"],
  ["REJECTED", "Rechazada"],
  ["CANCELLED", "Anulada"],
];

/** Bandeja de Acciones de Personal: filtros, «pendientes de mi firma» y empleados sin Primera AP de horario. */
export default function ActionsPage() {
  const { hasPermission } = useAuth();
  const [params, setParams] = useSearchParams();
  const filters = useMemo(
    () => ({
      status: params.get("status") ?? "",
      type: params.get("type") ?? "",
      search: params.get("search") ?? "",
      pending_for_me: params.get("pending_for_me") ?? "",
      page: Number(params.get("page") ?? 1) || 1,
    }),
    [params],
  );
  const [searchText, setSearchText] = useState(filters.search);
  const [types, setTypes] = useState([]);
  const [missing, setMissing] = useState(null);
  const [state, setState] = useState({ loading: true, data: null, error: null });

  const update = (changes) => {
    const next = { ...filters, page: 1, ...changes };
    setParams(Object.fromEntries(Object.entries(next).filter(([k, v]) => v && !(k === "page" && v === 1)).map(([k, v]) => [k, String(v)])), { replace: true });
  };

  useEffect(() => {
    if (searchText === filters.search) return undefined;
    const timer = setTimeout(() => update({ search: searchText.trim() }), 350);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchText]);

  useEffect(() => {
    const controller = new AbortController();
    actionsApi.types({ signal: controller.signal }).then((d) => setTypes(d.results)).catch(() => {});
    actionsApi.missingInitial({ signal: controller.signal }).then(setMissing).catch(() => {});
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    actionsApi
      .list({ ...filters, page_size: PAGE_SIZE }, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [filters]);

  const rows = state.data?.results ?? [];

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Acciones de personal</h1>
          <p className="muted page-subtitle">
            Cambios de horario, ajustes salariales y otros eventos con folio, fecha efectiva y firmas por rol. Los tipos y sus
            campos se parametrizan en /admin/.
          </p>
        </div>
        {hasPermission("actions.create") && (
          <Link className="button" to="/personnel-actions/new">
            Nueva AP
          </Link>
        )}
      </header>

      {missing?.count > 0 && (
        <div className="alert alert--warn" role="status">
          <p className="alert__title">
            {missing.count} colaborador(es) activo(s) sin Primera AP de asignación de horario
          </p>
          <ul className="msg-list">
            {missing.results.slice(0, 10).map((e) => (
              <li key={e.employee_code}>
                <code>{e.employee_code}</code> {e.full_name} (ingreso {formatDate(e.hire_date)}) —{" "}
                <Link to={`/personnel-actions/new?type=AP_HORARIO_INICIAL&employee=${e.employee_code}`}>elaborar su Primera AP</Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="filters" role="search">
        <label className="checkbox">
          <input type="checkbox" checked={filters.pending_for_me === "1"} onChange={(e) => update({ pending_for_me: e.target.checked ? "1" : "" })} />
          <span>
            Pendientes de mi firma{state.data ? ` (${state.data.pending_for_me})` : ""}
          </span>
        </label>
        <label className="field">
          <span className="field__label">Estado</span>
          <select value={filters.status} onChange={(e) => update({ status: e.target.value })}>
            <option value="">Todos</option>
            {STATUSES.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Tipo</span>
          <select value={filters.type} onChange={(e) => update({ type: e.target.value })}>
            <option value="">Todos</option>
            {types.map((t) => (
              <option key={t.code} value={t.code}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field filters__search">
          <span className="field__label">Buscar</span>
          <input type="search" placeholder="Folio, ID corporativo, nombre o justificación" value={searchText} onChange={(e) => setSearchText(e.target.value)} />
        </label>
      </div>
      {state.error && <p className="error-box">{state.error}</p>}
      <div className="table-wrap" aria-busy={state.loading}>
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Folio</th>
              <th scope="col">Tipo</th>
              <th scope="col">Empleado</th>
              <th scope="col">Fecha efectiva</th>
              <th scope="col">Firmas</th>
              <th scope="col">Estado</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.folio}>
                <td>
                  <Link to={`/personnel-actions/${a.folio}`}>
                    <code>{a.folio}</code>
                  </Link>
                  {a.attachments_count > 0 && (
                    <Link to={`/personnel-actions/${a.folio}?tab=evidence`} className="badge badge--muted" title="Evidencias adjuntas (Fase 24)">
                      {a.attachments_count} adj.
                    </Link>
                  )}
                </td>
                <td>
                  {a.action_type_name}
                  {a.is_initial && <span className="badge badge--info">Fundacional</span>}
                </td>
                <td>
                  {a.full_name}
                  <br />
                  <code className="small">{a.employee_code}</code>
                </td>
                <td>{formatDate(a.effective_date)}</td>
                <td className="small">
                  {a.steps_signed}/{a.steps_total}
                  {a.next_step && <span className="muted"> · sigue {a.next_step.role_label}</span>}
                </td>
                <td>
                  <ActionStatusBadge status={a.status} label={a.status_label} />
                </td>
              </tr>
            ))}
            {!state.loading && rows.length === 0 && (
              <tr>
                <td colSpan={6} className="empty">
                  No hay acciones de personal con estos filtros.
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
