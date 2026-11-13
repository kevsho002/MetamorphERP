import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { formatDate } from "../../hcm/lib/format.js";
import { actionsApi } from "../api.js";
import RehireAlert from "./RehireAlert.jsx";

const STATUS_CLASS = { ACTIVE: "badge--ok", INACTIVE: "badge--warn", TERMINATED: "badge--error" };

/**
 * Fase 21 — Pestaña «Ciclo de vida» del expediente: estado, antigüedad vigente (congelada por suspensiones, reiniciada
 * por un reingreso) e historial laboral. El indicador interno de recomendación de recontratación solo lo ve RRHH.
 */
export default function LifecyclePanel({ employee }) {
  const code = employee.employee_code;
  const [state, setState] = useState({ loading: true, data: null, error: null });

  useEffect(() => {
    const controller = new AbortController();
    actionsApi
      .lifecycle(code, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [code]);

  if (state.loading) return <p className="muted">Cargando ciclo de vida…</p>;
  if (!state.data) return <p className="error-box">{state.error}</p>;
  const d = state.data;
  const t = d.tenure;
  return (
    <section aria-labelledby="lifecycle-title" className="lifecycle">
      <header className="docs-header">
        <h2 id="lifecycle-title" className="section-title">
          Ciclo de vida
        </h2>
        <Link className="button button--sm button--ghost" to={`/personnel-actions/new?employee=${code}`}>
          Nueva AP
        </Link>
      </header>
      <dl className="kpis">
        <div className="kpi">
          <dt>Estado</dt>
          <dd>
            <span className={`badge ${STATUS_CLASS[d.status] ?? ""}`}>{d.status_label}</span>
          </dd>
        </div>
        <div className="kpi">
          <dt>Ingreso vigente</dt>
          <dd>{formatDate(d.hire_date)}</dd>
        </div>
        {d.termination_date && (
          <div className="kpi">
            <dt>Terminación</dt>
            <dd>{formatDate(d.termination_date)}</dd>
          </div>
        )}
        <div className="kpi">
          <dt>Antigüedad (tenure)</dt>
          <dd>
            {t.label}
            {t.frozen && <span className="badge badge--warn lifecycle__frozen">Congelada</span>}
          </dd>
        </div>
        <div className="kpi">
          <dt>Días computables</dt>
          <dd>
            {t.days} <span className="muted small">de {t.calendar_days} ({t.suspended_days} suspendidos)</span>
          </dd>
        </div>
        {d.is_hr && (
          <div className="kpi">
            <dt>Recontratación (interno RRHH)</dt>
            <dd>
              {d.rehire_eligible === null || d.rehire_eligible === undefined ? (
                <span className="muted">Sin terminaciones</span>
              ) : d.rehire_eligible ? (
                <span className="badge badge--ok">Recomendable</span>
              ) : (
                <span className="badge badge--error">No recomendable</span>
              )}
            </dd>
          </div>
        )}
      </dl>
      {d.active_suspension && (
        <p className="alert alert--warn">
          Suspensión disciplinaria vigente del {formatDate(d.active_suspension.start_date)} al {formatDate(d.active_suspension.end_date)}
          {d.active_suspension.folio ? ` (AP ${d.active_suspension.folio})` : ""}: el colaborador está inactivo, no se le pagan esas horas y su
          antigüedad no corre. Vuelve a Activo automáticamente al terminar.
        </p>
      )}
      {d.is_hr && d.rehire_alert && d.status === "TERMINATED" && (
        <RehireAlert alert={d.rehire_alert} acknowledged={false} onAcknowledge={() => {}} readOnly />
      )}
      <div className="table-wrap">
        <table className="table table--compact">
          <caption className="muted small">Historial laboral (ingresos, suspensiones, terminaciones y reingresos)</caption>
          <thead>
            <tr>
              <th scope="col">Evento</th>
              <th scope="col">Desde</th>
              <th scope="col">Hasta</th>
              <th scope="col">AP</th>
              <th scope="col">Detalle</th>
            </tr>
          </thead>
          <tbody>
            {d.history.length === 0 && (
              <tr>
                <td colSpan={5} className="muted">
                  Sin eventos registrados desde la Fase 21 (ingreso original: {formatDate(d.hire_date)}).
                </td>
              </tr>
            )}
            {d.history.map((h) => (
              <tr key={h.id}>
                <td>{h.kind_label}</td>
                <td>{formatDate(h.start_date)}</td>
                <td>{h.end_date ? formatDate(h.end_date) : "—"}</td>
                <td>{h.folio ? <Link to={`/personnel-actions/${h.folio}`}>{h.folio}</Link> : "—"}</td>
                <td>
                  {h.kind === "SUSPENSION" && `${h.days} día(s)${h.reactivated_at ? " · reactivado" : ""}`}
                  {h.kind === "TERMINATION" &&
                    `${h.termination_reason_label}${d.is_hr ? ` · ${h.rehire_eligible ? "recomendable" : "NO recomendable"}` : ""}`}
                  {h.kind === "REHIRE" &&
                    `Ingreso anterior ${formatDate(h.previous_hire_date)} · terminación ${formatDate(h.previous_termination_date)}${
                      d.is_hr && h.rehire_acknowledged ? " · alerta reconocida" : ""
                    }`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
