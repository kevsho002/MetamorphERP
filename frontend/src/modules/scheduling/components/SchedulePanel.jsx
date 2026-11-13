import { useTimeFormat } from "../../../app/timeFormat.js";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { formatDate, todayIso } from "../../hcm/lib/format.js";
import ActionStatusBadge from "../../personnelActions/components/ActionStatusBadge.jsx";
import { ScheduleTable } from "../../personnelActions/components/WeeklyScheduleEditor.jsx";
import { actionsApi } from "../../personnelActions/api.js";
import { schedulingApi } from "../api.js";
import { FLAG_CLASS, addDays, fmtMinutes, fmtStamp, mondayOf } from "../lib/time.js";

/**
 * Pestaña «Horario» del expediente (Fase 9): el horario se dibuja a partir de las ACCIONES DE PERSONAL vigentes
 * por fechas efectivas (no hay turnos predefinidos). Cada día muestra inicio, fin, almuerzo y horas diurnas /
 * nocturnas; los cambios se hacen con una AP de cambio de horario que, al aprobarse, cierra el horario anterior.
 * Fase 10: un día puede tener varios bloques (turno partido) y, además del horario principal, asignaciones
 * ADICIONALES con fecha de fin; las horas programadas de todas se suman por fecha de ocurrencia.
 */
