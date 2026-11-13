import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAuth } from "../../../auth/AuthContext.jsx";
import { useTimeFormat } from "../../../app/timeFormat.js";
import { adhApi } from "../../wfm/api.js";

const fmt = (iso) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)} ${iso.slice(11, 19)}` : "—");
const seconds = (x) => Math.max(0, (new Date(x.end) - new Date(x.start)) / 1000);

const NEW_TYPES = [
  { code: "AP_JUSTIFICACION_TIEMPO", label: "Justificación de tiempo" },
  { code: "AP_PERMISO_CON_GOCE", label: "Permiso con goce" },
  { code: "AP_PERMISO_SIN_GOCE", label: "Permiso sin goce" },
];

/**
 * Fase 22 — Justificaciones y permisos por AP, unificados en el módulo regular de Acciones de Personal. Se elaboran
 * como cualquier AP (Justificación de tiempo, Permiso con / sin goce); al APROBARSE, el sistema registra aquí la
 * ventana justificada (adherencia: no hay Out of Adherence, Unjustified Absence ni Lateness), coloca el segmento en la
 * grilla IEX y la planilla paga (o no) esas horas según la naturaleza del tipo. Este registro es de solo lectura.
 */
export default function JustificationsPage() {
  const time = useTimeFormat();
  const { hasPermission } = useAuth();
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => ({ employee: params.get("employee") ?? "", from: params.get("from") ?? "", to: params.get("to") ?? "" }), [params]);
  const [state, setState] = useState({ loading: true, data: null, error: null });

  useEffect(() => {
    const controller = new AbortController();
    adhApi
      .exceptions(filters, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [filters]);

  const update = (changes) => setParams(Object.fromEntries(Object.entries({ ...filters, ...changes }).filter(([, v]) => v)), { replace: true });
  const rows = state.data?.results ?? [];
  const totals = rows.reduce((t, x) => ({ ...t, [x.is_paid ? "paid" : "unpaid"]: t[x.is_paid ? "paid" : "unpaid"] + seconds(x) }), { paid: 0, unpaid: 0 });

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Justificaciones y permisos</h1>
          <p className="muted page-subtitle">
            Se elaboran como AP (justificación de tiempo, permiso con o sin goce). Al aprobarse justifican la ventana en la adherencia, colocan el segmento en la
            grilla y la planilla paga las horas según el tipo. Horas en hora local de la operación.
          </p>
        </div>
        {hasPermission("actions.create") && (
          <div className="pay-actions">
            {NEW_TYPES.map((t) => (
              <Link key={t.code} className="button button--ghost button--sm" to={`/personnel-actions/new?type=${t.code}${filters.employee ? `&employee=${filters.employee}` : ""}`}>
                + {t.label}
              </Link>
            ))}
          </div>
        )}
      </header>
      <div className="filters" role="search">
        <label className="field">
          <span className="field__label">Agente (ID)</span>
          <input type="search" defaultValue={filters.employee} onKeyDown={(e) => e.key === "Enter" && update({ employee: e.currentTarget.value.trim().toUpperCase() })} />
        </label>
        <label className="field">
          <span className="field__label">Desde</span>
          <input type="date" value={filters.from} onChange={(e) => update({ from: e.target.value })} />
        </label>
        <label className="field">
          <span className="field__label">Hasta</span>
          <input type="date" value={filters.to} onChange={(e) => update({ to: e.target.value })} />
        </label>
      </div>
      {state.error && <p className="error-box">{state.error}</p>}
      {state.data && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Agente</th>
                <th scope="col">Desde</th>
                <th scope="col">Hasta</th>
                <th scope="col" className="num">
                  Duración ({time.unit})
                </th>
                <th scope="col">AP</th>
                <th scope="col">Motivo</th>
                <th scope="col">Pago</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="empty">
                    Sin justificaciones en el rango.
                  </td>
                </tr>
              )}
              {rows.map((x) => (
                <tr key={x.id}>
                  <td>
                    {x.full_name}
                    <div className="muted small">{x.employee_code}</div>
                  </td>
                  <td className="pay-nowrap">{fmt(x.start)}</td>
                  <td className="pay-nowrap">{fmt(x.end)}</td>
                  <td className="num">{time.seconds(seconds(x))}</td>
                  <td>
                    <Link to={`/personnel-actions/${x.folio}`}>{x.folio}</Link>
                    <div className="muted small">{x.action_type}</div>
                  </td>
                  <td>{x.reason}</td>
                  <td>
                    <span className={`badge ${x.is_paid ? "badge--ok" : "badge--muted"}`}>{x.is_paid ? "Con goce" : "Sin goce"}</span>
                  </td>
                </tr>
              ))}
            </tbody>
            {rows.length > 0 && (
              <tfoot>
                <tr>
                  <th scope="row" colSpan={3}>
                    Total ({rows.length})
                  </th>
                  <td className="num">{time.seconds(totals.paid + totals.unpaid)}</td>
                  <td colSpan={3} className="small muted">
                    Con goce {time.seconds(totals.paid)} · sin goce {time.seconds(totals.unpaid)}
                  </td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}
    </section>
  );
}
