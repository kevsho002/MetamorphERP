import { useTimeFormat } from "../../../app/timeFormat.js";
import { Fragment, useEffect, useState } from "react";
import { DAY_KEYS, DAY_LABELS, fmtMinutes, grossMinutes } from "../../scheduling/lib/time.js";
import { actionsApi } from "../api.js";

export const LUNCH_ALLOCATIONS = [
  { value: "PROPORTIONAL", label: "Proporcional a las horas de cada fecha" },
  { value: "START_DAY", label: "En la fecha de inicio del turno" },
  { value: "LONGEST_SEGMENT", label: "En la fecha con más horas" },
];

const MAX_BLOCKS = 4;
const NEW_DAY = () => [{ start: "08:00", end: "17:00", lunch_minutes: 60 }];
const NEW_BLOCK = () => ({ start: "13:00", end: "17:00", lunch_minutes: 0 });

/** Bloques de un día: acepta un objeto (un bloque, formato anterior), una lista o null (descanso). */
export function blocksOf(day) {
  if (!day) return [];
  return Array.isArray(day) ? day : [day];
}

/** Horario inicial: lunes a viernes 08:00–17:00 con 60 min de almuerzo; sábado y domingo de descanso. */
export const defaultSchedule = () => ({
  days: Object.fromEntries(DAY_KEYS.map((k) => [k, ["sat", "sun"].includes(k) ? null : NEW_DAY()])),
  lunch_allocation: "PROPORTIONAL",
});

/** Solo lo que captura el usuario (las horas diurnas / nocturnas las calcula el servidor). */
export function scheduleInput(value) {
  return {
    days: Object.fromEntries(
      DAY_KEYS.map((k) => {
        const blocks = blocksOf(value?.days?.[k]);
        return [k, blocks.length ? blocks.map((b) => ({ start: b.start, end: b.end, lunch_minutes: Number(b.lunch_minutes || 0) })) : null];
      }),
    ),
    lunch_allocation: value?.lunch_allocation ?? "PROPORTIONAL",
  };
}

/** Horario editable a partir del resumen de un horario guardado (summary del backend). */
export function scheduleFromSummary(summary) {
  if (!summary) return defaultSchedule();
  return {
    days: Object.fromEntries(
      summary.days.map((d) => [
        d.day,
        d.rest ? null : (d.blocks?.length ? d.blocks : [d]).map((b) => ({ start: b.start, end: b.end, lunch_minutes: b.lunch_minutes })),
      ]),
    ),
    lunch_allocation: summary.lunch_allocation ?? "PROPORTIONAL",
  };
}

/**
 * Horario ATÓMICO por día (formato de Acción de Personal): cada día puede tener uno o varios BLOQUES (turno partido),
 * con hora de inicio, hora de fin y almuerzo OPCIONAL. Las horas DIURNAS y NOCTURNAS las calcula el servidor con la
 * regla de nocturnidad del país vigente a la fecha efectiva; las reglas de almuerzo del país indican desde cuántas
 * horas continuas corresponde almuerzo (advertencia u obligatorio).
 */
