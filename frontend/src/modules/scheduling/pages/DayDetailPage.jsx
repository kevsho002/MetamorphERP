import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { formatDate } from "../../hcm/lib/format.js";
import { schedulingApi } from "../api.js";
import { FLAG_CLASS, fmtMinutes, fmtStamp } from "../lib/time.js";

/**
 * Desglose de UNA fecha de ocurrencia de un empleado (Fase 10): qué bloques programados aportan horas ese día (de qué AP,
 * principal o adicional, y de qué fecha de turno, incluida la porción de un turno que empezó el día anterior), el tiempo
 * registrado, la nocturnidad, las reglas de almuerzo, el corte de nómina y las AP con efecto ese día.
 * Es la base para la auditoría diaria y el detalle de turnos.
 */
export default function DayDetailPage() {
  const { code, date } = useParams();
  const [state, setState] = useState({ loading: true, data: null, error: null });

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    schedulingApi
      .employeeDay(code, date, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [code, date]);

  const d = state.data;
  const s = d?.summary;
  return (
    <section className="card card--wide" aria-busy={state.loading}>
      <header className="card__header">
        <div>
          <p className="muted small">
            <Link to={`/hcm/employees/${code}?tab=schedule`}>← Horario del expediente</Link> · <Link to={`/scheduling/report?search=${code}`}>Horas teóricas vs reales</Link>
          </p>
          <h1 className="page-title">
            Desglose del {d ? `${d.weekday} ${formatDate(d.date)}` : formatDate(date)}
          </h1>
          {d && (
            <p className="muted page-subtitle">
              {d.full_name} · <code>{d.employee_code}</code> · {d.country}
            </p>
          )}
        </div>
        {d && (
          <nav className="week-view__nav" aria-label="Día">
            <Link className="button button--ghost button--sm" to={`/scheduling/employees/${code}/days/${d.previous_date}`}>
              ‹ Día anterior
            </Link>
            <Link className="button button--ghost button--sm" to={`/scheduling/employees/${code}/days/${d.next_date}`}>
              Día siguiente ›
            </Link>
          </nav>
        )}
      </header>
      {state.error && <p className="error-box">{state.error}</p>}
      {state.loading && !d && <p className="muted">Cargando el día…</p>}
      {d && (
        <>
          <dl className="kpis">
            <div className="kpi">
              <dt>Teórico</dt>
              <dd>{fmtMinutes(s?.scheduled_minutes ?? 0)}</dd>
            </div>
            <div className="kpi">
              <dt>Teórico nocturno</dt>
              <dd>{fmtMinutes(s?.scheduled_night_minutes ?? 0)}</dd>
            </div>
            <div className="kpi">
              <dt>Real</dt>
              <dd>{fmtMinutes(s?.worked_minutes ?? 0)}</dd>
            </div>
            <div className={`kpi ${(s?.variance_minutes ?? 0) < 0 ? "kpi--warn" : "kpi--ok"}`}>
              <dt>Diferencia</dt>
              <dd>{fmtMinutes(s?.variance_minutes ?? 0)}</dd>
            </div>
            <div className="kpi">
              <dt>Resultado</dt>
              <dd>
                <span className={`badge ${FLAG_CLASS[s?.flag] ?? "badge--muted"}`}>{s?.flag_label ?? "Descanso"}</span>
              </dd>
            </div>
          </dl>

          <h2 className="section-title">Bloques programados en esta fecha</h2>
          {d.blocks.length === 0 ? (
            <p className="muted">Sin horas programadas (descanso o sin horario vigente).</p>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">AP</th>
                    <th scope="col">Asignación</th>
                    <th scope="col">Jornada (fecha de turno)</th>
                    <th scope="col">Porción en esta fecha</th>
                    <th scope="col">Almuerzo</th>
                    <th scope="col">Netas</th>
                    <th scope="col">Nocturnas</th>
                  </tr>
                </thead>
                <tbody>
                  {d.blocks.map((b) => (
                    <tr key={`${b.assignment_id}-${b.shift_date}-${b.block}`}>
                      <th scope="row">
                        {b.folio ? (
                          <Link to={`/personnel-actions/${b.folio}`}>
                            <code>{b.folio}</code>
                          </Link>
                        ) : (
                          "—"
                        )}
                      </th>
                      <td>
                        <span className={`badge ${b.mode === "ADDITIONAL" ? "badge--warn" : "badge--muted"}`}>{b.mode === "ADDITIONAL" ? "Adicional" : "Principal"}</span>
                      </td>
                      <td>
                        {fmtStamp(b.start)} → {fmtStamp(b.end)}
                        {b.from_previous_day && <span className="badge badge--info shift-grid__badge">Inició el día anterior</span>}
                      </td>
                      <td>
                        {fmtStamp(b.on_this_date.start)} → {fmtStamp(b.on_this_date.end)}
                      </td>
                      <td>{b.on_this_date.lunch_minutes ? `${b.on_this_date.lunch_minutes} min` : "—"}</td>
                      <td>
                        <strong>{fmtMinutes(b.on_this_date.minutes)}</strong>
                      </td>
                      <td>{fmtMinutes(b.on_this_date.night_minutes)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h2 className="section-title">Tiempo registrado</h2>
          {d.records.length === 0 ? (
            <p className="muted">Sin registros de tiempo. La carga manual está retirada; las marcaciones llegarán del Web Timer interno.</p>
          ) : (
            <ul className="day-records">
              {d.records.map((r) => (
                <li key={r.id}>
                  {r.kind === "INTERVAL" ? `${fmtStamp(r.start_at)} → ${fmtStamp(r.end_at)}` : `${fmtMinutes(r.minutes)} h reportadas`}{" "}
                  <span className="muted small">
                    ({r.source_label}
                    {r.shift_date ? `, turno del ${formatDate(r.shift_date)}` : ", sin turno"}; en esta fecha:{" "}
                    {fmtMinutes(r.days.filter((x) => x.occurrence_date === d.date).reduce((acc, x) => acc + x.minutes, 0))} h)
                  </span>
                </li>
              ))}
            </ul>
          )}

          <h2 className="section-title">Contexto de nómina y parámetros</h2>
          <dl className="detail-list">
            <div>
              <dt>Corte de nómina</dt>
              <dd>
                {d.period
                  ? `${d.period.cycle} ${d.period.code} · asistencia ${formatDate(d.period.cutoff_start)}–${formatDate(d.period.cutoff_end)} · ${d.period.status_label.toLowerCase()}`
                  : "Sin periodo generado para esta fecha"}
              </dd>
            </div>
            <div>
              <dt>Nocturnidad</dt>
              <dd>{d.night_rule ? `${d.night_rule.start}–${d.night_rule.end} (+${d.night_rule.surcharge_percent} %)` : "Sin regla vigente"}</dd>
            </div>
            <div>
              <dt>Reglas de almuerzo</dt>
              <dd>
                {d.lunch_rules.length
                  ? d.lunch_rules.map((r) => `≥ ${fmtMinutes(r.min_block_minutes)} h continuas → ${r.lunch_minutes} min (${r.enforcement_label.toLowerCase()})`).join("; ")
                  : "Sin regla vigente"}
              </dd>
            </div>
            <div>
              <dt>Horarios vigentes</dt>
              <dd>
                {d.assignments.length
                  ? d.assignments.map((a, i) => (
                      <span key={a.id}>
                        {i > 0 && " + "}
                        {a.folio ? <Link to={`/personnel-actions/${a.folio}`}>{a.folio}</Link> : `#${a.id}`} ({a.mode_label.toLowerCase()})
                      </span>
                    ))
                  : "Ninguno"}
              </dd>
            </div>
          </dl>

          <h2 className="section-title">Auditoría del día</h2>
          {d.actions_effective.length ? (
            <ul>
              {d.actions_effective.map((a) => (
                <li key={a.folio}>
                  <Link to={`/personnel-actions/${a.folio}`}>{a.folio}</Link> — {a.action_type} ({a.status_label.toLowerCase()}) con fecha efectiva este día
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted small">Ninguna acción de personal tiene fecha efectiva este día.</p>
          )}
        </>
      )}
    </section>
  );
}
