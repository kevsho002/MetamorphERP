import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { formatDate, todayIso } from "../../hcm/lib/format.js";
import { schedulingApi } from "../api.js";

const MONTHS = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];

/**
 * Ciclos de pago y cortes operativos internos, AGRUPADOS POR AÑO (Fase 10). Cada periodo pertenece al año en que
 * inicia (un corte BPO del 25/12 al 09/01 es del año que termina), así no se repite. Los ciclos se agrupan por
 * frecuencia (quincenal, mensual, semanal) y sus periodos por mes, plegados salvo el ciclo con el corte en curso.
 * Los ciclos (día de inicio, fin de la primera quincena, corte y pago) se parametrizan en /admin/.
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
            Los periodos pueden cruzar de un mes al siguiente (p. ej. del 10 al 24 y del 25 al 9): solo se exige que cada uno inicie el día siguiente
            al fin del anterior, sin huecos ni colisiones. Se parametrizan en /admin/ › Horarios, tiempo y cortes.
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
              onClose={(p) => act(`p-${p.id}`, () => schedulingApi.closePeriod(p.id))}
              onReopen={(p) => act(`p-${p.id}`, () => schedulingApi.reopenPeriod(p.id))}
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
          {c.crosses_month && <span className="badge badge--info">Cruza de mes</span>}
        </span>
        <span className="muted small">
          {c.country} · {c.rule_description} · corte {c.cutoff_lag_days ? `${c.cutoff_lag_days} día(s) antes del fin` : "al fin del periodo"} · pago{" "}
          {c.payment_lag_days ? `${c.payment_lag_days} día(s) después` : "el último día"} · {c.stats.total} periodo(s), {c.stats.closed} cerrado(s)
          {c.stats.current && ` · en curso: ${c.stats.current}`}
        </span>
      </summary>
      {canManage && (
        <div className="form-actions form-actions--start">
          <button type="button" className="button button--sm" disabled={busy === `gen-${c.code}`} onClick={onGenerate}>
            {busy === `gen-${c.code}` ? "Generando…" : `Generar periodos ${year}`}
          </button>
        </div>
      )}
      {c.periods.length === 0 ? (
        <p className="muted small">
          Sin periodos en {year}.
          {c.preview.length > 0 &&
            ` Se generarían, por ejemplo: ${c.preview.map((p) => `${p.label} (${formatDate(p.period_start)}–${formatDate(p.period_end)})`).join(" · ")}…`}
        </p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Mes de inicio</th>
                <th scope="col">Periodo</th>
                <th scope="col">Fechas del periodo</th>
                <th scope="col">Ventana de asistencia (corte)</th>
                <th scope="col">Pago</th>
                <th scope="col">Estado</th>
                <th scope="col">
                  <span className="sr-only">Acciones</span>
                </th>
              </tr>
            </thead>
            {byMonth.map(([month, periods]) => (
              <tbody key={month} className="cycle-month">
                {periods.map((p, i) => (
                  <tr key={p.id} className={p.cutoff_start <= today && today <= p.cutoff_end ? "row--current" : undefined}>
                    {i === 0 && (
                      <th scope="rowgroup" rowSpan={periods.length} className="cycle-month__label">
                        {MONTHS[month - 1]}
                      </th>
                    )}
                    <td>
                      <code>{p.code}</code>
                    </td>
                    <td>
                      {formatDate(p.period_start)} – {formatDate(p.period_end)}
                      {p.crosses_month && <span className="badge badge--info shift-grid__badge">cruza de mes</span>}
                    </td>
                    <td>
                      {formatDate(p.cutoff_start)} – {formatDate(p.cutoff_end)}
                    </td>
                    <td>{formatDate(p.payment_date)}</td>
                    <td>
                      <span className={`badge ${p.status === "CLOSED" ? "badge--muted" : "badge--ok"}`}>{p.status_label}</span>
                      {p.closed_by && <span className="muted small"> por {p.closed_by}</span>}
                    </td>
                    <td>
                      <span className="gid-actions">
                        <Link className="link-button" to={`/scheduling/report?period=${p.id}`}>
                          Horas del corte
                        </Link>
                        {canManage && p.status === "OPEN" && p.cutoff_end < today && (
                          <button type="button" className="link-button" disabled={Boolean(busy)} onClick={() => onClose(p)}>
                            Cerrar corte
                          </button>
                        )}
                        {canManage && p.status === "CLOSED" && (
                          <button type="button" className="link-button" disabled={Boolean(busy)} onClick={() => onReopen(p)}>
                            Reabrir
                          </button>
                        )}
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
