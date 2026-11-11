import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { formatDate, todayIso } from "../../hcm/lib/format.js";
import { schedulingApi } from "../api.js";

const MONTHS = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];

/**
 * Ciclos de pago, agrupados por año y frecuencia (Fase 10) con DOS dimensiones independientes (Fase 11):
 * - Periodo de PAGO: fechas oficiales de devengo y pago (1–15 / 16–fin).
 * - Corte interno de ASISTENCIA: ventana en la que se cuentan las horas (p. ej. 25–9 / 10–24); se cierra y reabre.
 * Cada corte aparece junto al periodo de pago que lo paga (el que contiene su fecha de cierre). Las reglas se
 * parametrizan en /admin/ › Ciclos de pago.
 */
export default function PayCyclesPage() {
  const [params, setParams] = useSearchParams();
  const thisYear = Number(todayIso().slice(0, 4));
  const year = Number(params.get("year")) || thisYear;
  const frequency = params.get("frequency") ?? "";
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [reloadKey, setReloadKey] = useState(0);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(null);

  const setFilter = (changes) => {
    const next = { year: String(year), frequency, ...changes };
    setParams(Object.fromEntries(Object.entries(next).filter(([k, v]) => v !== "" && !(k === "year" && v === String(thisYear)))), { replace: true });
  };

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    schedulingApi
      .payCycles({ year, frequency: frequency || undefined }, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [year, frequency, reloadKey]);

  const act = async (key, fn) => {
    setBusy(key);
    setNotice(null);
    try {
      const body = await fn();
      setNotice({ ok: true, text: body.feedback });
      setReloadKey((k) => k + 1);
    } catch (err) {
      setNotice({ ok: false, text: err.message });
    } finally {
      setBusy(null);
    }
  };

  const data = state.data;
  const canManage = data?.can_manage;
  const today = todayIso();
  const years = useMemo(() => {
    const set = new Set([...(data?.years ?? []), thisYear, thisYear + 1, year]);
    return [...set].sort((a, b) => a - b);
  }, [data, thisYear, year]);
  const groups = useMemo(() => {
    const out = new Map();
    for (const c of data?.results ?? []) {
      const key = c.pay_frequency_label;
      if (!out.has(key)) out.set(key, []);
      out.get(key).push(c);
    }
    return [...out.entries()];
  }, [data]);

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Ciclos de pago y cortes</h1>
          <p className="muted page-subtitle">
            El <strong>periodo de pago</strong> fija las fechas oficiales de devengo y pago; el <strong>corte de asistencia</strong> es la ventana en
            la que se cuentan las horas y puede cruzar de mes (p. ej. del 25 al 9 y del 10 al 24). Cada dimensión se valida por separado (sin
            huecos ni colisiones) y cada corte se paga en el periodo que contiene su fecha de cierre. Se parametrizan en /admin/ › Ciclos de pago.
          </p>
        </div>
      </header>

      <div className="filters" role="search">
        <div className="field">
          <span className="field__label">Año</span>
          <div className="segmented" role="tablist" aria-label="Año">
            {years.map((y) => (
              <button
                key={y}
                type="button"
                role="tab"
                aria-selected={y === year}
                className={`segmented__item${y === year ? " segmented__item--active" : ""}`}
                onClick={() => setFilter({ year: String(y) })}
              >
                {y}
              </button>
            ))}
          </div>
        </div>
        <label className="field">
          <span className="field__label">Frecuencia</span>
          <select value={frequency} onChange={(e) => setFilter({ frequency: e.target.value })}>
            <option value="">Todas</option>
            {(data?.frequencies ?? []).map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {notice && (
        <div className={`alert ${notice.ok ? "alert--ok" : "alert--error"} flash`} role="status">
          <p className="alert__text">{notice.text}</p>
        </div>
      )}
      {state.error && <p className="error-box">{state.error}</p>}
      {state.loading && !data && <p className="muted">Cargando ciclos…</p>}
      {data?.results.length === 0 && <p className="empty">No hay ciclos de pago con estos filtros.</p>}

      {groups.map(([label, cycles]) => (
        <section key={label} className="cycle-group" aria-label={`Ciclos ${label}`}>
          <h2 className="section-title">
            {label} <span className="muted small">· {year}</span>
          </h2>
          {cycles.map((c) => (
            <CycleCard
              key={c.code}
              cycle={c}
              year={year}
              today={today}
              canManage={canManage}
              busy={busy}
              onGenerate={() => act(`gen-${c.code}`, () => schedulingApi.generatePeriods(c.code, year))}
              onClose={(x) => act(`c-${x.id}`, () => schedulingApi.closeCutoff(x.id))}
              onReopen={(x) => act(`c-${x.id}`, () => schedulingApi.reopenCutoff(x.id))}
            />
          ))}
        </section>
      ))}
    </section>
  );
}

