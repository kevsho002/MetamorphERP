import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useTimeFormat } from "../../../app/timeFormat.js";
import { formatDate, formatDateTime, todayIso } from "../../hcm/lib/format.js";
import { payrollApi } from "../../payroll/api.js";
import { KIND_COLORS, MonthGrid, YearGrid, monthName } from "../components/HolidayCalendar.jsx";
import HolidayEditor from "../components/HolidayEditor.jsx";

const WEEKDAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];
const VIEWS = [
  { value: "month", label: "Mes" },
  { value: "year", label: "Año" },
  { value: "list", label: "Lista y Holiday Segments" },
];

/**
 * Horarios y tiempo › Calendario de feriados. Fase 21: feriados legales por país y Holiday Segments (el contenedor del
 * turno laborado en un feriado; la planilla paga las horas más el recargo, sin afectar la adherencia).
 * Fase 23: calendario interactivo por mes y por año con alta, edición, activación y baja directamente en React para los
 * perfiles autorizados (payroll.manage), y copia de los feriados al año siguiente (Semana Santa recalculada en SQL Server).
 */
export default function HolidaysPage() {
  const time = useTimeFormat();
  const today = todayIso();
  const [params, setParams] = useSearchParams();
  const year = Number(params.get("year")) || new Date().getFullYear();
  const month = params.get("month") !== null ? Math.min(11, Math.max(0, Number(params.get("month")))) : new Date().getMonth();
  const view = VIEWS.some((v) => v.value === params.get("view")) ? params.get("view") : "month";
  const country = params.get("country") || "SV";
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [segments, setSegments] = useState(null);
  const [reload, setReload] = useState(0);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [editor, setEditor] = useState(null); // { holiday } | { date }

  const go = useCallback((patch) => {
    const next = { year, month, view, country, ...patch };
    setParams({ year: String(next.year), month: String(next.month), view: next.view, country: next.country }, { replace: true });
  }, [year, month, view, country, setParams]);

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true }));
    payrollApi
      .holidays({ year, country }, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    if (view === "list") {
      payrollApi
        .holidaySegments({ from: `${year}-01-01`, to: `${year}-12-31` }, { signal: controller.signal })
        .then(setSegments)
        .catch(() => setSegments(null));
    }
    return () => controller.abort();
  }, [year, country, reload, view]);

  const data = state.data;
  const canManage = Boolean(data?.can_manage);
  const rows = useMemo(() => data?.results ?? [], [data]);
  const byDate = useMemo(() => rows.reduce((m, h) => ({ ...m, [String(h.date).slice(0, 10)]: [...(m[String(h.date).slice(0, 10)] ?? []), h] }), {}), [rows]);
  const upcoming = rows.filter((h) => h.is_active && String(h.date) >= today).slice(0, 5);

  const done = (promise, text) => {
    setBusy(true);
    setNotice(null);
    return promise
      .then((b) => {
        setNotice({ ok: true, text: b?.feedback ?? text });
        setEditor(null);
        setReload((k) => k + 1);
      })
      .catch((err) => setNotice({ ok: false, text: err.message }))
      .finally(() => setBusy(false));
  };
  const save = (form) => {
    const payload = { ...form, country };
    if (editor?.holiday) {
      const h = editor.holiday;
      if (h.segments > 0) delete payload.date;
      return done(payrollApi.updateHoliday(h.id, payload), `Feriado «${form.name}» actualizado.`);
    }
    return done(payrollApi.createHoliday(payload), `Feriado «${form.name}» registrado el ${formatDate(form.date)}.`);
  };
  const shift = (delta) => {
    if (view === "year") return go({ year: year + delta });
    const m = month + delta;
    return go({ month: (m + 12) % 12, year: year + Math.floor(m / 12) });
  };

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Calendario de feriados</h1>
          <p className="muted page-subtitle">
            Feriados legales por país. Si alguien labora en un feriado se genera su Holiday Segment y la planilla le paga las horas regulares más el
            recargo (pago doble), sin afectar la adherencia ni marcar ausencias.
            {canManage ? " Haga clic en un día libre para agregar un feriado o en un feriado para editarlo." : ""}
          </p>
        </div>
        <div className="pay-actions">
          {data && (
            <label className="field">
              <span className="field__label">País</span>
              <select value={country} onChange={(e) => go({ country: e.target.value })}>
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

      <div className="holcal__bar">
        <div className="pay-actions" role="tablist" aria-label="Vista">
          {VIEWS.map((v) => (
            <button key={v.value} type="button" role="tab" aria-selected={view === v.value}
              className={`button button--sm${view === v.value ? "" : " button--ghost"}`} onClick={() => go({ view: v.value })}>
              {v.label}
            </button>
          ))}
        </div>
        <div className="holcal__nav">
          <button type="button" className="button button--ghost button--sm" aria-label="Anterior" onClick={() => shift(-1)}>
            ‹
          </button>
          <span className="holcal__title" aria-live="polite">
            {view === "month" ? `${monthName(month)} ${year}` : year}
          </span>
          <button type="button" className="button button--ghost button--sm" aria-label="Siguiente" onClick={() => shift(1)}>
            ›
          </button>
          <button type="button" className="button button--ghost button--sm" onClick={() => go({ year: new Date().getFullYear(), month: new Date().getMonth() })}>
            Hoy
          </button>
        </div>
        {canManage && (
          <div className="pay-actions">
            <button type="button" className="button button--sm" onClick={() => setEditor({ date: view === "month" ? `${year}-${String(month + 1).padStart(2, "0")}-01` : `${year}-01-01` })}>
              + Feriado
            </button>
            <button type="button" className="button button--ghost button--sm" disabled={busy}
              onClick={() => window.confirm(`¿Copiar los feriados de ${year} a ${year + 1}? (Semana Santa se recalcula; las fechas ya registradas se omiten.)`)
                && done(payrollApi.copyHolidayYear({ country, from_year: year, to_year: year + 1 }))}>
              Copiar a {year + 1}
            </button>
          </div>
        )}
      </div>

      {notice && <p className={notice.ok ? "alert alert--ok" : "error-box"}>{notice.text}</p>}
      {state.error && <p className="error-box">{state.error}</p>}

      {view !== "list" && (
        <>
          <p className="holcal__legend">
            {(data?.kinds ?? []).map((k) => (
              <span key={k.value}>
                <i style={{ background: KIND_COLORS[k.value] }} />
                {k.label}
              </span>
            ))}
            <span className="muted">· {rows.length} feriado(s) en {year}</span>
          </p>
          <div aria-busy={state.loading}>
            {view === "month" ? (
              <MonthGrid year={year} month={month} byDate={byDate} today={today} canManage={canManage}
                onAdd={(date) => setEditor({ date })} onOpen={(h) => setEditor({ holiday: h })} />
            ) : (
              <YearGrid year={year} byDate={byDate} today={today} onMonth={(m) => go({ month: m, view: "month" })} onOpen={(h) => setEditor({ holiday: h })} />
            )}
          </div>
          {upcoming.length > 0 && (
            <>
              <h2 className="section-title">Próximos feriados</h2>
              <ul className="holcal__upcoming">
                {upcoming.map((h) => (
                  <li key={h.id}>
                    <button type="button" className="link-button" onClick={() => setEditor({ holiday: h })}>
                      {h.name}
                    </button>
                    <span className="muted">
                      {WEEKDAYS[h.weekday]} {formatDate(h.date)}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}

      {view === "list" && (
        <>
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
                {rows.map((h) => (
                  <tr key={h.id} className={h.is_active ? "" : "is-muted"}>
                    <td className="pay-nowrap">
                      {formatDate(h.date)}
                      <div className="muted small">{WEEKDAYS[h.weekday]}</div>
                    </td>
                    <td>
                      <button type="button" className="link-button" onClick={() => setEditor({ holiday: h })}>
                        <strong>{h.name}</strong>
                      </button>
                      {h.legal_reference && <div className="muted small">{h.legal_reference}</div>}
                    </td>
                    <td className="small">{h.kind_label}</td>
                    <td className="num">{Number(h.premium_percent).toFixed(0)} %</td>
                    <td className="num">{h.segments}</td>
                    <td className="small">{h.is_active ? "Activo" : "Inactivo"}</td>
                  </tr>
                ))}
                {!state.loading && data && rows.length === 0 && (
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
        </>
      )}

      {editor && (
        <HolidayEditor
          holiday={editor.holiday}
          date={editor.date}
          kinds={data?.kinds ?? []}
          canManage={canManage}
          busy={busy}
          onClose={() => setEditor(null)}
          onSave={save}
          onDelete={(h) => done(payrollApi.deleteHoliday(h.id), `Feriado «${h.name}» eliminado.`)}
        />
      )}
    </section>
  );
}