export default function WeeklyScheduleEditor({ value, onChange, country, employeeCode, effectiveDate, errors = [], disabled, idPrefix = "schedule" }) {
  useTimeFormat(); // Fase 21: re-render al cambiar HH:MM:SS / horas decimales
  const days = value?.days ?? {};
  const [preview, setPreview] = useState({ data: null, error: null });
  const setBlocks = (key, blocks) => onChange({ ...value, days: { ...days, [key]: blocks && blocks.length ? blocks : null } });
  const setBlock = (key, index, patch) => setBlocks(key, blocksOf(days[key]).map((b, i) => (i === index ? { ...b, ...patch } : b)));
  const copyMonday = () => {
    const mon = blocksOf(days.mon);
    if (!mon.length) return;
    onChange({ ...value, days: { ...days, ...Object.fromEntries(["tue", "wed", "thu", "fri"].map((k) => [k, mon.map((b) => ({ ...b }))])) } });
  };
  const errorFor = (key) =>
    errors
      .filter((e) => String(e.field ?? "").includes(`.${key}`))
      .map((e) => e.message)
      .join(" ");
  const general = errors.filter((e) => !DAY_KEYS.some((k) => String(e.field ?? "").includes(`.${k}`)));

  useEffect(() => {
    if (!country && !employeeCode) return undefined;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      actionsApi
        .schedulePreview({ schedule: scheduleInput(value), country, employee_code: employeeCode, effective_date: effectiveDate }, { signal: controller.signal })
        .then((data) => setPreview({ data, error: null }))
        .catch((err) => err.name !== "AbortError" && setPreview({ data: null, error: err.body?.errors ?? [{ message: err.message }] }));
    }, 350);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [value, country, employeeCode, effectiveDate]);

  const calc = Object.fromEntries((preview.data?.summary?.days ?? []).map((d) => [d.day, d]));
  const summary = preview.data?.summary;
  const warnings = preview.data?.warnings ?? [];
  const lunchRules = preview.data?.lunch_rules ?? [];

  return (
    <div className="shift-editor">
      <div className="table-wrap">
        <table className="table shift-grid">
          <thead>
            <tr>
              <th scope="col">Día</th>
              <th scope="col">Labora</th>
              <th scope="col">Hora de inicio</th>
              <th scope="col">Hora de fin</th>
              <th scope="col">Almuerzo (min)</th>
              <th scope="col">Horas diurnas</th>
              <th scope="col">Horas nocturnas</th>
              <th scope="col">Total</th>
              <th scope="col">
                <span className="sr-only">Bloques</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {DAY_KEYS.map((key) => {
              const blocks = blocksOf(days[key]);
              const c = calc[key];
              const err = errorFor(key);
              const rows = Math.max(1, blocks.length) + (err ? 1 : 0);
              const head = (
                <>
                  <th scope="row" rowSpan={rows}>
                    {DAY_LABELS[key]}
                    {blocks.length > 1 && <span className="badge badge--info shift-grid__badge">Partido</span>}
                  </th>
                  <td rowSpan={rows}>
                    <input
                      type="checkbox"
                      name={`${idPrefix}.${key}`}
                      aria-label={`${DAY_LABELS[key]}: día laboral`}
                      checked={blocks.length > 0}
                      disabled={disabled}
                      onChange={(e) => setBlocks(key, e.target.checked ? NEW_DAY() : null)}
                    />
                  </td>
                </>
              );
              return (
                <Fragment key={key}>
                  {blocks.length === 0 ? (
                    <tr>
                      {head}
                      <td colSpan={7} className="muted">
                        Descanso
                      </td>
                    </tr>
                  ) : (
                    blocks.map((b, i) => {
                      const gross = grossMinutes(b.start, b.end);
                      const cb = c?.blocks?.[i];
                      const label = `${DAY_LABELS[key]}${blocks.length > 1 ? ` (bloque ${i + 1})` : ""}`;
                      return (
                        <tr key={`${key}-${i}`} className={err ? "shift-grid__row--error" : undefined}>
                          {i === 0 && head}
                          <td>
                            <input type="time" value={b.start} disabled={disabled} aria-label={`${label}: hora de inicio`} onChange={(e) => setBlock(key, i, { start: e.target.value })} required />
                          </td>
                          <td>
                            <input type="time" value={b.end} disabled={disabled} aria-label={`${label}: hora de fin`} onChange={(e) => setBlock(key, i, { end: e.target.value })} required />
                            {gross !== null && b.end <= b.start && <span className="badge badge--info shift-grid__badge">+1 día</span>}
                          </td>
                          <td>
                            <input
                              type="number"
                              min={0}
                              max={240}
                              step={5}
                              value={b.lunch_minutes ?? 0}
                              disabled={disabled}
                              aria-label={`${label}: minutos de almuerzo (opcional)`}
                              onChange={(e) => setBlock(key, i, { lunch_minutes: e.target.value === "" ? 0 : Number(e.target.value) })}
                            />
                          </td>
                          <td>{cb ? fmtMinutes(cb.day_minutes) : "—"}</td>
                          <td>{cb ? fmtMinutes(cb.night_minutes) : "—"}</td>
                          <td>
                            <strong>{cb ? fmtMinutes(cb.net_minutes) : gross !== null ? fmtMinutes(gross - Number(b.lunch_minutes || 0)) : "—"}</strong>
                          </td>
                          <td className="shift-grid__tools">
                            {blocks.length > 1 && (
                              <button type="button" className="link-button" disabled={disabled} aria-label={`Quitar ${label}`} onClick={() => setBlocks(key, blocks.filter((_, j) => j !== i))}>
                                Quitar
                              </button>
                            )}
                            {i === blocks.length - 1 && blocks.length < MAX_BLOCKS && (
                              <button type="button" className="link-button" disabled={disabled} onClick={() => setBlocks(key, [...blocks, NEW_BLOCK()])}>
                                + bloque
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })
                  )}
                  {err && (
                    <tr className="shift-grid__row--error">
                      <td colSpan={7} className="shift-grid__error" role="alert">
                        {err}
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
          {summary && (
            <tfoot>
              <tr>
                <th scope="row" colSpan={5}>
                  Total semanal
                </th>
                <td>{fmtMinutes(summary.weekly_day_minutes)}</td>
                <td>{fmtMinutes(summary.weekly_night_minutes)}</td>
                <td>
                  <strong>{fmtMinutes(summary.weekly_minutes)}</strong>
                </td>
                <td />
              </tr>
            </tfoot>
          )}
        </table>
      </div>
      <div className="form-actions form-actions--start">
        <button type="button" className="button button--ghost button--sm" onClick={copyMonday} disabled={disabled || !blocksOf(days.mon).length}>
          Copiar el lunes a martes–viernes
        </button>
        <label className="field">
          <span className="field__label">Almuerzo en jornadas que cruzan la medianoche</span>
          <select value={value?.lunch_allocation ?? "PROPORTIONAL"} disabled={disabled} onChange={(e) => onChange({ ...value, lunch_allocation: e.target.value })}>
            {LUNCH_ALLOCATIONS.map((a) => (
              <option key={a.value} value={a.value}>
                {a.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="muted small">
        Turno partido: use «+ bloque». El almuerzo es opcional y solo una duración (su hora la programa WFM).{" "}
        {lunchRules.length > 0 &&
          `Regla de almuerzo del país: ${lunchRules
            .map((r) => `jornada continua ≥ ${fmtMinutes(r.min_block_minutes)} → ${r.lunch_minutes} min (${r.enforcement_label.toLowerCase()})`)
            .join("; ")}. `}
        {preview.data?.night_rule
          ? `Nocturnidad aplicada: ${preview.data.night_rule.start}–${preview.data.night_rule.end} (+${preview.data.night_rule.surcharge_percent} %).`
          : preview.data
            ? "El país no tiene regla de nocturnidad vigente: todas las horas se cuentan como diurnas."
            : ""}
      </p>
      {warnings.length > 0 && (
        <ul className="msg-list msg-list--warn">
          {warnings.map((w, i) => (
            <li key={i}>{w.message}</li>
          ))}
        </ul>
      )}
      {[...general, ...(preview.error && !errors.length ? preview.error : [])].length > 0 && (
        <ul className="msg-list msg-list--error">
          {[...general, ...(preview.error && !errors.length ? preview.error : [])].map((e, i) => (
            <li key={i}>{e.message}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Tabla de solo lectura de un horario guardado (summary del backend), un renglón por bloque. */
export function ScheduleTable({ summary, caption }) {
  if (!summary) return null;
  return (
    <div className="table-wrap">
      <table className="table shift-grid">
        {caption && <caption className="muted small">{caption}</caption>}
        <thead>
          <tr>
            <th scope="col">Día</th>
            <th scope="col">Inicio</th>
            <th scope="col">Fin</th>
            <th scope="col">Almuerzo</th>
            <th scope="col">Diurnas</th>
            <th scope="col">Nocturnas</th>
            <th scope="col">Total</th>
          </tr>
        </thead>
        <tbody>
          {summary.days.map((d) => {
            if (d.rest) {
              return (
                <tr key={d.day}>
                  <th scope="row">{DAY_LABELS[d.day]}</th>
                  <td colSpan={6} className="muted">
                    Descanso
                  </td>
                </tr>
              );
            }
            const blocks = d.blocks?.length ? d.blocks : [d];
            return blocks.map((b, i) => (
              <tr key={`${d.day}-${i}`}>
                {i === 0 && (
                  <th scope="row" rowSpan={blocks.length}>
                    {DAY_LABELS[d.day]}
                    {blocks.length > 1 && <span className="badge badge--info shift-grid__badge">Partido</span>}
                  </th>
                )}
                <td>{b.start}</td>
                <td>
                  {b.end} {b.crosses_midnight && <span className="badge badge--info">+1 día</span>}
                </td>
                <td>{b.lunch_minutes ? `${b.lunch_minutes} min` : "—"}</td>
                <td>{fmtMinutes(b.day_minutes)}</td>
                <td>{fmtMinutes(b.night_minutes)}</td>
                <td>
                  <strong>{fmtMinutes(b.net_minutes)}</strong>
                </td>
              </tr>
            ));
          })}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row" colSpan={4}>
              Total semanal
            </th>
            <td>{fmtMinutes(summary.weekly_day_minutes)}</td>
            <td>{fmtMinutes(summary.weekly_night_minutes)}</td>
            <td>
              <strong>{fmtMinutes(summary.weekly_minutes)}</strong>
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
