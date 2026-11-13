import { useEffect, useState } from "react";
import { useTimeFormat } from "../../../app/timeFormat.js";
import { formatDate, formatDateTime } from "../../hcm/lib/format.js";
import { payrollApi } from "../../payroll/api.js";

const WEEKDAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];
const EMPTY = { date: "", name: "", kind: "NATIONAL", premium_percent: "100", legal_reference: "" };

/**
 * Fase 21 — Calendario de feriados legales por país y Holiday Segments: cuando un colaborador labora en un feriado, el
 * sistema genera automáticamente su contenedor (el bloque del turno con las horas laboradas). La planilla paga esas
 * horas como salario regular + el recargo del feriado (pago doble). No cambia la adherencia ni la asistencia de WFM: en
 * un feriado no se marcan Unjustified Absence ni Lateness.
 */
export default function HolidaysPage() {
  const time = useTimeFormat();
  const thisYear = new Date().getFullYear();
  const [year, setYear] = useState(thisYear);
  const [country, setCountry] = useState("SV");
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [segments, setSegments] = useState(null);
  const [reload, setReload] = useState(0);
  const [form, setForm] = useState(EMPTY);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    payrollApi
      .holidays({ year, country }, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    payrollApi
      .holidaySegments({ from: `${year}-01-01`, to: `${year}-12-31` }, { signal: controller.signal })
      .then(setSegments)
      .catch(() => setSegments(null));
    return () => controller.abort();
  }, [year, country, reload]);

  const done = (promise, text) => {
    setBusy(true);
    setNotice(null);
    return promise
      .then((b) => {
        setNotice({ ok: true, text: b?.feedback ?? text });
        setReload((k) => k + 1);
      })
      .catch((err) => setNotice({ ok: false, text: err.message }))
      .finally(() => setBusy(false));
  };
  const data = state.data;
  const canManage = data?.can_manage;

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Calendario de feriados</h1>
          <p className="muted page-subtitle">
            Feriados legales por país. Si alguien labora en un feriado se genera su Holiday Segment y la planilla le paga las horas
            regulares más el recargo del feriado (pago doble), sin afectar la adherencia ni marcar ausencias injustificadas.
          </p>
        </div>
        <div className="pay-actions">
          <label className="field">
            <span className="field__label">Año</span>
            <select value={year} onChange={(e) => setYear(Number(e.target.value))}>
              {[thisYear - 1, thisYear, thisYear + 1].map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </label>
          {data && (
            <label className="field">
              <span className="field__label">País</span>
              <select value={country} onChange={(e) => setCountry(e.target.value)}>
                {data.countries.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.code} · {c.name}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      </header>
      {notice && <p className={notice.ok ? "alert alert--ok" : "error-box"}>{notice.text}</p>}
      {state.error && <p className="error-box">{state.error}</p>}

      {canManage && (
        <form className="pay-inline-form" onSubmit={(e) => {
          e.preventDefault();
          done(payrollApi.createHoliday({ ...form, country }), "Feriado registrado.").then(() => setForm(EMPTY));
        }}>
          <label className="field">
            <span className="field__label">Fecha</span>
            <input type="date" required value={form.date} onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))} />
          </label>
          <label className="field">
            <span className="field__label">Nombre</span>
            <input required maxLength={120} value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
          </label>
          <label className="field">
            <span className="field__label">Tipo</span>
            <select value={form.kind} onChange={(e) => setForm((f) => ({ ...f, kind: e.target.value }))}>
              {(data?.kinds ?? []).map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field__label">Recargo (%)</span>
            <input type="number" min="0" max="300" step="0.01" value={form.premium_percent}
              onChange={(e) => setForm((f) => ({ ...f, premium_percent: e.target.value }))} />
          </label>
          <button type="submit" className="button button--sm" disabled={busy}>
            Agregar feriado
          </button>
        </form>
      )}

      <div className="table-wrap" aria-busy={state.loading}>
        <table className="table hol-table">
          <thead>
            <tr>
              <th scope="col">Fecha</th>
              <th scope="col">Feriado</th>
              <th scope="col">Tipo</th>
              <th scope="col" className="num">
                Recargo
              </th>
              <th scope="col" className="num">
                Holiday Segments
              </th>
              <th scope="col">Estado</th>
            </tr>
          </thead>
          <tbody>
            {(data?.results ?? []).map((h) => (
              <tr key={h.id} className={h.is_active ? "" : "is-muted"}>
                <td className="pay-nowrap">
                  {formatDate(h.date)}
                  <div className="muted small">{WEEKDAYS[h.weekday]}</div>
                </td>
                <td>
                  <strong>{h.name}</strong>
                  {h.legal_reference && <div className="muted small">{h.legal_reference}</div>}
                </td>
                <td className="small">{h.kind_label}</td>
                <td className="num">{Number(h.premium_percent).toFixed(0)} %</td>
                <td className="num">{h.segments}</td>
                <td>
                  {canManage ? (
                    <div className="pay-actions">
                      <button type="button" className="button button--ghost button--sm" disabled={busy}
                        onClick={() => done(payrollApi.updateHoliday(h.id, { is_active: !h.is_active }), h.is_active ? "Feriado desactivado." : "Feriado activado.")}>
                        {h.is_active ? "Desactivar" : "Activar"}
                      </button>
                      {h.segments === 0 && (
                        <button type="button" className="button button--danger button--sm" disabled={busy}
                          onClick={() => window.confirm(`¿Eliminar el feriado «${h.name}»?`) && done(payrollApi.deleteHoliday(h.id), "Feriado eliminado.")}>
                          Eliminar
                        </button>
                      )}
                    </div>
                  ) : (
                    <span className="small">{h.is_active ? "Activo" : "Inactivo"}</span>
                  )}
                </td>
              </tr>
            ))}
            {!state.loading && data && data.results.length === 0 && (
              <tr>
                <td colSpan={6} className="empty">
                  No hay feriados registrados para {year}.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <h2 className="section-title">Holiday Segments (feriados laborados)</h2>
      {segments?.can_generate && (
        <p>
          <button type="button" className="button button--ghost button--sm" disabled={busy}
            onClick={() => done(payrollApi.generateHolidaySegments({ from: `${year}-01-01`, to: `${year}-12-31` }))}>
            Regenerar Holiday Segments de {year}
          </button>{" "}
          <span className="muted small">Se generan solos al conciliar la asistencia y al calcular la planilla.</span>
        </p>
      )}
      <div className="table-wrap">
        <table className="table table--compact hol-segments">
          <thead>
            <tr>
              <th scope="col">Fecha</th>
              <th scope="col">Colaborador</th>
              <th scope="col">Contenedor</th>
              <th scope="col" className="num">
                Programado ({time.unit})
              </th>
              <th scope="col" className="num">
                Laborado ({time.unit})
              </th>
              <th scope="col" className="num">
                Nocturno ({time.unit})
              </th>
              <th scope="col" className="num">
                Recargo
              </th>
            </tr>
          </thead>
          <tbody>
            {(segments?.results ?? []).map((s) => (
              <tr key={s.id}>
                <td className="pay-nowrap">
                  {formatDate(s.date)}
                  <div className="muted small">{s.holiday}</div>
                </td>
                <td>
                  {s.full_name}
                  <div className="muted small">{s.employee_code}</div>
                </td>
                <td className="small pay-nowrap">
                  {formatDateTime(s.start_at)} → {formatDateTime(s.end_at)}
                </td>
                <td className="num">{time.seconds(s.scheduled_seconds)}</td>
                <td className="num">{time.seconds(s.worked_seconds)}</td>
                <td className="num">{s.night_seconds ? time.seconds(s.night_seconds) : "—"}</td>
                <td className="num">{Number(s.premium_percent).toFixed(0)} %</td>
              </tr>
            ))}
            {segments && segments.results.length === 0 && (
              <tr>
                <td colSpan={7} className="empty">
                  Nadie ha laborado en un feriado de {year}.
                </td>
              </tr>
            )}
          </tbody>
          {segments?.results.length > 0 && (
            <tfoot>
              <tr>
                <th scope="row" colSpan={4}>
                  Total ({segments.count})
                </th>
                <td className="num">{time.seconds(segments.totals.worked_seconds)}</td>
                <td className="num">{time.seconds(segments.totals.night_seconds)}</td>
                <td />
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </section>
  );
}
