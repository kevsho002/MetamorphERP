import { useTimeFormat } from "../../../app/timeFormat.js";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { todayIso } from "../../hcm/lib/format.js";
import {
  ATTENDANCE, addSeconds, adhApi, durationText, fmtDuration, fmtHM, fmtPct, groupByCategory, hhmm, hhmmss, minutesFrom, minutesToHMS, parseDuration,
} from "../api.js";
import ActivityIcon from "../components/ActivityIcon.jsx";
import ActivityModal from "../components/ActivityModal.jsx";
import AuditTrailDrawer from "../components/AuditTrailDrawer.jsx";
import GanttTrack, { GanttScale, PATTERN_MINUTES } from "../components/Gantt.jsx";
import FieldHint from "../../../components/ui/FieldHint.jsx";
import EmployeeAutocomplete from "../../../components/ui/EmployeeAutocomplete.jsx";

const FILTER_KEYS = ["group", "client", "brand", "director", "manager", "supervisor", "team_manager", "search"];
const LEVEL_PARAMS = [
  ["director", "OPS_DIRECTOR", "Operations Director"],
  ["manager", "OPS_MANAGER", "Operations Manager"],
  ["supervisor", "ACCOUNT_SUPERVISOR", "Account Supervisor"],
  ["team_manager", "TEAM_MANAGER", "Team Manager"],
];
const ZOOMS = [
  { value: 1, label: "60 px/h" },
  { value: 1.6, label: "96 px/h" },
  { value: 2.4, label: "144 px/h" },
  { value: 3.2, label: "192 px/h" },
];
const WEEKDAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const FILTERS_PIN_KEY = "metamorph.iex.filters.pinned";
const PAGE_SIZES = [25, 50, 100, 200];
const DEFAULT_PAGE_SIZE = 50;
const TOOL_CATEGORY_KEY = "metamorph.iex.toolbox.category";
const WIDE = "(min-width: 1101px)";

const shiftDate = (iso, days) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
};

function pctClass(v) {
  if (v === null || v === undefined) return "";
  return v >= 90 ? "adh-pct--ok" : v >= 80 ? "adh-pct--warn" : "adh-pct--bad";
}

function readPinned() {
  try {
    const v = window.localStorage.getItem(FILTERS_PIN_KEY);
    return v === null ? window.matchMedia(WIDE).matches : v === "1";
  } catch {
    return true;
  }
}

/** Mismo icono «chevrones / alfiler» del menú principal de módulos. */
function PinIcon({ pinned }) {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true">
      {pinned ? <path d="M15 18l-6-6 6-6M20 18l-6-6 6-6" /> : <path d="M12 17v5M9 3h6l-1 6 3 3v2H7v-2l3-3z" />}
    </svg>
  );
}

/**
 * Planificación WFM estilo Nice IEX (Fases 17 y 18).
 *
 * * Panel izquierdo de filtros PLEGABLE como el menú de módulos: fijo, o contraído a una barra de íconos que se
 *   despliega sobre la grilla al pasar el cursor / recibir el foco (Management Unit, cuenta y cadena de mando del roster).
 * * Barra superior compacta: un cuadrado por actividad (solo icono + tooltip), en una tira horizontal con flechas.
 * * Los segmentos son una línea delgada con el icono de la actividad repetido cada 15 minutos; todo va al SEGUNDO.
 * * Clic en la cabecera de una fila (agente o fecha) abre su Audit Trail.
 * * Fase 19: desplegable de categorías (Time Utilization) que filtra la barra; clic en una actividad o en el
 *   pre-contenedor abre la ventana flotante del día (tabla + edición / solicitudes); Lateness y ausencias automáticas.
 */