export default function SchedulePanel({ employee }) {
  useTimeFormat(); // Fase 21: re-render al cambiar HH:MM:SS / horas decimales
  const code = employee.employee_code;
  const [state, setState] = useState({ loading: true, data: null, error: null });

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    actionsApi
      .employee(code, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [code]);

  if (state.loading && !state.data) return <p className="muted">Cargando horario…</p>;
  if (!state.data) return <p className="error-box">{state.error}</p>;
  const d = state.data;
  const initialType = d.creatable_types.find((t) => t.is_initial_schedule);
  const changeType = d.creatable_types.find((t) => t.effect === "SCHEDULE" && !t.is_initial_schedule && t.schedule_mode !== "ADDITIONAL");
  const additionalType = d.creatable_types.find((t) => t.effect === "SCHEDULE" && t.schedule_mode === "ADDITIONAL");
  const additional = d.additional_schedules ?? [];
  const pending = d.results.filter((a) => a.effect === "SCHEDULE" && ["DRAFT", "PENDING"].includes(a.status));
  const current = d.current_schedule;

  return (
    <section aria-labelledby="sch-title" className="roster">
      <header className="docs-header">
        <h2 id="sch-title" className="section-title">
          Horario
        </h2>
        <span className="muted">
          {current ? (
            <>
              Vigente desde el {formatDate(current.effective_start_date)} por la AP{" "}
              <Link to={`/personnel-actions/${current.folio}`}>
                <code>{current.folio}</code>
              </Link>
            </>
          ) : (
            "Sin horario vigente"
          )}
        </span>
        {d.can_create && d.initial_action && changeType && (
          <Link className="button button--sm" to={`/personnel-actions/new?type=${changeType.code}&employee=${code}`}>
            Nueva AP de cambio de horario
          </Link>
        )}
        {d.can_create && d.initial_action && additionalType && (
          <Link className="button button--ghost button--sm" to={`/personnel-actions/new?type=${additionalType.code}&employee=${code}`}>
            Asignación adicional
          </Link>
        )}
      </header>

      {!d.initial_action && (
        <div className="alert alert--warn" role="status">
          <p className="alert__text">
            El colaborador no tiene su <strong>Primera AP de asignación de horario</strong> (AP fundacional de turno).
          </p>
          {d.can_create && initialType && (
            <Link className="button button--sm" to={`/personnel-actions/new?type=${initialType.code}&employee=${code}`}>
              Elaborar la Primera AP
            </Link>
          )}
        </div>
      )}
      {d.initial_action && d.initial_action.status !== "APPROVED" && (
        <p className="alert alert--warn">
          La Primera AP <Link to={`/personnel-actions/${d.initial_action.folio}`}>{d.initial_action.folio}</Link> está{" "}
          {d.initial_action.status_label.toLowerCase()}: el horario se aplica al completarse sus firmas.
        </p>
      )}
      {pending.length > 0 && (
        <p className="muted small">
          AP de horario en trámite:{" "}
          {pending.map((a) => (
            <span key={a.folio}>
              <Link to={`/personnel-actions/${a.folio}`}>{a.folio}</Link> (efectiva {formatDate(a.effective_date)}, <ActionStatusBadge status={a.status} label={a.status_label} />){" "}
            </span>
          ))}
        </p>
      )}

      {current && <ScheduleTable summary={current.schedule} caption={`Horario principal${current.is_now ? " (Now)" : ` hasta el ${formatDate(current.effective_end_date)}`}`} />}

      {additional.map((a) => (
        <div key={a.id} className="sch-additional">
          <ScheduleTable
            summary={a.schedule}
            caption={`Asignación adicional ${a.folio ?? ""} · del ${formatDate(a.effective_start_date)} al ${formatDate(a.effective_end_date)}${a.is_future ? " (futura)" : ""} — se suma al horario principal`}
          />
        </div>
      ))}

      {d.schedules.length > 0 && (
        <>
          <h3 className="section-title">Historial de horarios (por AP)</h3>
          <div className="table-wrap">
            <table className="table roster-table">
              <thead>
                <tr>
                  <th scope="col">AP</th>
                  <th scope="col">Tipo</th>
                  <th scope="col">Vigencia</th>
                  <th scope="col">Diurnas / nocturnas por semana</th>
                  <th scope="col">Total semanal</th>
                </tr>
              </thead>
              <tbody>
                {d.schedules.map((s) => (
                  <tr key={s.id}>
                    <th scope="row">
                      {s.folio ? (
                        <Link to={`/personnel-actions/${s.folio}`}>
                          <code>{s.folio}</code>
                        </Link>
                      ) : (
                        "—"
                      )}
                      {s.is_initial && <span className="badge badge--info">Fundacional</span>}
                    </th>
                    <td>
                      <span className={`badge ${s.mode === "ADDITIONAL" ? "badge--warn" : "badge--muted"}`}>{s.mode === "ADDITIONAL" ? "Adicional" : "Principal"}</span>
                    </td>
                    <td>
                      {formatDate(s.effective_start_date)} → {s.is_now ? <strong>Now</strong> : formatDate(s.effective_end_date)}
                    </td>
                    <td>
                      {fmtMinutes(s.schedule.weekly_day_minutes)} / {fmtMinutes(s.schedule.weekly_night_minutes)}
                    </td>
                    <td>{fmtMinutes(s.weekly_minutes)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <WeekView code={code} refreshKey={0} />
    </section>
  );
}

/** Semana del empleado por fecha de ocurrencia: programado (teórico, según sus AP) vs registrado (real). */
function WeekView({ code, refreshKey }) {
  const [from, setFrom] = useState(mondayOf(todayIso()));
  const [state, setState] = useState({ loading: true, data: null, error: null });

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    schedulingApi
      .timeline(code, { from, to: addDays(from, 6) }, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [code, from, refreshKey]);

  const data = state.data;
  return (
    <div className="week-view">
      <header className="docs-header">
        <h3 className="section-title">Semana por fecha de ocurrencia</h3>
        <div className="week-view__nav">
          <button type="button" className="button button--ghost button--sm" onClick={() => setFrom(addDays(from, -7))}>
            ‹ Semana anterior
          </button>
          <input type="date" value={from} onChange={(e) => e.target.value && setFrom(mondayOf(e.target.value))} aria-label="Semana" />
          <button type="button" className="button button--ghost button--sm" onClick={() => setFrom(addDays(from, 7))}>
            Semana siguiente ›
          </button>
        </div>
      </header>
      {state.error && <p className="error-box">{state.error}</p>}
      {data && (
        <>
          {data.cutoffs?.length > 0 && (
            <p className="muted small">
              Corte(s) de asistencia:{" "}
              {data.cutoffs
                .map((c) => `${c.cycle} ${c.code} (${formatDate(c.cutoff_start)}–${formatDate(c.cutoff_end)}, se paga en ${c.pay_period.code}, ${c.status_label.toLowerCase()})`)
                .join(" · ")}
            </p>
          )}
          <div className="table-wrap" aria-busy={state.loading}>
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Fecha de ocurrencia</th>
                  <th scope="col">Turno(s)</th>
                  <th scope="col">Teórico</th>
                  <th scope="col">Real</th>
                  <th scope="col">Nocturno real</th>
                  <th scope="col">Diferencia</th>
                  <th scope="col">Resultado</th>
                </tr>
              </thead>
              <tbody>
                {data.days.map((d) => (
                  <tr key={d.occurrence_date}>
                    <th scope="row">
                      <Link className="occurrence-link" to={`/scheduling/employees/${code}/days/${d.occurrence_date}`} title="Ver el desglose del día">
                        <span className="small">{d.weekday}</span> {formatDate(d.occurrence_date)}
                      </Link>
                    </th>
                    <td className="small">
                      {d.actions.join(" · ") || "—"}
                      {d.shift_dates.some((s) => s !== d.occurrence_date) && (
                        <span className="muted"> (turno del {d.shift_dates.filter((s) => s !== d.occurrence_date).map(formatDate).join(", ")})</span>
                      )}
                    </td>
                    <td>{fmtMinutes(d.scheduled_minutes)}</td>
                    <td>{fmtMinutes(d.worked_minutes)}</td>
                    <td>{d.worked_night_minutes ? fmtMinutes(d.worked_night_minutes) : "—"}</td>
                    <td className={d.variance_minutes < 0 ? "text-error" : undefined}>{fmtMinutes(d.variance_minutes)}</td>
                    <td>
                      <span className={`badge ${FLAG_CLASS[d.flag] ?? "badge--muted"}`}>{d.flag_label}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th scope="row" colSpan={2}>
                    Total
                  </th>
                  <td>{fmtMinutes(data.totals.scheduled_minutes ?? 0)}</td>
                  <td>{fmtMinutes(data.totals.worked_minutes ?? 0)}</td>
                  <td>{fmtMinutes(data.totals.worked_night_minutes ?? 0)}</td>
                  <td>{fmtMinutes(data.totals.variance_minutes ?? 0)}</td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
          {data.records.length > 0 && (
            <details className="week-view__records">
              <summary>Registros de tiempo de la semana ({data.records.length})</summary>
              <ul>
                {data.records.map((r) => (
                  <li key={r.id}>
                    {r.kind === "INTERVAL" ? `${fmtStamp(r.start_at)} → ${fmtStamp(r.end_at)}` : `${formatDate(r.occurrence_date)} · ${fmtMinutes(r.minutes)}`}{" "}
                    <span className="muted small">
                      ({r.source_label}
                      {r.shift_date ? `, turno del ${formatDate(r.shift_date)}` : ", sin turno"})
                      {r.days.length > 1 && ` — ${r.days.map((d) => `${formatDate(d.occurrence_date)}: ${fmtMinutes(d.minutes)}`).join(" + ")}`}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}
    </div>
  );
}
