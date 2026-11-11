import { hhmm, wallMs } from "../api.js";

/**
 * Línea de tiempo horizontal (hora local de la operación). `lanes` = [{ key, label, blocks: [{ key, start, end, color,
 * label, title, onClick, selected, variant }] }]. El rango [start, end) se marca por horas.
 */
export default function Timeline({ start, end, lanes, compact = false }) {
  const t0 = wallMs(start);
  const t1 = wallMs(end);
  const span = Math.max(1, t1 - t0);
  const pct = (ms) => `${Math.min(100, Math.max(0, ((ms - t0) / span) * 100))}%`;
  const hours = [];
  for (let t = Math.ceil(t0 / 3_600_000) * 3_600_000; t <= t1; t += 3_600_000) hours.push(t);
  const step = hours.length > 14 ? 2 : 1;

  return (
    <div className={`timeline${compact ? " timeline--compact" : ""}`}>
      {!compact && (
        <div className="timeline__scale" aria-hidden="true">
          {hours.map((t, i) =>
            i % step === 0 ? (
              <span key={t} className="timeline__tick" style={{ left: pct(t) }}>
                {String(new Date(t).getUTCHours()).padStart(2, "0")}
              </span>
            ) : null,
          )}
        </div>
      )}
      {lanes.map((lane) => (
        <div key={lane.key} className="timeline__lane">
          {lane.label && <span className="timeline__lane-label">{lane.label}</span>}
          <div className="timeline__track">
            {hours.map((t) => (
              <span key={t} className="timeline__grid" style={{ left: pct(t) }} aria-hidden="true" />
            ))}
            {lane.blocks.map((b) => {
              const left = pct(wallMs(b.start));
              const width = `calc(${pct(wallMs(b.end))} - ${left})`;
              const title = b.title ?? `${b.label} · ${hhmm(b.start)}–${hhmm(b.end)}`;
              const style = { left, width, "--block-color": b.color };
              const cls = `timeline__block${b.variant ? ` timeline__block--${b.variant}` : ""}${b.selected ? " is-selected" : ""}`;
              return b.onClick ? (
                <button key={b.key} type="button" className={cls} style={style} title={title} aria-label={title} onClick={b.onClick}>
                  <span className="timeline__text">{b.label}</span>
                </button>
              ) : (
                <span key={b.key} className={cls} style={style} title={title}>
                  <span className="timeline__text">{b.label}</span>
                </span>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