export default function PlanningPage() {
  useTimeFormat(); // Fase 21: re-render al cambiar HH:MM:SS / horas decimales
  const [params, setParams] = useSearchParams();
  const view = params.get("view") === "agent" ? "agent" : "grid";
  const date = params.get("date") ?? todayIso();
  const employee = params.get("employee") ?? "";
  const from = params.get("from") ?? "";
  const filters = useMemo(() => Object.fromEntries(FILTER_KEYS.map((k) => [k, params.get(k) ?? ""])), [params]);
  // Fase 27: la grilla de grupo no se consulta sin filtros y carga los agentes por páginas.
  const hasFilter = FILTER_KEYS.some((k) => filters[k]);
  const page = Math.max(1, Number(params.get("page")) || 1);
  const pageSize = PAGE_SIZES.includes(Number(params.get("size"))) ? Number(params.get("size")) : DEFAULT_PAGE_SIZE;

  const [meta, setMeta] = useState(null);
  const [metaError, setMetaError] = useState(null);
  const [state, setState] = useState({ loading: false, data: null, error: null });
  const [reloadKey, setReloadKey] = useState(0);
  const [notice, setNotice] = useState(null);
  const [modal, setModal] = useState(null); // ventana flotante: { employee_code, full_name, date, focus }
  const [armed, setArmed] = useState(null); // actividad elegida con clic (alternativa al arrastre)
  const [zoom, setZoom] = useState(null);
  const [busy, setBusy] = useState(false);
  const [audit, setAudit] = useState(null); // { employee_code, full_name, date }
  const [filtersPinned, setFiltersPinned] = useState(readPinned);
  const drag = useRef(null);

  const toggleFiltersPin = useCallback(() => {
    setFiltersPinned((v) => {
      try {
        window.localStorage.setItem(FILTERS_PIN_KEY, v ? "0" : "1");
      } catch {
        // almacenamiento bloqueado: la preferencia dura solo esta visita
      }
      return !v;
    });
  }, []);

  const update = useCallback(
    (changes) => {
      setParams((p) => {
        const next = { ...Object.fromEntries(p), ...changes };
        // Cambiar un filtro (o el tamaño de página) vuelve a la primera página.
        if (!("page" in changes) && Object.keys(changes).some((k) => FILTER_KEYS.includes(k) || k === "size")) delete next.page;
        return Object.fromEntries(Object.entries(next).filter(([, v]) => v));
      }, { replace: true });
    },
    [setParams],
  );

  useEffect(() => {
    const controller = new AbortController();
    adhApi
      .gridFilters({ signal: controller.signal })
      .then(setMeta)
      .catch((err) => err.name !== "AbortError" && setMetaError(err.message));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if ((view === "agent" && !employee) || (view === "grid" && !hasFilter)) {
      setState({ loading: false, data: null, error: null });
      return undefined;
    }
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    const call =
      view === "agent"
        ? adhApi.agentHistory({ employee, from }, { signal: controller.signal })
        : adhApi.grid({ date, ...filters, page, page_size: pageSize }, { signal: controller.signal });
    call
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [view, date, employee, from, filters, hasFilter, page, pageSize, reloadKey]);

  const data = state.data;
  const canManage = Boolean(data?.can_manage ?? meta?.can_manage);
  const toolbox = data?.toolbox ?? [];
  const defaultName = toolbox.find((a) => a.is_default)?.name ?? "Producción";
  const grid = data?.grid ?? meta?.setting;
  const interval = grid?.interval_minutes ?? 15;
  const snapSeconds = grid?.snap_seconds ?? 300;
  const ppm = zoom ?? (interval >= 30 ? 1 : 1.6);
  const win = data?.grid ? { start: data.grid.window_start, end: data.grid.window_end } : { start: 360, end: 1200 };

  const after = useCallback((body) => {
    const m = body.refresh?.metrics;
    setNotice({
      ok: true,
      text: `${body.feedback}${m ? ` Adherencia del día: ${fmtPct(m.adherence_pct)} (programado ${fmtHM(m.scheduled)}).` : ""}${
        body.refresh?.stored_recomputed ? " El resultado guardado para nómina y calidad se recalculó." : ""}`,
    });
    setReloadKey((k) => k + 1);
  }, []);
  const fail = useCallback((err) => setNotice({ ok: false, text: err.message }), []);
  const closeModal = useCallback(() => setModal(null), []);

  /** Ajusta [start, start + dur) (minutos con decimales) al pre-contenedor que contiene `start`; null si se soltó fuera. */
  const fit = (row, rowDate, start, dur) => {
    const boxes = row.containers.map((c) => ({ s: minutesFrom(rowDate, c.start), e: minutesFrom(rowDate, c.end) }));
    const box = boxes.find((b) => start >= b.s && start < b.e) ?? boxes.find((b) => start + dur > b.s && start < b.s);
    if (!box) return null;
    const d = Math.min(dur, box.e - box.s);
    const s = Math.max(box.s, Math.min(start, box.e - d));
    return { s, e: s + d };
  };

  const place = (row, rowDate, start, activity) => {
    const span = fit(row, rowDate, start, (activity.default_seconds || 1800) / 60);
    if (!span) {
      setNotice({ ok: false, text: row.containers.length ? `Suelte ${activity.name} dentro del turno de ${row.full_name ?? "el agente"} (pre-contenedor gris).` : `${row.full_name ?? "El agente"} no tiene turno el ${rowDate}: no hay pre-contenedor donde insertar el segmento.` });
      return;
    }
    setBusy(true);
    adhApi
      .createSegment({ employee_code: row.employee_code ?? data.employee_code, shift_date: rowDate, activity: activity.code,
        start: minutesToHMS(span.s), end: minutesToHMS(span.e) })
      .then(after)
      .catch(fail)
      .finally(() => setBusy(false));
  };

  const move = (row, rowDate, start, segment) => {
    const span = fit(row, rowDate, start, segment.seconds / 60);
    if (!span) {
      setNotice({ ok: false, text: "El segmento debe quedar dentro del turno (pre-contenedor)." });
      return;
    }
    if (minutesToHMS(span.s) === hhmmss(segment.start)) return;
    setBusy(true);
    adhApi.updateSegment(segment.id, { start: minutesToHMS(span.s), end: minutesToHMS(span.e) }).then(after).catch(fail).finally(() => setBusy(false));
  };

  const trackProps = {
    win, ppm, interval, snapSeconds, canManage, drag, armed, defaultName, statusColors: data?.status_colors ?? {},
    selectedId: modal?.focus, onDropActivity: place, onMoveSegment: move, onPlaceArmed: (r, d, s, a) => { place(r, d, s, a); setArmed(null); },
    onSelectSegment: (segment, row, d) => setModal({ employee_code: row.employee_code, full_name: row.full_name, date: d, focus: segment.id }),
    onSelectContainer: (row, d) => setModal({ employee_code: row.employee_code, full_name: row.full_name, date: d, focus: "container" }),
  };
  const reconcile = () => {
    setBusy(true);
    adhApi
      .reconcile({ date, ...filters })
      .then((b) => { setNotice({ ok: true, text: b.feedback }); setReloadKey((k) => k + 1); })
      .catch(fail)
      .finally(() => setBusy(false));
  };
  const snapLabel = grid?.snaps?.find((s) => s.value === snapSeconds)?.label ?? `${snapSeconds} s`;

  return (
    <section className="iex">
      <header className="iex__head">
        <div>
          <h1 className="page-title">Planificación WFM</h1>
          <p className="muted page-subtitle">
            El turno vigente (AP de horario) es el pre-contenedor gris; arrastre un segmento de la barra y suéltelo a la hora exacta (al segundo). Clic en una
            actividad o en el pre-contenedor: detalle del día. Clic en la cabecera de una fila: audit trail.
          </p>
        </div>
        <div className="iex__views" role="tablist" aria-label="Vista">
          <button type="button" role="tab" aria-selected={view === "grid"} className={`iex__tab${view === "grid" ? " is-active" : ""}`}
            onClick={() => update({ view: "", from: "" })}>
            Grilla de grupo
          </button>
          <button type="button" role="tab" aria-selected={view === "agent"} className={`iex__tab${view === "agent" ? " is-active" : ""}`}
            onClick={() => update({ view: "agent" })}>
            Agente (histórico)
          </button>
        </div>
      </header>

      <div className="iex__toolbar" aria-label="Barra de segmentos">
        {view === "grid" && (
          <div className="iex__date">
            <button type="button" className="button button--ghost button--sm" aria-label="Día anterior" onClick={() => update({ date: shiftDate(date, -1) })}>
              ‹
            </button>
            <input type="date" value={date} aria-label="Fecha del turno" onChange={(e) => e.target.value && update({ date: e.target.value })} />
            <button type="button" className="button button--ghost button--sm" aria-label="Día siguiente" onClick={() => update({ date: shiftDate(date, 1) })}>
              ›
            </button>
            <button type="button" className="link-button" onClick={() => update({ date: todayIso() })}>
              Hoy
            </button>
          </div>
        )}
        <ToolStrip toolbox={toolbox} categories={data?.categories ?? []} canManage={canManage} armed={armed} setArmed={setArmed} drag={drag} />
        <div className="iex__view-opts">
          <label className="iex__opt">
            <span className="muted small">Zoom</span>
            <select value={ppm} onChange={(e) => setZoom(Number(e.target.value))}>
              {ZOOMS.map((z) => (
                <option key={z.value} value={z.value}>
                  {z.label}
                </option>
              ))}
            </select>
          </label>
          {grid && <GridSettings grid={grid} group={filters.group} canManage={canManage} onSaved={(b) => { setNotice({ ok: true, text: b.feedback }); setReloadKey((k) => k + 1); }} onError={fail} />}
          {canManage && view === "grid" && hasFilter && (
            <button type="button" className="button button--ghost button--sm" onClick={reconcile} disabled={busy}
              title="Inserta el Lateness de quien inició sesión tarde y marca Unjustified Absence (con Legal Benefit Lunch) a quien no se presentó">
              Conciliar asistencia
            </button>
          )}
        </div>
      </div>
      {armed && (
        <p className="iex__armed" role="status">
          <ActivityIcon name={armed.icon} /> {armed.name}: haga clic en la hora del turno del agente para insertarlo.{" "}
          <button type="button" className="link-button" onClick={() => setArmed(null)}>
            Cancelar
          </button>
        </p>
      )}

      <div className={`iex__body${filtersPinned ? "" : " iex__body--filters-collapsed"}`}>
        <FilterPanel meta={meta} filters={filters} view={view} employee={employee} update={update} pinned={filtersPinned} onTogglePin={toggleFiltersPin} />
        <div className="iex__main">
          {metaError && <p className="error-box">{metaError}</p>}
          {notice && (
            <div className={`alert ${notice.ok ? "alert--ok" : "alert--error"} flash`} role="status">
              <p className="alert__text">{notice.text}</p>
              {notice.skipped?.length > 0 && (
                <details>
                  <summary>{notice.skipped.length} omitidos</summary>
                  <ul className="msg-list msg-list--warn">
                    {notice.skipped.map((s) => (
                      <li key={`${s.employee_code}-${s.date}`}>
                        {s.employee_code} · {s.date}: {s.reason}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}
          {state.error && <p className="error-box">{state.error}</p>}
          {(state.loading || busy) && <p className="muted iex__loading">{busy ? "Guardando y recalculando adherencia…" : "Cargando…"}</p>}

          {view === "grid" && !hasFilter && <FiltersRequired meta={meta} update={update} />}
          {view === "grid" && hasFilter && data?.paging && data.paging.count > 0 && (
            <GridPager paging={data.paging} shown={data.rows.length} update={update} />
          )}
          {view === "grid" && data?.rows && (
            <GroupGrid data={data} date={date} trackProps={trackProps} canManage={canManage} snapLabel={snapLabel} audit={audit}
              onAudit={(r) => setAudit({ employee_code: r.employee_code, full_name: r.full_name, date })}
              onOpenAgent={(code) => update({ view: "agent", employee: code, from: "" })}
              onBulkDone={(b) => { setNotice({ ok: true, text: b.feedback, skipped: b.skipped }); setReloadKey((k) => k + 1); }} onError={fail} />
          )}
          {view === "agent" && !employee && <p className="empty">Indique el ID corporativo del agente en el panel izquierdo o ábralo desde la grilla de grupo.</p>}
          {view === "agent" && data?.rows && data.employee_code && (
            <AgentHistory data={data} trackProps={trackProps} update={update} audit={audit}
              onAudit={(d) => setAudit({ employee_code: data.employee_code, full_name: data.full_name, date: d })} />
          )}
        </div>
      </div>
      {audit && <AuditTrailDrawer key={`${audit.employee_code}-${audit.date}-${reloadKey}`} target={audit} onClose={() => setAudit(null)} />}
      {modal && (
        <ActivityModal key={`${modal.employee_code}-${modal.date}`} target={modal} onClose={closeModal} onChanged={() => setReloadKey((k) => k + 1)}
          onAudit={(t) => { setModal(null); setAudit({ employee_code: t.employee_code, full_name: t.full_name, date: t.date }); }} />
      )}
    </section>
  );
}

/* ---------------------------------------------------------------------------- barra compacta de segmentos -- */
/**
 * Tira horizontal continua de cuadrados (solo icono). Sin barra de desplazamiento nativa: flechas laterales y la
 * rueda del ratón desplazan; el nombre completo aparece en un tooltip flotante (hover o foco).
 */
function readCategory() {
  try {
    return window.localStorage.getItem(TOOL_CATEGORY_KEY) ?? "";
  } catch {
    return "";
  }
}

function ToolStrip({ toolbox, categories, canManage, armed, setArmed, drag }) {
  const viewport = useRef(null);
  const [edges, setEdges] = useState({ left: false, right: false });
  const [hint, setHint] = useState(null); // { text, sub, x, y }
  // Fase 19: categoría del Time Utilization elegida; la barra muestra solo sus actividades.
  const [category, setCategory] = useState(readCategory);
  const groups = useMemo(() => {
    const order = new Map(categories.map((c, i) => [c.code, i]));
    return groupByCategory(toolbox).sort((a, b) => (order.get(a.code) ?? 999) - (order.get(b.code) ?? 999));
  }, [toolbox, categories]);
  const current = groups.some((g) => g.code === category) ? category : "*";
  const shown = current === "*" ? toolbox : groups.find((g) => g.code === current)?.items ?? [];
  const choose = (value) => {
    setCategory(value);
    try {
      window.localStorage.setItem(TOOL_CATEGORY_KEY, value);
    } catch {
      // almacenamiento bloqueado: la elección dura solo esta visita
    }
    if (viewport.current) viewport.current.scrollLeft = 0;
    setHint(null);
  };

  const measure = useCallback(() => {
    const el = viewport.current;
    if (!el) return;
    setEdges({ left: el.scrollLeft > 1, right: el.scrollLeft + el.clientWidth < el.scrollWidth - 1 });
  }, []);
  useLayoutEffect(() => {
    measure();
    const el = viewport.current;
    if (!el || typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [measure, shown.length]);

  const scrollBy = (dir) => {
    const el = viewport.current;
    if (!el) return;
    el.scrollBy({ left: dir * Math.max(120, el.clientWidth * 0.8), behavior: "smooth" });
  };
  const show = (e, a) => {
    const r = e.currentTarget.getBoundingClientRect();
    const sub = [a.default_seconds ? fmtDuration(a.default_seconds) : null, a.is_paid ? null : "no pagado", a.is_billable ? "facturable" : null,
      a.is_default ? "predeterminada del turno" : null, a.requires_ap ? "requiere AP" : null,
      a.requires_acd_login ? null : "sin sesión ACD"].filter(Boolean).join(" · ");
    setHint({ text: a.name, sub, x: r.left + r.width / 2, y: r.bottom + 8 });
  };

  return (
    <div className="iex-strip">
      <label className="iex-strip__category">
        <span className="sr-only">Categoría de segmentos</span>
        <select value={current} onChange={(e) => choose(e.target.value)} title="Categoría (Time Utilization): la barra muestra solo sus segmentos">
          <option value="*">Todas las categorías ({toolbox.length})</option>
          {[...new Set(groups.map((g) => g.department))].map((dept) => (
            <optgroup key={dept || "none"} label={dept || "Sin departamento"}>
              {groups.filter((g) => g.department === dept).map((g) => (
                <option key={g.code || "none"} value={g.code}>
                  {g.name} ({g.items.length})
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>
      <button type="button" className="iex-strip__arrow" aria-label="Ver actividades anteriores" disabled={!edges.left} onClick={() => scrollBy(-1)}>
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M15 18l-6-6 6-6" />
        </svg>
      </button>
      <div
        className={`iex-strip__viewport${edges.left ? " has-left" : ""}${edges.right ? " has-right" : ""}`}
        ref={viewport}
        onScroll={() => { measure(); setHint(null); }}
        onWheel={(e) => {
          if (Math.abs(e.deltaY) > Math.abs(e.deltaX) && viewport.current) viewport.current.scrollLeft += e.deltaY;
        }}
      >
        <ul className="iex-strip__list" aria-label="Actividades: arrastre a la grilla o haga clic y luego clic en la hora">
          {shown.map((a) => (
            <li key={a.code}>
              <button
                type="button"
                className={`iex-tool${armed?.code === a.code ? " is-armed" : ""}${a.requires_ap ? " needs-ap" : ""}`}
                style={{ "--tool-color": a.color }}
                draggable={canManage}
                disabled={!canManage}
                aria-label={`${a.name}${a.default_seconds ? `, ${fmtDuration(a.default_seconds)}` : ""}`}
                aria-pressed={armed?.code === a.code}
                onMouseEnter={(e) => show(e, a)}
                onMouseLeave={() => setHint(null)}
                onFocus={(e) => show(e, a)}
                onBlur={() => setHint(null)}
                onDragStart={(e) => {
                  setHint(null);
                  drag.current = { kind: "activity", activity: a, grab: 0 };
                  e.dataTransfer.effectAllowed = "copy";
                  e.dataTransfer.setData("text/plain", `activity:${a.code}`);
                }}
                onDragEnd={() => {
                  drag.current = null;
                }}
                onClick={() => setArmed((cur) => (cur?.code === a.code ? null : a))}
              >
                <ActivityIcon name={a.icon} size={18} />
              </button>
            </li>
          ))}
        </ul>
      </div>
      <button type="button" className="iex-strip__arrow" aria-label="Ver más actividades" disabled={!edges.right} onClick={() => scrollBy(1)}>
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M9 18l6-6-6-6" />
        </svg>
      </button>
      {hint && (
        <span className="iex-tooltip" role="tooltip" style={{ left: hint.x, top: hint.y }}>
          <strong>{hint.text}</strong>
          {hint.sub && <span>{hint.sub}</span>}
        </span>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------------------- panel izquierdo plegable -- */
const RAIL = [
  { id: "mu", label: "Management Unit", keys: ["group"], d: "M3 7h18M3 12h18M3 17h18" },
  { id: "account", label: "Cuenta (cliente / marca)", keys: ["client", "brand"], d: "M4 21V5a2 2 0 0 1 2-2h8l6 6v12zM14 3v6h6M8 13h8M8 17h5" },
  { id: "chain", label: "Cadena de mando", keys: ["director", "manager", "supervisor", "team_manager"],
    d: "M12 3v4M12 7a2 2 0 1 0 0 .01M6 21v-4h12v4M12 9v8M6 17a2 2 0 1 0 0 .01M18 17a2 2 0 1 0 0 .01" },
  { id: "search", label: "Buscar agente", keys: ["search"], d: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-5-5" },
];

/* ---------------------------------------------------------------------------- carga diferida (Fase 27) -- */
/** Estado inicial de la grilla de grupo: no se consulta nada hasta elegir al menos un filtro. */
function FiltersRequired({ meta, update }) {
  const units = meta?.management_units ?? [];
  return (
    <div className="iex-empty" role="status">
      <h2 className="iex-empty__title">Elija qué agentes quiere ver</h2>
      <p className="muted">
        Para no cargar la plantilla completa de una sola vez, la grilla se consulta después de aplicar al menos un filtro en el
        panel izquierdo: Management Unit, cuenta, cadena de mando (Director, Manager, Supervisor o Team Manager) o la búsqueda
        por nombre. Los agentes se cargan por páginas.
      </p>
      {units.length > 0 && (
        <div className="iex-empty__units">
          <span className="muted small">Acceso rápido por Management Unit:</span>
          {units.map((g) => (
            <button key={g.code} type="button" className="button button--ghost button--sm" onClick={() => update({ group: g.code })}>
              {g.name} <span className="muted small">({g.agents})</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Paginación de los agentes de la grilla (el servidor evalúa solo la página pedida). */
function GridPager({ paging, shown, update }) {
  const from = (paging.page - 1) * paging.page_size + 1;
  return (
    <nav className="iex-pager" aria-label="Páginas de agentes">
      <span className="muted small">
        Agentes {from}–{from + shown - 1} de {paging.count.toLocaleString("es-SV")}
      </span>
      <div className="iex-pager__controls">
        <button type="button" className="button button--ghost button--sm" disabled={paging.page <= 1} onClick={() => update({ page: String(paging.page - 1) })}>
          ‹ Anterior
        </button>
        <span className="small">
          Página {paging.page} de {paging.pages}
        </span>
        <button type="button" className="button button--ghost button--sm" disabled={paging.page >= paging.pages}
          onClick={() => update({ page: String(paging.page + 1) })}>
          Siguiente ›
        </button>
        <label className="iex__opt">
          <span className="muted small">Por página</span>
          <select value={paging.page_size} onChange={(e) => update({ size: e.target.value === String(DEFAULT_PAGE_SIZE) ? "" : e.target.value })}>
            {(paging.page_sizes ?? PAGE_SIZES).map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      </div>
    </nav>
  );
}

function FilterPanel({ meta, filters, view, employee, update, pinned, onTogglePin }) {
  const leaders = useMemo(() => meta?.leaders ?? [], [meta]);
  const brands = meta?.clients.find((c) => c.code === filters.client)?.brands ?? [];
  const [peek, setPeek] = useState(false);
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  const wide = () => typeof window === "undefined" || window.matchMedia(WIDE).matches;
  const schedule = (value, delay) => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setPeek(value), delay);
  };

  // Desplegables encadenados: cada nivel muestra solo los líderes bajo el nivel superior elegido.
  const options = useMemo(() => {
    const byLevel = {};
    let parents = null;
    LEVEL_PARAMS.forEach(([param, level]) => {
      const list = leaders.filter((l) => l.level === level && (parents === null || parents.has(l.reports_to_id)));
      byLevel[param] = list;
      const chosen = list.find((l) => l.employee_code === filters[param]);
      parents = chosen ? new Set([chosen.id]) : parents === null ? null : new Set(list.map((l) => l.id));
    });
    return byLevel;
  }, [leaders, filters]);

  const setLevel = (param, value) => {
    const idx = LEVEL_PARAMS.findIndex(([p]) => p === param);
    const changes = { [param]: value };
    LEVEL_PARAMS.slice(idx + 1).forEach(([p]) => { changes[p] = ""; }); // los niveles inferiores dependen de este
    update(changes);
  };
  const activeCount = FILTER_KEYS.filter((k) => filters[k]).length;
  const collapsed = !pinned && !peek;
  const cls = ["iex-filters", collapsed && "iex-filters--collapsed", !pinned && peek && "iex-filters--peek"].filter(Boolean).join(" ");

  return (
    <aside
      className={cls}
      aria-label="Filtros"
      onMouseEnter={() => !pinned && wide() && schedule(true, 120)}
      onMouseLeave={() => !pinned && wide() && schedule(false, 280)}
      onFocus={() => !pinned && schedule(true, 0)}
      onBlur={(e) => !pinned && !e.currentTarget.contains(e.relatedTarget) && schedule(false, 0)}
      onKeyDown={(e) => e.key === "Escape" && !pinned && peek && (e.currentTarget.ownerDocument.activeElement?.blur(), setPeek(false))}
    >
      <div className="iex-filters__panel">
        <div className="iex-filters__head">
          <button type="button" className={`sidebar__pin iex-filters__pin${pinned ? " is-pinned" : ""}`} onClick={onTogglePin} aria-pressed={pinned}
            title={pinned ? "Contraer filtros (se abrirán al pasar el cursor)" : "Fijar el panel de filtros"}
            aria-label={pinned ? "Desfijar y contraer los filtros" : "Fijar el panel de filtros expandido"}>
            <PinIcon pinned={pinned} />
          </button>
          <span className="iex-filters__title">
            Filtros {activeCount > 0 && <span className="badge badge--info">{activeCount}</span>}
          </span>
        </div>

        <ul className="iex-filters__rail" aria-hidden={!collapsed}>
          {RAIL.filter((r) => r.id !== "search" || view === "grid").map((r) => {
            const on = r.keys.some((k) => filters[k]);
            return (
              <li key={r.id}>
                <button type="button" tabIndex={collapsed ? 0 : -1} className={`iex-filters__rail-btn${on ? " is-on" : ""}`} title={r.label} aria-label={`${r.label}${on ? " (filtrado)" : ""}`}
                  onClick={() => setPeek(true)}>
                  <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d={r.d} />
                  </svg>
                </button>
              </li>
            );
          })}
        </ul>

        <div className="iex-filters__content">
          {view === "agent" && (
            <div className="iex-filters__section">
              <div className="field">
                <label className="field__label" htmlFor="iex-agent">Agente</label>
                <EmployeeAutocomplete inputId="iex-agent" scope="acd" value={employee} onChange={(code) => update({ employee: code, from: "" })}
                  placeholder="Nombre o ID del agente…" />
              </div>
            </div>
          )}
          <div className="iex-filters__section">
            <h2 className="iex-filters__heading">Management Unit</h2>
            <label className="field">
              <span className="field__label">Grupo de agentes (ACD)</span>
              <select value={filters.group} onChange={(e) => update({ group: e.target.value })}>
                <option value="">Todas</option>
                {(meta?.management_units ?? []).map((g) => (
                  <option key={g.code} value={g.code}>
                    {g.name} ({g.agents})
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="iex-filters__section">
            <h2 className="iex-filters__heading">Cuenta</h2>
            <label className="field">
              <span className="field__label">Cliente</span>
              <select value={filters.client} onChange={(e) => update({ client: e.target.value, brand: "" })}>
                <option value="">Todos</option>
                {(meta?.clients ?? []).map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field__label">Marca</span>
              <select value={filters.brand} disabled={!filters.client || brands.length === 0} onChange={(e) => update({ brand: e.target.value })}>
                <option value="">Todas</option>
                {brands.map((b) => (
                  <option key={b.code} value={b.code}>
                    {b.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="iex-filters__section">
            <h2 className="iex-filters__heading">Cadena de mando (roster)</h2>
            {LEVEL_PARAMS.map(([param, , label]) => (
              <label key={param} className="field">
                <span className="field__label">{label}</span>
                <select value={filters[param]} onChange={(e) => setLevel(param, e.target.value)} disabled={options[param].length === 0 && !filters[param]}>
                  <option value="">{options[param].length ? "Todos" : "Sin registros"}</option>
                  {options[param].map((l) => (
                    <option key={l.id} value={l.employee_code}>
                      {l.full_name}
                    </option>
                  ))}
                </select>
              </label>
            ))}
            {leaders.length === 0 && meta && (
              <p className="muted small">
                Aún no hay líderes. Regístrelos en <Link to="/roster/hierarchy">Roster › Cadena de mando</Link> y asigne el Team Manager de cada agente en su roster.
              </p>
            )}
          </div>
          {view === "grid" && (
            <div className="iex-filters__section">
              <label className="field">
                <span className="field__label">Buscar agente</span>
                <input type="search" key={filters.search} defaultValue={filters.search} placeholder="Nombre o ID"
                  onKeyDown={(e) => e.key === "Enter" && update({ search: e.currentTarget.value.trim() })} />
              </label>
            </div>
          )}
          {activeCount > 0 && (
            <button type="button" className="link-button iex-filters__clear" onClick={() => update(Object.fromEntries(FILTER_KEYS.map((k) => [k, ""])))}>
              Limpiar filtros
            </button>
          )}
        </div>
      </div>
    </aside>
  );
}

/* ---------------------------------------------------------------------------------------- vista 1: grilla -- */
function AuditButton({ label, onClick }) {
  return (
    <button type="button" className="gantt__audit" onClick={(e) => { e.stopPropagation(); onClick(); }} aria-label={label} title={label}>
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M12 8v4l3 2M3.05 11a9 9 0 1 1 .5 4M3 4v7h7" />
      </svg>
    </button>
  );
}

function GroupGrid({ data, date, trackProps, canManage, snapLabel, audit, onAudit, onOpenAgent, onBulkDone, onError }) {
  const [picked, setPicked] = useState(new Set());
  const { win, ppm, interval } = trackProps;
  const rows = data.rows;
  const toggle = (code) =>
    setPicked((s) => {
      const next = new Set(s);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  return (
    <>
      <dl className="kpis iex-kpis">
        <div className="kpi">
          <dt>{data.paging && data.paging.pages > 1 ? "Agentes (esta página)" : "Agentes"}</dt>
          <dd>{data.summary.agents}</dd>
        </div>
        <div className="kpi">
          <dt>Con turno</dt>
          <dd>{data.summary.with_shift}</dd>
        </div>
        <div className="kpi" title="Con turno menos ausencias injustificadas, permisos / licencias e inactivos">
          <dt>Dotación neta</dt>
          <dd>{data.summary.net_staff}</dd>
        </div>
        <div className="kpi">
          <dt>Lateness · ausentes</dt>
          <dd>
            {data.summary.late} · <span className={data.summary.absent ? "adh-pct--bad" : ""}>{data.summary.absent}</span>
          </dd>
        </div>
        <div className="kpi">
          <dt>Permisos · inactivos</dt>
          <dd>
            {data.summary.on_leave} · {data.summary.inactive}
          </dd>
        </div>
        <div className="kpi">
          <dt>Adherencia del grupo</dt>
          <dd className={pctClass(data.summary.adherence_pct)}>{data.summary.evaluated ? fmtPct(data.summary.adherence_pct) : "Día futuro"}</dd>
        </div>
        <div className="kpi">
          <dt>Intervalo · ajuste</dt>
          <dd>
            {data.grid.interval_minutes}′ · {snapLabel}
          </dd>
        </div>
      </dl>
      {rows.length === 0 ? (
        <p className="empty">No hay agentes con esos filtros.</p>
      ) : (
        <div className="gantt" role="grid" aria-label={`Grilla de turnos del ${date}`}>
          <div className="gantt__row gantt__row--head" role="row">
            <div className="gantt__who" role="columnheader">
              Agente
            </div>
            <div role="columnheader">
              <GanttScale win={win} ppm={ppm} interval={interval} />
            </div>
            <div className="gantt__metric" role="columnheader">
              Adh.
            </div>
          </div>
          {rows.map((r) => {
            const isAudited = audit?.employee_code === r.employee_code && audit?.date === date;
            return (
              <div key={r.employee_code} className={`gantt__row${isAudited ? " is-audited" : ""}`} role="row" aria-selected={isAudited}>
                <div className="gantt__who gantt__who--select" role="rowheader" onClick={(e) => !e.target.closest("button, input, a") && onAudit(r)}
                  title="Clic para ver el audit trail de esta línea">
                  {canManage && (
                    <input type="checkbox" checked={picked.has(r.employee_code)} onChange={() => toggle(r.employee_code)} aria-label={`Elegir a ${r.full_name}`}
                      disabled={r.containers.length === 0} />
                  )}
                  <div className="gantt__who-text">
                    <button type="button" className="link-button gantt__name" onClick={() => onOpenAgent(r.employee_code)} title="Ver histórico del agente">
                      {r.full_name}
                    </button>
                    <span className="muted small">
                      {r.employee_code}
                      {r.hierarchy?.TEAM_MANAGER ? ` · TM ${r.hierarchy.TEAM_MANAGER.full_name}` : ""}
                    </span>
                    {ATTENDANCE[r.attendance] && <span className={`badge ${ATTENDANCE[r.attendance].cls} gantt__att`}>{ATTENDANCE[r.attendance].label}</span>}
                    {r.warnings.length > 0 && (
                      <span className="gantt__warn" title={r.warnings.join("\n")}>
                        ⚠ {r.warnings[0]}
                      </span>
                    )}
                  </div>
                  <AuditButton label={`Audit trail de ${r.full_name} el ${date}`} onClick={() => onAudit(r)} />
                </div>
                <div role="gridcell">
                  <GanttTrack {...trackProps} date={date} row={r} />
                </div>
                <div className={`gantt__metric ${pctClass(r.metrics?.adherence_pct)}`} role="gridcell" title={r.metrics ? `En adherencia ${fmtHM(r.metrics.in_adherence)} de ${fmtHM(r.metrics.scheduled)}` : ""}>
                  {r.metrics ? fmtPct(r.metrics.adherence_pct) : "—"}
                </div>
              </div>
            );
          })}
        </div>
      )}
      <GanttLegend />
      {canManage && rows.length > 0 && (
        <BulkSegment activities={data.toolbox} date={date} employees={rows.filter((r) => picked.has(r.employee_code))}
          onDone={(b) => { setPicked(new Set()); onBulkDone(b); }} onError={onError} />
      )}
    </>
  );
}

function GanttLegend() {
  return (
    <ul className="adh-legend gantt-legend" aria-label="Leyenda">
      <li>
        <span className="gantt-legend__box gantt-legend__box--container" /> Pre-contenedor (turno de la AP)
      </li>
      <li>
        <span className="gantt-legend__box gantt-legend__box--segment" /> Segmento (icono cada {PATTERN_MINUTES} min)
      </li>
      <li>
        <span className="gantt-legend__box gantt-legend__box--actual" /> Real (ACD / Web Timer, color del estado)
      </li>
      <li>
        <span className="gantt-legend__box gantt-legend__box--ooa" /> Out of Adherence
      </li>
      <li>
        <span className="gantt-legend__box gantt-legend__box--excess" /> Unpaid Excess Login
      </li>
      <li>
        <span className="gantt-legend__box gantt-legend__box--justified" /> Justificado (AP)
      </li>
      <li>
        <span className="gantt-legend__box gantt-legend__box--locked" /> Lateness / ausencia (bloqueado: solo se reemplaza con AP)
      </li>
    </ul>
  );
}

/* --------------------------------------------------------------------------------------- vista 2: agente -- */
function AgentHistory({ data, trackProps, update, audit, onAudit }) {
  const { ppm, interval } = trackProps;
  const win = { start: data.grid.window_start, end: data.grid.window_end };
  const current = data.hierarchy_history.find((h) => h.effective_end === null) ?? data.hierarchy_history.at(-1);
  const evaluated = data.rows.filter((r) => r.metrics);
  const sched = evaluated.reduce((a, r) => a + r.metrics.scheduled - r.metrics.justified_scheduled, 0);
  const inAdh = evaluated.reduce((a, r) => a + r.metrics.in_adherence, 0);
  const row = (r) => ({ ...r, employee_code: data.employee_code, full_name: data.full_name });
  return (
    <>
      <div className="iex-agent">
        <div>
          <h2 className="iex-agent__name">{data.full_name}</h2>
          <p className="muted small">
            {data.employee_code} · contratación {data.hire_date}
            {data.management_unit ? ` · ${data.management_unit.name}` : " · sin Management Unit"}
            {data.termination_date ? ` · baja ${data.termination_date}` : ""}
          </p>
          {current && (
            <p className="iex-agent__chain small">
              {LEVEL_PARAMS.slice().reverse().map(([, level, label]) => (current[level] ? <span key={level}>{label}: <strong>{current[level].full_name}</strong></span> : null))}
            </p>
          )}
        </div>
        <dl className="kpis iex-kpis">
          <div className="kpi">
            <dt>Días en la página</dt>
            <dd>{data.rows.length}</dd>
          </div>
          <div className="kpi">
            <dt>Adherencia del periodo</dt>
            <dd className={pctClass(sched > 0 ? (inAdh * 100) / sched : null)}>{sched > 0 ? fmtPct((inAdh * 100) / sched) : "—"}</dd>
          </div>
        </dl>
      </div>
      <nav className="iex-pager" aria-label="Páginas del histórico">
        <button type="button" className="button button--ghost button--sm" disabled={!data.prev_from} onClick={() => update({ from: data.prev_from })}>
          ← Anterior
        </button>
        <button type="button" className="button button--ghost button--sm" onClick={() => update({ from: data.hire_date })}>
          Desde la contratación
        </button>
        <button type="button" className="button button--ghost button--sm" onClick={() => update({ from: "" })}>
          Hoy
        </button>
        <span className="muted small">
          {data.from} → {data.to}
        </span>
        <button type="button" className="button button--ghost button--sm" onClick={() => update({ from: data.next_from })}>
          Siguiente →
        </button>
      </nav>
      <div className="gantt gantt--history" role="grid" aria-label={`Histórico de ${data.full_name}`}>
        <div className="gantt__row gantt__row--head" role="row">
          <div className="gantt__who" role="columnheader">
            Fecha
          </div>
          <div role="columnheader">
            <GanttScale win={win} ppm={ppm} interval={interval} />
          </div>
          <div className="gantt__metric" role="columnheader">
            Adh.
          </div>
        </div>
        {data.rows.map((r) => {
          const isAudited = audit?.employee_code === data.employee_code && audit?.date === r.date;
          return (
            <div key={r.date} className={`gantt__row${r.is_today ? " is-today" : ""}${r.containers.length === 0 ? " is-rest" : ""}${isAudited ? " is-audited" : ""}`}
              role="row" aria-selected={isAudited}>
              <div className="gantt__who gantt__who--select" role="rowheader" onClick={(e) => !e.target.closest("button") && onAudit(r.date)}
                title="Clic para ver el audit trail de esta fecha">
                <div className="gantt__who-text">
                  <strong>
                    {WEEKDAYS[r.weekday]} {r.date.slice(8, 10)}/{r.date.slice(5, 7)}
                  </strong>
                  <span className="muted small">
                    {r.containers.length ? r.containers.map((c) => `${hhmm(c.start)}–${hhmm(c.end)}`).join(", ") : "Descanso / sin turno"}
                    {r.is_today ? " · hoy" : ""}
                  </span>
                  {ATTENDANCE[r.attendance] && <span className={`badge ${ATTENDANCE[r.attendance].cls} gantt__att`}>{ATTENDANCE[r.attendance].label}</span>}
                </div>
                <AuditButton label={`Audit trail del ${r.date}`} onClick={() => onAudit(r.date)} />
              </div>
              <div role="gridcell">
                <GanttTrack {...trackProps} win={win} date={r.date} row={row(r)} />
              </div>
              <div className={`gantt__metric ${pctClass(r.metrics?.adherence_pct)}`} role="gridcell"
                title={r.stored ? `Guardado: ${fmtPct(r.stored.adherence_pct)}` : r.is_future ? "Día futuro" : ""}>
                {r.metrics ? fmtPct(r.metrics.adherence_pct) : r.is_future ? "·" : "—"}
              </div>
            </div>
          );
        })}
      </div>
      <GanttLegend />
    </>
  );
}

/* ---------------------------------------------------------------------------------- edición y programación -- */
function BulkSegment({ activities: all, date, employees, onDone, onError }) {
  const activities = all.filter((a) => !a.requires_ap); // las que exigen AP se colocan una por una con su folio
  const usable = activities.filter((a) => !a.is_default);
  const first = usable[0] ?? activities[0];
  const [form, setForm] = useState({ activity: first?.code ?? "", start: "10:00:00", end: addSeconds("10:00:00", first?.default_seconds ?? 900), date_to: "", notes: "" });
  const [busy, setBusy] = useState(false);
  const setActivity = (code) => {
    const a = activities.find((x) => x.code === code);
    setForm((f) => ({ ...f, activity: code, end: a?.default_seconds ? addSeconds(f.start, a.default_seconds) : f.end }));
  };
  const setStart = (start) => {
    const a = activities.find((x) => x.code === form.activity);
    setForm((f) => ({ ...f, start, end: a?.default_seconds && start ? addSeconds(start, a.default_seconds) : f.end }));
  };
  const submit = (e) => {
    e.preventDefault();
    if (employees.length === 0) return;
    setBusy(true);
    adhApi
      .bulkSegments({ activity: form.activity, start: form.start, end: form.end, notes: form.notes, employee_codes: employees.map((x) => x.employee_code),
        date_from: date, date_to: form.date_to || date })
      .then(onDone)
      .catch(onError)
      .finally(() => setBusy(false));
  };
  return (
    <details className="form-section iex-bulk">
      <summary className="form-section__title">Programación masiva (varios agentes / fechas)</summary>
      <form onSubmit={submit}>
        <p className="form-section__desc">
          {employees.length === 0 ? "Marque los agentes en la grilla." : `Para ${employees.length} agente(s): ${employees.map((x) => x.full_name).join(", ")}.`}
        </p>
        <div className="adh-new__grid">
          <label className="field">
            <span className="field__label">Actividad</span>
            <select value={form.activity} onChange={(e) => setActivity(e.target.value)}>
              {groupByCategory(activities).map((g) => (
                <optgroup key={g.code || "none"} label={g.name}>
                  {g.items.map((a) => (
                    <option key={a.code} value={a.code}>
                      {a.name}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field__label">Inicio (HH:MM:SS)</span>
            <input type="time" step="1" required value={form.start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label className="field">
            <span className="field__label">Fin (HH:MM:SS)</span>
            <input type="time" step="1" required value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} />
          </label>
          <label className="field">
            <span className="field__label">Repetir hasta (opcional)</span>
            <input type="date" min={date} value={form.date_to} onChange={(e) => setForm({ ...form, date_to: e.target.value })} />
          </label>
          <label className="field">
            <span className="field__label">Notas</span>
            <input maxLength={200} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          </label>
        </div>
        <div className="form-actions form-actions--start">
          <button type="submit" className="button button--sm" disabled={busy || employees.length === 0}>
            {busy ? "Programando…" : "Programar"}
          </button>
          <span className="muted small">
            Los días sin turno se omiten; lo que salga del turno, se traslape o exija AP (cambio mayor) se rechaza con su motivo.
          </span>
        </div>
      </form>
    </details>
  );
}

function GridSettings({ grid, group, canManage, onSaved, onError }) {
  const [open, setOpen] = useState(false);
  const pick = (g) => ({ interval_minutes: g.interval_minutes, snap_seconds: g.snap_seconds, margin_hours: g.margin_hours,
    lateness_grace_seconds: g.lateness_grace_seconds ?? 60, ap_required: durationText(g.ap_required_seconds ?? 14400) });
  const [form, setForm] = useState(() => pick(grid));
  const [busy, setBusy] = useState(false);
  useEffect(() => setForm(pick(grid)), [grid]);
  const save = (e) => {
    e.preventDefault();
    const apSeconds = form.ap_required.trim() === "" ? 0 : parseDuration(form.ap_required);
    if (apSeconds === null) {
      onError(new Error("Duración que exige AP: HH:MM:SS (vacío o 00:00:00 = solo el día completo)."));
      return;
    }
    setBusy(true);
    const { ap_required: _ap, ...rest } = form;
    adhApi
      .saveGridSettings({ ...rest, ap_required_seconds: apSeconds, group })
      .then((b) => {
        setOpen(false);
        onSaved(b);
      })
      .catch(onError)
      .finally(() => setBusy(false));
  };
  return (
    <div className="iex-settings">
      <button type="button" className="button button--ghost button--sm" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        Grilla: {grid.interval_minutes}′
      </button>
      {open && (
        <form className="iex-settings__panel" onSubmit={save}>
          <p className="small muted">{group ? `Management Unit ${group}` : "Configuración global"}</p>
          <label className="field">
            <span className="field__label">Intervalo</span>
            <select value={form.interval_minutes} disabled={!canManage} onChange={(e) => setForm({ ...form, interval_minutes: Number(e.target.value) })}>
              {grid.intervals.map((v) => (
                <option key={v} value={v}>
                  {v} min
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field__label">Ajuste al soltar</span>
            <select value={form.snap_seconds} disabled={!canManage} onChange={(e) => setForm({ ...form, snap_seconds: Number(e.target.value) })}>
              {(grid.snaps ?? []).map((s) => (
                <option key={s.value} value={s.value} disabled={s.value > form.interval_minutes * 60}>
                  {s.label}
                </option>
              ))}
            </select>
            <FieldHint>1 s = sin redondeo: la hora queda donde se suelta.</FieldHint>
          </label>
          <label className="field">
            <span className="field__label">Margen alrededor del turno (h)</span>
            <input type="number" min={0} max={6} value={form.margin_hours} disabled={!canManage} onChange={(e) => setForm({ ...form, margin_hours: Number(e.target.value) })} />
          </label>
          <label className="field">
            <span className="field__label">Tolerancia de llegada (s)</span>
            <input type="number" min={0} max={3600} value={form.lateness_grace_seconds} disabled={!canManage}
              onChange={(e) => setForm({ ...form, lateness_grace_seconds: Number(e.target.value) })} />
            <FieldHint>Después de la entrada + tolerancia, el inicio de sesión ACD inserta el Lateness.</FieldHint>
          </label>
          <label className="field">
            <span className="field__label">Cambio mayor que exige AP (HH:MM:SS)</span>
            <input value={form.ap_required} disabled={!canManage} placeholder="04:00:00" onChange={(e) => setForm({ ...form, ap_required: e.target.value })} />
            <FieldHint>El día completo y las actividades marcadas siempre exigen AP.</FieldHint>
          </label>
          {canManage && (
            <button type="submit" className="button button--sm" disabled={busy}>
              Guardar
            </button>
          )}
        </form>
      )}
    </div>
  );
}