function CycleCard({ cycle: c, year, today, canManage, busy, onGenerate, onClose, onReopen }) {
  const byMonth = useMemo(() => {
    const out = new Map();
    for (const p of c.periods) {
      if (!out.has(p.month)) out.set(p.month, []);
      out.get(p.month).push(p);
    }
    return [...out.entries()];
  }, [c.periods]);

  return (
    <details className="form-section cycle-card" open={Boolean(c.stats.current) || c.periods.length === 0}>
      <summary className="cycle-card__summary">
        <span className="cycle-card__title">
          {c.name} <code className="small">{c.code}</code>
          {c.is_default && <span className="badge badge--ok">Predeterminado</span>}
          {c.cutoffs_cross_month && <span className="badge badge--info">Cortes que cruzan de mes</span>}
        </span>
        <span className="cycle-card__rules">
          <span>
            <strong>Pago:</strong> {c.rule_description}
            {c.payment_lag_days ? ` · se paga ${c.payment_lag_days} día(s) después del fin` : " · se paga el último día"}
          </span>
          <span>
            <strong>Asistencia:</strong> {c.cutoff_rule_description}
          </span>
        </span>
        <span className="muted small">
          {c.country} · {c.stats.total} periodo(s) de pago · {c.stats.cutoffs} corte(s), {c.stats.closed} cerrado(s)
          {c.stats.current && ` · corte en curso: ${c.stats.current}`}
          {c.stats.periods_without_cutoff > 0 && ` · ${c.stats.periods_without_cutoff} periodo(s) sin corte`}
        </span>
      </summary>
      {canManage && (
        <div className="form-actions form-actions--start">
          <button type="button" className="button button--sm" disabled={busy === `gen-${c.code}`} onClick={onGenerate}>
            {busy === `gen-${c.code}` ? "Generando…" : `Generar periodos y cortes ${year}`}
          </button>
        </div>
      )}
      {c.periods.length === 0 ? (
        <div className="muted small">
          <p>Sin periodos en {year}. Se generarían, por ejemplo:</p>
          <ul className="cycle-preview">
            {c.preview.map((p) => (
              <li key={p.label}>
                <strong>{p.label}</strong> {formatDate(p.period_start)}–{formatDate(p.period_end)}, pago {formatDate(p.payment_date)}
                {p.cutoffs.map((x) => ` · asistencia ${formatDate(x.cutoff_start)}–${formatDate(x.cutoff_end)}`).join("")}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="table cycle-table">
            <thead>
              <tr>
                <th scope="col">Mes</th>
                <th scope="col">Periodo de pago</th>
                <th scope="col">Pago</th>
                <th scope="col">Corte(s) de asistencia que paga</th>
                <th scope="col">
                  <span className="sr-only">Acciones del periodo</span>
                </th>
              </tr>
            </thead>
            {byMonth.map(([month, periods]) => (
              <tbody key={month} className="cycle-month">
                {periods.map((p, i) => (
                  <tr key={p.id} className={p.period_start <= today && today <= p.period_end ? "row--current" : undefined}>
                    {i === 0 && (
                      <th scope="rowgroup" rowSpan={periods.length} className="cycle-month__label">
                        {MONTHS[month - 1]}
                      </th>
                    )}
                    <td>
                      <code>{p.code}</code>
                      <div className="small">
                        {formatDate(p.period_start)} – {formatDate(p.period_end)}
                      </div>
                    </td>
                    <td>{formatDate(p.payment_date)}</td>
                    <td>
                      {p.cutoffs.length === 0 ? (
                        <span className="badge badge--warn">Sin corte</span>
                      ) : (
                        <ul className="cutoff-list">
                          {p.cutoffs.map((x) => (
                            <li key={x.id} className={x.cutoff_start <= today && today <= x.cutoff_end ? "cutoff-list__item--current" : undefined}>
                              <code>{x.code}</code> {formatDate(x.cutoff_start)} – {formatDate(x.cutoff_end)}
                              {x.crosses_month && <span className="badge badge--info shift-grid__badge">cruza de mes</span>}{" "}
                              <span className={`badge ${x.status === "CLOSED" ? "badge--muted" : "badge--ok"}`}>{x.status_label}</span>
                              {x.closed_by && <span className="muted small"> por {x.closed_by}</span>}
                              <span className="gid-actions">
                                <Link className="link-button" to={`/scheduling/report?cutoff=${x.id}`}>
                                  Horas del corte
                                </Link>
                                {canManage && x.status === "OPEN" && x.cutoff_end < today && (
                                  <button type="button" className="link-button" disabled={Boolean(busy)} onClick={() => onClose(x)}>
                                    Cerrar corte
                                  </button>
                                )}
                                {canManage && x.status === "CLOSED" && (
                                  <button type="button" className="link-button" disabled={Boolean(busy)} onClick={() => onReopen(x)}>
                                    Reabrir
                                  </button>
                                )}
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </td>
                    <td>
                      <span className="gid-actions">
                        <Link className="link-button" to={`/scheduling/report?period=${p.id}`}>
                          Horas para planilla
                        </Link>
                        <a className="link-button" href={schedulingApi.payPeriodHoursCsvUrl(p.id)} download>
                          CSV
                        </a>
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
        </div>
      )}
    </details>
  );
}
