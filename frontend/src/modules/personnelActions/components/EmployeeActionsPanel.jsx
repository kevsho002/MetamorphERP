import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { formatDate } from "../../hcm/lib/format.js";
import { actionsApi } from "../api.js";
import ActionStatusBadge from "./ActionStatusBadge.jsx";

/** Pestaña «Acciones de personal» del expediente: todas las AP del colaborador que su rol puede ver. */
export default function EmployeeActionsPanel({ employee }) {
  const code = employee.employee_code;
  const [state, setState] = useState({ loading: true, data: null, error: null });

  useEffect(() => {
    const controller = new AbortController();
    actionsApi
      .employee(code, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [code]);

  if (state.loading) return <p className="muted">Cargando acciones de personal…</p>;
  if (!state.data) return <p className="error-box">{state.error}</p>;
  const d = state.data;

  return (
    <section aria-labelledby="pa-title" className="roster">
      <header className="docs-header">
        <h2 id="pa-title" className="section-title">
          Acciones de personal
        </h2>
        {d.can_create && d.creatable_types.length > 0 && (
          <Link className="button button--sm" to={`/personnel-actions/new?employee=${code}`}>
            Nueva AP
          </Link>
        )}
      </header>
      <div className="table-wrap">
        <table className="table roster-table">
          <thead>
            <tr>
              <th scope="col">Folio</th>
              <th scope="col">Tipo</th>
              <th scope="col">Fecha efectiva</th>
              <th scope="col">Firmas</th>
              <th scope="col">Estado</th>
            </tr>
          </thead>
          <tbody>
            {d.results.map((a) => (
              <tr key={a.folio}>
                <th scope="row">
                  <Link to={`/personnel-actions/${a.folio}`}>
                    <code>{a.folio}</code>
                  </Link>
                </th>
                <td>
                  {a.action_type_name} {a.is_initial && <span className="badge badge--info">Fundacional</span>}
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
            {d.results.length === 0 && (
              <tr>
                <td colSpan={5} className="empty">
                  El colaborador no tiene acciones de personal visibles para su rol.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
