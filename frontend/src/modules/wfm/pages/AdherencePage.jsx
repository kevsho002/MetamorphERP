import { useTimeFormat } from "../../../app/timeFormat.js";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { todayIso } from "../../hcm/lib/format.js";
import { adhApi, fmtHM, fmtPct, hhmm } from "../api.js";
import Timeline from "../components/Timeline.jsx";

const KPIS = [
  ["adherence_pct", "Adherencia", "pct"],
  ["conformance_pct", "Conformidad", "pct"],
  ["scheduled", "Programado"],
  ["in_adherence", "En adherencia"],
  ["out_of_adherence", "Out of Adherence", null, "error"],
  ["unpaid_excess", "Unpaid Excess Login", null, "error"],
  ["justified", "Justificado (AP)"],
  ["paid_valid", "Válido para pago", null, "ok"],
  ["billable", "Facturable (billing)", null, "ok"],
  ["primary_work", "Trabajo principal"],
  ["secondary_paid", "Auxiliares secundarios pagados"],
];

const tone = (pct) => (pct === null || pct === undefined ? "" : pct >= 90 ? "adh-pct--ok" : pct >= 80 ? "adh-pct--warn" : "adh-pct--bad");

/**
 * Adherencia (WFM): cruza los segmentos programados con los estados reales del ACD / Web Timer. Muestra adherencia,
 * conformidad, tiempo válido para pago y facturación, trabajo principal vs auxiliares secundarios, y las desviaciones
 * (Out of Adherence y Unpaid Excess Login). «Guardar resultados» deja el cálculo para nómina y calidad.
 */
