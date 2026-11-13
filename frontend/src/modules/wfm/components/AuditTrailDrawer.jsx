import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { adhApi, fmtDuration, hhmm } from "../api.js";

const KINDS = [
  ["", "Todo"],
  ["change", "Cambios"],
  ["approval", "Aprobaciones"],
  ["action", "Acciones"],
  ["system", "Sistema"],
];
const SOURCES = { wfm: "WFM", pa: "Acción de personal", roster: "Roster", acd: "ACD", adherence: "Adherencia", cutoff: "Corte", schedule: "Horario" };
const LEVELS = [
  ["TEAM_MANAGER", "Team Manager"],
  ["ACCOUNT_SUPERVISOR", "Account Supervisor"],
  ["OPS_MANAGER", "Operations Manager"],
  ["OPS_DIRECTOR", "Operations Director"],
];

function when(iso) {
  if (!iso) return "—";
  return `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)} ${iso.slice(11, 19)}`;
}

function SegmentState({ value }) {
  if (!value) return <span className="muted">—</span>;
  return (
    <>
      <strong>{value.activity_name}</strong> {hhmm(value.start)}–{hhmm(value.end)} <span className="muted">({fmtDuration(value.seconds)})</span>
      {value.notes ? <span className="muted"> · {value.notes}</span> : null}
    </>
  );
}

/**
 * Audit Trail de una línea de la grilla (agente + fecha de turno), Fase 18: historial de cambios del plan (con antes /
 * después al segundo), AP y sus firmas de aprobación, roster, sesiones ACD, cálculo guardado y cierre del corte.
 */
export default function AuditTrailDrawer({ target, onClose }) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [kind, setKind] = useState("");
  const panel = useRef(null);
  const opener = useRef(typeof document !== "undefined" ? document.activeElement : null);

  useEffect(() => {
    const controller = new AbortController();
    adhApi
      .auditTrail({ employee: target.employee_code, date: target.date }, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [target.employee_code, target.date]);

  // Foco al abrir, Escape cierra y el foco vuelve a donde estaba.
  useEffect(() => {
    panel.current?.focus();
    const back = opener.current;
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      if (back && typeof back.focus === "function") back.focus();
    };
  }, [onClose]);

  const entries = useMemo(() => (state.data?.entries ?? []).filter((e) => !kind || e.kind === kind), [state.data, kind]);
  const d = state.data;

  return (
    <div className="audit-drawer" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="audit-drawer__panel" role="dialog" aria-modal="true" aria-labelledby="audit-title" tabIndex={-1} ref={panel}>
        <header className="audit-drawer__head">
          <div>
            <p className="audit-drawer__eyebrow">Audit trail</p>
            <h2 id="audit-title" className="audit-drawer__title">
              {target.full_name ?? target.employee_code}
            </h2>
            <p className="muted small">
              {target.employee_code} · fecha de turno {target.date.slice(8, 10)}/{target.date.slice(5, 7)}/{target.date.slice(0, 4)}
              {d?.frozen ? ` · corte ${d.cutoff} cerrado` : ""}
            </p>
          </div>
          <button type="button" className="audit-drawer__close" onClick={onClose} aria-label="Cerrar audit trail">
            ×
          </button>
        </header>

        {state.loading && <p className="muted audit-drawer__pad">Cargando historial…</p>}
        {state.error && <p className="error-box audit-drawer__pad">{state.error}</p>}
        {d && (
          <div className="audit-drawer__body">
            {d.hierarchy && (
              <dl className="audit-drawer__chain">
                {LEVELS.map(([lvl, label]) =>
                  d.hierarchy[lvl] ? (
                    <div key={lvl}>
                      <dt>{label}</dt>
                      <dd>{d.hierarchy[lvl].full_name}</dd>
                    </div>
                  ) : null,
                )}
              </dl>
            )}
            {d.segments.length > 0 && (
              <p className="small audit-drawer__now">
                <span className="muted">Plan vigente: </span>
                {d.segments.map((s) => `${s.activity_name} ${hhmm(s.start)}–${hhmm(s.end)}`).join(" · ")}
              </p>
            )}
            <div className="audit-drawer__chips" role="group" aria-label="Filtrar por tipo">
              {KINDS.map(([value, label]) => (
                <button key={value || "all"} type="button" className={`audit-chip${kind === value ? " is-on" : ""}`} aria-pressed={kind === value}
                  onClick={() => setKind(value)}>
                  {label}
                  <span className="audit-chip__count">{value ? d.counts[value] ?? 0 : d.entries.length}</span>
                </button>
              ))}
            </div>
            {entries.length === 0 ? (
              <p className="empty">Sin registros {kind ? "de este tipo " : ""}para esta línea.</p>
            ) : (
              <ol className="audit-list">
                {entries.map((e, i) => (
                  <li key={`${e.at}-${e.action}-${i}`} className={`audit-list__item audit-list__item--${e.kind}`}>
                    <div className="audit-list__meta">
                      <time dateTime={e.at}>{when(e.at)}</time>
                      <span className={`audit-kind audit-kind--${e.kind}`}>{e.kind_label}</span>
                      <span className="muted small">{SOURCES[e.source] ?? e.source}</span>
                    </div>
                    <p className="audit-list__title">{e.title}</p>
                    {e.summary && <p className="audit-list__summary small">{e.summary}</p>}
                    {(e.before || e.after) && (
                      <dl className="audit-diff small">
                        <div>
                          <dt>Antes</dt>
                          <dd>
                            <SegmentState value={e.before} />
                          </dd>
                        </div>
                        <div>
                          <dt>Después</dt>
                          <dd>
                            <SegmentState value={e.after} />
                          </dd>
                        </div>
                      </dl>
                    )}
                    <p className="muted small audit-list__actor">
                      {e.actor ? `Por ${e.actor}` : "Automático"}
                      {e.source === "pa" && e.ref ? (
                        <>
                          {" · "}
                          <Link to={`/personnel-actions/${encodeURIComponent(e.ref)}`}>ver AP {e.ref}</Link>
                        </>
                      ) : null}
                    </p>
                  </li>
                ))}
              </ol>
            )}
            {d.truncated && <p className="muted small">Se muestran los 400 registros más recientes.</p>}
          </div>
        )}
      </aside>
    </div>
  );
}
