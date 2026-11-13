import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { todayIso } from "../../hcm/lib/format.js";
import { ATTENDANCE, adhApi, fmtPct, hhmm } from "../../wfm/api.js";
import ActivityModal from "../../wfm/components/ActivityModal.jsx";
import GanttTrack, { GanttScale } from "../../wfm/components/Gantt.jsx";

const PPM = 1.2;

/**
 * Mi plan y mi equipo (Fase 19, autoservicio en MODO LECTURA): el día del agente y, si es líder en la cadena de mando
 * del roster (Team Manager, Account Supervisor, Operations Manager o Director), el de los agentes bajo su mando. Clic
 * en una actividad o en el turno abre la ventana de detalle; las correcciones se envían a la cola de aprobación de WFM.
 */
export default function MyPlanPage() {
  const [params, setParams] = useSearchParams();
  const date = params.get("date") ?? todayIso();
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [reload, setReload] = useState(0);
  const [modal, setModal] = useState(null);
  const drag = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    adhApi
      .myPlan({ date }, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [date, reload]);

  const closeModal = useCallback(() => setModal(null), []);
  const data = state.data;
  const win = data?.grid ? { start: data.grid.window_start, end: data.grid.window_end } : null;
  const open = (row, d, focus) => setModal({ employee_code: row.employee_code, full_name: row.full_name, date: d, focus });
  const go = (value) => setParams(value ? { date: value } : {}, { replace: true });

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Mi plan{data?.is_leader ? " y mi equipo" : ""}</h1>
          <p className="muted page-subtitle">
            Consulta en modo lectura. Clic en una actividad o en el turno para ver el detalle; si algo no corresponde, solicite la corrección a WFM desde esa
            ventana.
          </p>
        </div>
        <div className="iex__date">
          <button type="button" className="button button--ghost button--sm" aria-label="Día anterior" onClick={() => data && go(data.previous)}>
            ‹
          </button>
          <input type="date" value={date} aria-label="Fecha del turno" onChange={(e) => e.target.value && go(e.target.value)} />
          <button type="button" className="button button--ghost button--sm" aria-label="Día siguiente" onClick={() => data && go(data.next)}>
            ›
          </button>
          <button type="button" className="link-button" onClick={() => go("")}>
            Hoy
          </button>
        </div>
      </header>
      {state.error && <p className="error-box">{state.error}</p>}
      {state.loading && <p className="muted">Cargando…</p>}
      {data && data.rows.length === 0 && (
        <p className="empty">Su usuario no está vinculado a un expediente con turno ni a un equipo en la cadena de mando del roster.</p>
      )}
      {data && data.rows.length > 0 && win && (
        <div className="gantt" role="grid" aria-label={`Plan del ${date}`}>
          <div className="gantt__row gantt__row--head" role="row">
            <div className="gantt__who" role="columnheader">
              {data.is_leader ? `Agente (${data.team_size} en el equipo)` : "Agente"}
            </div>
            <div role="columnheader">
              <GanttScale win={win} ppm={PPM} interval={data.grid.interval_minutes} />
            </div>
            <div className="gantt__metric" role="columnheader">
              Adh.
            </div>
          </div>
          {data.rows.map((r) => (
            <div key={r.employee_code} className={`gantt__row${r.is_me ? " is-today" : ""}`} role="row">
              <div className="gantt__who" role="rowheader">
                <div className="gantt__who-text">
                  <button type="button" className="link-button gantt__name" onClick={() => open(r, date, "container")}>
                    {r.full_name}
                    {r.is_me ? " (yo)" : ""}
                  </button>
                  <span className="muted small">
                    {r.employee_code}
                    {r.containers.length ? ` · ${r.containers.map((c) => `${hhmm(c.start)}–${hhmm(c.end)}`).join(", ")}` : " · sin turno"}
                  </span>
                  {ATTENDANCE[r.attendance] && <span className={`badge ${ATTENDANCE[r.attendance].cls} gantt__att`}>{ATTENDANCE[r.attendance].label}</span>}
                </div>
              </div>
              <div role="gridcell">
                <GanttTrack date={date} win={win} ppm={PPM} interval={data.grid.interval_minutes} snapSeconds={data.grid.snap_seconds} row={r}
                  statusColors={data.status_colors} canManage={false} drag={drag} armed={null} selectedId={modal?.employee_code === r.employee_code ? modal.focus : null}
                  defaultName={r.plan.find((b) => b.source === "CONTAINER")?.activity_name ?? "Producción"}
                  onSelectSegment={(seg, row, d) => open(row, d, seg.id)} onSelectContainer={(row, d) => open(row, d, "container")}
                  onDropActivity={() => {}} onMoveSegment={() => {}} onPlaceArmed={() => {}} />
              </div>
              <div className="gantt__metric" role="gridcell">
                {r.metrics ? fmtPct(r.metrics.adherence_pct) : "—"}
              </div>
            </div>
          ))}
        </div>
      )}
      {modal && <ActivityModal key={`${modal.employee_code}-${modal.date}`} target={modal} onClose={closeModal} onChanged={() => setReload((k) => k + 1)} />}
    </section>
  );
}
