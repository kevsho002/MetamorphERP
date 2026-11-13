const DOW = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const MONTH_FMT = new Intl.DateTimeFormat("es-SV", { month: "long" });
export const KIND_COLORS = { NATIONAL: "#2f7dd1", LOCAL: "#0f9b8e", COMPANY: "#9333ea" };

const iso = (y, m, d) => `${y}-${String(m + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
export const monthName = (m) => MONTH_FMT.format(new Date(2026, m, 1));

/** Celdas de un mes (semana de lunes a domingo) con los días de relleno del mes anterior y el siguiente. */
function cells(year, month) {
  const first = new Date(year, month, 1);
  const offset = (first.getDay() + 6) % 7;
  const start = new Date(year, month, 1 - offset);
  const total = Math.ceil((offset + new Date(year, month + 1, 0).getDate()) / 7) * 7;
  return Array.from({ length: total }, (_, i) => {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
    return { date: iso(d.getFullYear(), d.getMonth(), d.getDate()), day: d.getDate(), inMonth: d.getMonth() === month, weekday: (d.getDay() + 6) % 7 };
  });
}

/**
 * Fase 23 — Calendario interactivo de feriados: vista de mes (clic en un día libre para agregar, clic en un feriado
 * para editar) y vista de año (12 meses; clic en un mes para abrirlo).
 */
export function MonthGrid({ year, month, byDate, today, canManage, onAdd, onOpen }) {
  return (
    <div className="holcal__month" role="grid" aria-label={`${monthName(month)} ${year}`}>
      {DOW.map((d) => (
        <div key={d} className="holcal__dow" role="columnheader">
          {d}
        </div>
      ))}
      {cells(year, month).map((c) => {
        const hols = byDate[c.date] ?? [];
        const canAdd = canManage && c.inMonth && hols.length === 0;
        const cls = ["holcal__day", c.inMonth ? "" : "is-out", c.weekday >= 5 ? "is-weekend" : "", c.date === today ? "is-today" : "",
          canAdd ? "can-add" : ""].filter(Boolean).join(" ");
        return (
          <div key={c.date} role="gridcell" className={cls} tabIndex={canAdd ? 0 : -1}
            aria-label={`${c.day} ${hols.map((h) => h.name).join(", ")}`.trim()}
            title={canAdd ? "Agregar un feriado en este día" : undefined}
            onClick={() => canAdd && onAdd(c.date)} onKeyDown={(e) => canAdd && (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onAdd(c.date))}>
            <span className="holcal__num">{c.day}</span>
            {hols.map((h) => (
              <button key={h.id} type="button" className={`holcal__chip${h.is_active ? "" : " is-inactive"}`} style={{ "--chip": KIND_COLORS[h.kind] }}
                onClick={(e) => { e.stopPropagation(); onOpen(h); }} title={`${h.name} · ${h.kind_label} · recargo ${Number(h.premium_percent)} %`}>
                {h.name}
                <span className="holcal__chip-meta">
                  {h.kind_label}
                  {h.segments ? ` · ${h.segments} laborado(s)` : ""}
                </span>
              </button>
            ))}
          </div>
        );
      })}
    </div>
  );
}

export function YearGrid({ year, byDate, today, onMonth, onOpen }) {
  return (
    <div className="holcal__year">
      {Array.from({ length: 12 }, (_, m) => {
        const count = Object.keys(byDate).filter((k) => k.startsWith(iso(year, m, 1).slice(0, 7))).length;
        return (
          <section key={m} className="holcal__mini">
            <h3>
              <button type="button" onClick={() => onMonth(m)}>
                {monthName(m)}
              </button>{" "}
              <span className="muted small">{count ? `· ${count} feriado(s)` : ""}</span>
            </h3>
            <div className="holcal__mini-grid">
              {DOW.map((d) => (
                <span key={d} className="is-dow">
                  {d[0]}
                </span>
              ))}
              {cells(year, m).map((c) => {
                if (!c.inMonth) return <span key={c.date} />;
                const h = (byDate[c.date] ?? [])[0];
                return h ? (
                  <button key={c.date} type="button" className={`is-holiday${c.date === today ? " is-today" : ""}`}
                    style={{ "--chip": KIND_COLORS[h.kind], opacity: h.is_active ? 1 : 0.5 }} title={h.name} onClick={() => onOpen(h)}>
                    {c.day}
                  </button>
                ) : (
                  <span key={c.date} className={c.date === today ? "is-today" : ""}>
                    {c.day}
                  </span>
                );
              })}
            </div>
          </section>
        );
      })}
    </div>
  );
}
