import { useState } from "react";
import { clockLabel, fmtDuration, hhmm, minutesFrom, minutesToHM } from "../api.js";
import ActivityIcon from "./ActivityIcon.jsx";

/** Cada cuántos minutos se repite el icono de la actividad dentro de un segmento (Fase 18). */
export const PATTERN_MINUTES = 15;

/**
 * Grilla temporal horizontal estilo IEX (Fase 17). Todas las filas comparten la ventana `win` = { start, end } en
 * minutos desde las 00:00 de la fecha de cada fila (un turno nocturno puede pasar de 1440) y la escala `ppm`
 * (píxeles por minuto). El intervalo marca las franjas finas; las horas, las gruesas.
 */
export function GanttScale({ win, ppm, interval }) {
  const ticks = [];
  for (let m = Math.ceil(win.start / interval) * interval; m <= win.end; m += interval) ticks.push(m);
  const labelEvery = ppm * 60 >= 70 ? 60 : 120;
  return (
    <div className="gantt__scale" style={{ width: (win.end - win.start) * ppm }} aria-hidden="true">
      {ticks.map((m) => (
        <span key={m} className={`gantt__tick${m % 60 === 0 ? " gantt__tick--hour" : ""}${m === win.start ? " gantt__tick--first" : ""}`}
          style={{ left: (m - win.start) * ppm }}>
          {m % labelEvery === 0 && <span className="gantt__tick-label">{minutesToHM(m)}</span>}
          {m % 60 !== 0 && ppm * interval >= 28 && <span className="gantt__tick-minor">{String(m % 60).padStart(2, "0")}</span>}
        </span>
      ))}
    </div>
  );
}

/** Patrón del segmento: el icono de la actividad repetido cada 15 minutos desde su inicio (línea compacta). */
function SegmentPattern({ icon, minutes, ppm }) {
  const step = PATTERN_MINUTES * ppm;
  const width = minutes * ppm;
  if (width < 12) return null;
  const count = Math.max(1, Math.floor(width / step) + (width % step >= 12 ? 1 : 0));
  return (
    <span className="gantt__seg-pattern" aria-hidden="true">
      {Array.from({ length: Math.min(count, 200) }, (_, k) => (
        <span key={k} className="gantt__seg-mark" style={{ left: k * step }}>
          <ActivityIcon name={icon} size={10} />
        </span>
      ))}
    </span>
  );
}

/**
 * Pista de un agente en una fecha: pre-contenedor (turno de la AP) en gris, segmentos como línea delgada de color con
 * el patrón del icono, franja de la actividad real del ACD y marcas de desviación. Acepta soltar actividades de la
 * barra de segmentos y mover segmentos; las horas se ajustan al «snap» en SEGUNDOS de la grilla (Fase 18).
 *
 * `drag` es una ref compartida con la información de lo que se arrastra: { kind: "activity", activity } o
 * { kind: "segment", segment, grab, date }. `armed` = actividad elegida con clic (alternativa táctil / teclado).
 */
