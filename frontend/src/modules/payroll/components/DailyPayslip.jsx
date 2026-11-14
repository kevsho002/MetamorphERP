import { useState } from "react";
import { formatHours, useTimeFormat } from "../../../app/timeFormat.js";
import { formatDate, formatMoney } from "../../hcm/lib/format.js";

const TONE = {
  WORKED: "ok", PARTIAL: "warn", HOLIDAY: "info", VACATION: "info", ABSENCE: "error", UNPAID: "warn", REST: "muted",
  SUSPENDED: "error", OUTSIDE: "muted",
};
const isZero = (v) => !v || Number(v) === 0;

/**
 * Fase 25 — Boleta desglosada por DÍA: cada fecha de los cortes internos de asistencia con sus horas (programadas,
 * pagables, nocturnas) y su traducción exacta a dinero (salario por horas, vacaciones, nocturnidad, recargo de feriado
 * y séptimo día). La suma de los días es igual, al centavo, a las líneas por tiempo de la boleta.
 */
export default function DailyPayslip({ daily, currency }) {
  useTimeFormat();
  const [open, setOpen] = useState(true);
  const [onlyPaid, setOnlyPaid] = useState(false);
  const [index, setIndex] = useState(0); // Fase 27: un corte por página cuando la boleta cubre varios
  const [showAll, setShowAll] = useState(false);
  if (!daily) return null;
  if (!daily.cutoffs?.length) {
    return <p className="muted small daily-slip__empty">El desglose diario estará disponible al recalcular la planilla.</p>;
  }
  const m = (v) => formatMoney(v, currency);
  const total = daily.cutoffs.length;
  const current = Math.min(index, total - 1);
  const visible = showAll || total === 1 ? daily.cutoffs : [daily.cutoffs[current]];
  return (
    <section className="daily-slip" aria-label="Boleta desglosada por día">
      <header className="daily-slip__head">
        <div>
          <h3 className="section-title">Desglose diario de horas y pago</h3>
          <p className="muted small">
            Valor por hora {daily.hourly_rate ? m(daily.hourly_rate) : "—"} · {formatHours(daily.paid_h)} h pagables de {formatHours(daily.scheduled_h)} h
            programadas · las horas se cuentan en los cortes internos y se pagan en esta quincena.
          </p>
        </div>
        <div className="daily-slip__actions">
          <label className="checkbox small">
            <input type="checkbox" checked={onlyPaid} onChange={(e) => setOnlyPaid(e.target.checked)} /> Solo días con pago o descuento
          </label>
          <button type="button" className="button button--ghost button--sm" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
            {open ? "Ocultar días" : "Ver días"}
          </button>
        </div>
      </header>
      {open && total > 1 && (
        <nav className="daily-slip__pager" aria-label="Cortes de esta boleta">
          {!showAll && (
            <>
              <button type="button" className="button button--ghost button--sm" disabled={current === 0} onClick={() => setIndex(current - 1)}>
                ‹ Corte anterior
              </button>
              <span className="small">
                Corte {current + 1} de {total}
              </span>
              <button type="button" className="button button--ghost button--sm" disabled={current >= total - 1} onClick={() => setIndex(current + 1)}>
                Corte siguiente ›
              </button>
            </>
          )}
          <button type="button" className="link-button small" onClick={() => setShowAll((v) => !v)}>
            {showAll ? "Ver un corte a la vez" : `Ver los ${total} cortes`}
          </button>
        </nav>
      )}
      {open &&
        visible.map((c) => {
          const days = c.days.filter((d) => !onlyPaid || !isZero(d.total));
          return (
            <div key={c.code} className="daily-slip__cutoff">
              <p className="daily-slip__cutoff-title">
                <strong>Corte {c.code}</strong> · {formatDate(c.start)} al {formatDate(c.end)} · {formatHours(c.paid_h)} h pagables ·{" "}
                <strong>{m(c.total)}</strong>
              </p>
              <DailyDaysTable days={days} currency={currency} />
            </div>
          );
        })}
      <dl className="daily-slip__recon">
        <div>
          <dt>Suma de los días (tiempo)</dt>
          <dd>{m(daily.daily_total)}</dd>
        </div>
        <div>
          <dt>Otros devengos (AP: horas extra, bonos…)</dt>
          <dd>{m(daily.other_earnings)}</dd>
        </div>
        <div>
          <dt>Retenciones y descuentos</dt>
          <dd>−{m(daily.retentions)}</dd>
        </div>
        <div className={daily.reconciled ? "is-ok" : "is-warn"}>
          <dt>Conciliación con la boleta</dt>
          <dd>{daily.reconciled ? "Cuadra al centavo" : `Diferencia con las líneas por tiempo (${m(daily.time_lines_total)})`}</dd>
        </div>
      </dl>
    </section>
  );
}

/** Fase 27 — Tabla de días de un corte (la usan la boleta y el historial por corte del portal). */
export function DailyDaysTable({ days, currency }) {
  const m = (v) => formatMoney(v, currency);
  return (
    <div className="table-wrap">
      <table className="table table--compact daily-slip__table">
        <thead>
          <tr>
            <th scope="col">Fecha</th>
            <th scope="col">Día</th>
            <th scope="col" className="num">Programado</th>
            <th scope="col" className="num">Pagable</th>
            <th scope="col" className="num">Nocturno</th>
            <th scope="col" className="num">Salario</th>
            <th scope="col" className="num">Recargos</th>
            <th scope="col" className="num">Total</th>
          </tr>
        </thead>
        <tbody>
          {days.map((d) => {
            const extras = Number(d.vacation) + Number(d.night) + Number(d.holiday_premium) + Number(d.discount);
            return (
              <tr key={d.date} className={d.day_type === "REST" || d.day_type === "OUTSIDE" ? "is-muted" : ""}>
                <td className="pay-nowrap" data-label="Fecha">
                  <span className="daily-slip__wd">{d.weekday}</span> {formatDate(d.date)}
                </td>
                <td data-label="Día">
                  <span className={`badge badge--${TONE[d.day_type] ?? "info"}`}>{d.label}</span>
                  {d.notes && <div className="muted small">{d.notes}</div>}
                </td>
                <td className="num" data-label="Programado">{isZero(d.scheduled_h) ? "—" : formatHours(d.scheduled_h)}</td>
                <td className="num" data-label="Pagable">{isZero(d.paid_h) ? "—" : formatHours(d.paid_h)}</td>
                <td className="num" data-label="Nocturno">{isZero(d.night_h) ? "—" : formatHours(d.night_h)}</td>
                <td className="num" data-label="Salario">{isZero(d.regular) && isZero(d.vacation) ? "—" : m(Number(d.regular) + Number(d.vacation))}</td>
                <td className="num" data-label="Recargos" title={`Nocturnidad ${d.night} · feriado ${d.holiday_premium} · séptimo día ${d.discount}`}>
                  {extras - Number(d.vacation) === 0 ? "—" : m(extras - Number(d.vacation))}
                </td>
                <td className="num" data-label="Total">
                  <strong>{isZero(d.total) ? "—" : m(d.total)}</strong>
                </td>
              </tr>
            );
          })}
          {days.length === 0 && (
            <tr>
              <td colSpan={8} className="empty">
                Sin días con pago en este corte.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