export default function AdherencePage() {
  useTimeFormat(); // Fase 21: re-render al cambiar HH:MM:SS / horas decimales
  const [params, setParams] = useSearchParams();
  const today = todayIso();
  const filters = useMemo(
    () => ({
      from: params.get("from") ?? today,
      to: params.get("to") ?? params.get("from") ?? today,
      group: params.get("group") ?? "",
      employee: params.get("employee") ?? "",
    }),
    [params, today],
  );
  const [catalogs, setCatalogs] = useState(null);
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [open, setOpen] = useState(null); // employee_code expandido
  const [detail, setDetail] = useState(null); // {employee, date}
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    adhApi.catalogs({ signal: controller.signal }).then(setCatalogs).catch(() => {});
    return () => controller.abort();
  }, []);

  const load = useCallback(
    (signal) => {
      setState((s) => ({ ...s, loading: true, error: null }));
      return adhApi
        .report(filters, { signal })
        .then((data) => setState({ loading: false, data, error: null }))
        .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    },
    [filters],
  );

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const update = (changes) => {
    const next = { ...filters, ...changes };
    setParams(Object.fromEntries(Object.entries(next).filter(([, v]) => v)), { replace: true });
    setDetail(null);
  };

  const save = () => {
    setBusy(true);
    adhApi
      .compute(filters)
      .then((b) => setNotice({ ok: true, text: b.feedback + (b.frozen?.length ? ` Cortes cerrados omitidos: ${b.frozen.map((f) => `${f.employee_code} (${f.cutoff})`).join(", ")}.` : "") }))
      .catch((err) => setNotice({ ok: false, text: err.message }))
      .finally(() => setBusy(false));
  };

  const data = state.data;
  const totals = data?.totals;

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Adherencia</h1>
          <p className="muted page-subtitle">
            Segmentos programados por WFM vs estados reales del ACD / Web Timer, por fecha de turno. Dentro del contenedor el tiempo en estado pagado es válido
            para pago; fuera de él, sin AP que lo justifique, es Unpaid Excess Login. Fuentes en SQL: <code>dbo.vw_AdhAdherenceDay</code> y{" "}
            <code>dbo.vw_AdhDeviation</code>.
          </p>
        </div>
        {catalogs?.can_manage && (
          <button type="button" className="button button--ghost" disabled={busy} onClick={save}
            title="Guarda los días ya terminados del rango (antes de hoy) para nómina y control de calidad">
            {busy ? "Guardando…" : "Guardar resultados"}
          </button>
        )}
      </header>

      <div className="filters" role="search">
        <label className="field">
          <span className="field__label">Desde</span>
          <input type="date" value={filters.from} onChange={(e) => e.target.value && update({ from: e.target.value, to: filters.to < e.target.value ? e.target.value : filters.to })} />
        </label>
        <label className="field">
          <span className="field__label">Hasta</span>
          <input type="date" value={filters.to} min={filters.from} onChange={(e) => e.target.value && update({ to: e.target.value })} />
        </label>
        <label className="field">
          <span className="field__label">Grupo</span>
          <select value={filters.group} onChange={(e) => update({ group: e.target.value, employee: "" })}>
            <option value="">Todos los agentes</option>
            {(catalogs?.groups ?? []).map((g) => (
              <option key={g.code} value={g.code}>
                {g.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Agente (ID)</span>
          <input type="search" defaultValue={filters.employee} placeholder="SV-2026-000001-7"
            onKeyDown={(e) => e.key === "Enter" && update({ employee: e.currentTarget.value.trim().toUpperCase() })} />
        </label>
      </div>

      {notice && (
        <div className={`alert ${notice.ok ? "alert--ok" : "alert--error"} flash`} role="status">
          <p className="alert__text">{notice.text}</p>
        </div>
      )}
      {state.error && <p className="error-box">{state.error}</p>}
      {state.loading && !data && <p className="muted">Calculando…</p>}

      {totals && (
        <dl className="kpis adh-kpis">
          {KPIS.map(([key, label, kind, tn]) => (
            <div key={key} className={`kpi${tn ? ` kpi--${tn}` : ""}`}>
              <dt>{label}</dt>
              <dd className={kind === "pct" ? tone(totals[key]) : ""}>{kind === "pct" ? fmtPct(totals[key]) : fmtHM(totals[key])}</dd>
            </div>
          ))}
        </dl>
      )}

      {data && (
        <div className="table-wrap">
          <table className="table adh-table">
            <thead>
              <tr>
                <th>Agente</th>
                <th className="num">Adherencia</th>
                <th className="num">Conformidad</th>
                <th className="num">Programado</th>
                <th className="num">En adherencia</th>
                <th className="num">Out of Adh.</th>
                <th className="num">Unpaid Excess</th>
                <th className="num">Válido p/ pago</th>
                <th className="num">Facturable</th>
                <th className="num">Principal / Secund.</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.length === 0 && (
                <tr>
                  <td colSpan={10} className="empty">Sin agentes con esos filtros.</td>
                </tr>
              )}
              {data.rows.map((r) => (
                <Fragment key={r.employee_code}>
                  <tr className="table__row--link" onClick={() => setOpen(open === r.employee_code ? null : r.employee_code)}>
                    <td>
                      <button type="button" className="link-button" aria-expanded={open === r.employee_code}>
                        {open === r.employee_code ? "▾" : "▸"} {r.full_name}
                      </button>
                      <span className="muted small"> {r.employee_code}</span>
                    </td>
                    <TotalsCells t={r.totals} />
                  </tr>
                  {open === r.employee_code &&
                    r.days.map((d) => (
                      <tr key={d.date} className={`adh-day${detail?.employee === r.employee_code && detail?.date === d.date ? " row--current" : ""}`}>
                        <td>
                          <button type="button" className="link-button" onClick={() => setDetail({ employee: r.employee_code, date: d.date })}>
                            {d.date}
                          </button>
                        </td>
                        <TotalsCells t={d} />
                      </tr>
                    ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {detail && <DayDetail key={`${detail.employee}-${detail.date}`} {...detail} onClose={() => setDetail(null)} />}
    </section>
  );
}

function TotalsCells({ t }) {
  return (
    <>
      <td className={`num ${tone(t.adherence_pct)}`}>{fmtPct(t.adherence_pct)}</td>
      <td className="num">{fmtPct(t.conformance_pct)}</td>
      <td className="num">{fmtHM(t.scheduled)}</td>
      <td className="num">{fmtHM(t.in_adherence)}</td>
      <td className={`num${t.out_of_adherence ? " text-error" : ""}`}>{fmtHM(t.out_of_adherence)}</td>
      <td className={`num${t.unpaid_excess ? " text-error" : ""}`}>{fmtHM(t.unpaid_excess)}</td>
      <td className="num">{fmtHM(t.paid_valid)}</td>
      <td className="num">{fmtHM(t.billable)}</td>
      <td className="num">
        {fmtHM(t.primary_work)} / {fmtHM(t.secondary_paid)}
      </td>
    </>
  );
}

function DayDetail({ employee, date, onClose }) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  useEffect(() => {
    const controller = new AbortController();
    adhApi
      .detail({ employee, date }, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [employee, date]);
  const d = state.data;
  return (
    <section className="form-section adh-detail" aria-label="Detalle del día">
      <header className="adh-detail__head">
        <h2 className="form-section__title">
          {d ? `${d.full_name} · ${date}` : `${employee} · ${date}`}
        </h2>
        <button type="button" className="link-button" onClick={onClose}>
          Cerrar
        </button>
      </header>
      {state.error && <p className="error-box">{state.error}</p>}
      {state.loading && <p className="muted">Cargando…</p>}
      {d && (
        <>
          <Timeline
            start={d.window.start}
            end={d.window.end}
            lanes={[
              { key: "plan", label: "Programado", blocks: d.plan.map((b, i) => ({ key: i, start: b.start, end: b.end, color: b.color, label: b.activity_name,
                variant: b.source === "SEGMENT" ? "segment" : "fill" })) },
              { key: "real", label: "Real (ACD)", blocks: d.actual.map((a, i) => ({ key: i, start: a.start, end: a.end, color: "var(--adh-actual)", label: a.label })) },
              { key: "dev", label: "Desviaciones", blocks: [
                ...d.justifications.map((j, i) => ({ key: `j${i}`, start: j.start, end: j.end, color: "#64748b", label: j.folio, variant: "justified",
                  title: `Justificado con ${j.folio}${j.is_paid ? " (pagado)" : ""}` })),
                ...d.deviations.map((x, i) => ({ key: `d${i}`, start: x.start, end: x.end, color: x.kind === "UNPAID_EXCESS_LOGIN" ? "#b91c1c" : "#ea580c",
                  label: x.kind === "UNPAID_EXCESS_LOGIN" ? "Excess" : "OOA", title: `${x.kind_label} · ${hhmm(x.start)}–${hhmm(x.end)} · ${x.actual}` })),
              ] },
            ]}
          />
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Desviación</th>
                  <th>Desde</th>
                  <th>Hasta</th>
                  <th className="num">Duración</th>
                  <th>Programado</th>
                  <th>Real</th>
                </tr>
              </thead>
              <tbody>
                {d.deviations.length === 0 && (
                  <tr>
                    <td colSpan={6} className="empty">Sin desviaciones: el agente cumplió su plan.</td>
                  </tr>
                )}
                {d.deviations.map((x, i) => (
                  <tr key={i}>
                    <td>
                      <span className={`badge ${x.kind === "UNPAID_EXCESS_LOGIN" ? "badge--error" : "badge--warn"}`}>{x.kind_label}</span>
                    </td>
                    <td>{hhmm(x.start)}</td>
                    <td>{hhmm(x.end)}</td>
                    <td className="num">{fmtHM(x.seconds)}</td>
                    <td>{x.expected_name ?? "Fuera del turno"}</td>
                    <td>{x.actual}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