export default function GanttTrack({
  date, win, ppm, interval, snapSeconds, row, statusColors, canManage, drag, armed, selectedId, onDropActivity, onMoveSegment,
  onSelectSegment, onSelectContainer, onPlaceArmed, defaultName,
}) {
  const [ghost, setGhost] = useState(null);
  const width = (win.end - win.start) * ppm;
  const x = (iso) => (minutesFrom(date, iso) - win.start) * ppm;
  const w = (a, b) => Math.max(2, (minutesFrom(date, b) - minutesFrom(date, a)) * ppm);

  const minuteAt = (clientX, el) => {
    const rect = el.getBoundingClientRect();
    return win.start + (clientX - rect.left) / ppm;
  };
  const snap = Math.max(1, snapSeconds || 300);
  const snapTo = (m) => (Math.round((m * 60) / snap) * snap) / 60;

  const info = () => drag.current;
  const durationOf = (d) => (d.kind === "activity" ? (d.activity.default_seconds || 1800) / 60 : d.segment.seconds / 60);

  const onDragOver = (e) => {
    const d = info();
    if (!canManage || !d) return;
    if (d.kind === "segment" && (d.date !== date || d.segment.employee_code !== row.employee_code)) return; // otro agente / día
    e.preventDefault();
    e.dataTransfer.dropEffect = d.kind === "activity" ? "copy" : "move";
    const start = snapTo(minuteAt(e.clientX, e.currentTarget) - (d.grab ?? 0));
    const dur = durationOf(d);
    if (!ghost || ghost.start !== start || ghost.dur !== dur) {
      setGhost({ start, dur, color: d.kind === "activity" ? d.activity.color : d.segment.color, label: d.kind === "activity" ? d.activity.name : d.segment.activity_name });
    }
  };
  const onDrop = (e) => {
    const d = info();
    setGhost(null);
    if (!canManage || !d) return;
    e.preventDefault();
    const start = snapTo(minuteAt(e.clientX, e.currentTarget) - (d.grab ?? 0));
    if (d.kind === "activity") onDropActivity(row, date, start, d.activity);
    else if (d.date === date) onMoveSegment(row, date, start, d.segment);
  };
  const onClick = (e) => {
    if (!armed || !canManage || e.target.closest(".gantt__seg")) return;
    onPlaceArmed(row, date, snapTo(minuteAt(e.clientX, e.currentTarget)), armed);
  };

  const segments = row.plan.filter((b) => b.source === "SEGMENT");
  return (
    <div
      className={`gantt__track${armed && canManage ? " gantt__track--armed" : ""}`}
      style={{ width, "--interval-px": `${interval * ppm}px`, "--hour-px": `${60 * ppm}px`, "--offset-px": `${(-(win.start % 60) * ppm) || 0}px` }}
      onDragOver={onDragOver}
      onDragLeave={(e) => !e.currentTarget.contains(e.relatedTarget) && setGhost(null)}
      onDrop={onDrop}
      onClick={onClick}
    >
      {row.containers.map((c, i) => {
        // Fase 19: clic en el pre-contenedor = ventana flotante del día (salvo que haya una actividad elegida para insertar).
        const open = (e) => {
          if (armed && canManage) return;
          e.stopPropagation();
          onSelectContainer?.(row, date);
        };
        return (
          <span key={`c${i}`} className={`gantt__container${onSelectContainer ? " is-clickable" : ""}`} style={{ left: x(c.start), width: w(c.start, c.end) }}
            title={`Pre-contenedor (AP de horario): ${hhmm(c.start)}–${hhmm(c.end)} · resto del turno = ${defaultName}. Clic: detalle del día`}
            role={onSelectContainer ? "button" : undefined} tabIndex={onSelectContainer ? 0 : undefined} onClick={open}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), open(e))}>
            <span className="gantt__container-label">
              {hhmm(c.start)}–{hhmm(c.end)} · {defaultName}
            </span>
          </span>
        );
      })}
      {(row.justifications ?? []).map((j, i) => (
        <span key={`j${i}`} className="gantt__justified" style={{ left: x(j.start), width: w(j.start, j.end) }}
          title={`Justificado con la AP ${j.folio}: ${hhmm(j.start)}–${hhmm(j.end)}`} />
      ))}
      {segments.map((b) => {
        const seg = row.segments.find((s) => s.id === b.segment_id);
        const locked = Boolean(seg?.is_locked);
        const title = `${b.activity_name} · ${hhmm(b.start)}–${hhmm(b.end)} (${fmtDuration(b.seconds)})${seg?.notes ? ` · ${seg.notes}` : ""}${
          seg?.folio ? ` · AP ${seg.folio}` : ""}${locked ? " · bloqueado: solo se reemplaza con AP" : ""}`;
        return (
          <button
            key={b.segment_id}
            type="button"
            className={`gantt__seg${selectedId === b.segment_id ? " is-selected" : ""}${locked ? " is-locked" : ""}${b.system_role ? " is-system" : ""}`}
            style={{ left: x(b.start), width: w(b.start, b.end), "--seg-color": b.color }}
            title={title}
            aria-label={title}
            draggable={canManage && !locked}
            onDragStart={(e) => {
              const rect = e.currentTarget.getBoundingClientRect();
              drag.current = { kind: "segment", segment: seg, date, grab: (e.clientX - rect.left) / ppm };
              e.dataTransfer.effectAllowed = "move";
              e.dataTransfer.setData("text/plain", `segment:${b.segment_id}`);
            }}
            onDragEnd={() => {
              drag.current = null;
              setGhost(null);
            }}
            onClick={(e) => {
              e.stopPropagation();
              if (seg) onSelectSegment(seg, row, date);
            }}
          >
            <SegmentPattern icon={seg?.icon ?? b.icon} minutes={b.seconds / 60} ppm={ppm} />
          </button>
        );
      })}
      {ghost && (
        <span className="gantt__ghost" style={{ left: (ghost.start - win.start) * ppm, width: ghost.dur * ppm, "--seg-color": ghost.color }}>
          {clockLabel(ghost.start)}–{clockLabel(ghost.start + ghost.dur)} {ghost.label}
        </span>
      )}
      {(row.actual ?? []).map((a, i) => (
        <span key={`a${i}`} className="gantt__actual" style={{ left: x(a.start), width: w(a.start, a.end), background: statusColors[a.primary] ?? "#64748b" }}
          title={`Real (ACD): ${a.label} · ${hhmm(a.start)}–${hhmm(a.end)}`} />
      ))}
      {(row.deviations ?? []).map((d, i) => (
        <span key={`d${i}`} className={`gantt__dev gantt__dev--${d.kind === "UNPAID_EXCESS_LOGIN" ? "excess" : "ooa"}`}
          style={{ left: x(d.start), width: w(d.start, d.end) }}
          title={`${d.kind_label} · ${hhmm(d.start)}–${hhmm(d.end)} (${fmtDuration(d.seconds)}) · programado: ${d.expected_name ?? "fuera del turno"} · real: ${d.actual}`} />
      ))}
    </div>
  );
}
