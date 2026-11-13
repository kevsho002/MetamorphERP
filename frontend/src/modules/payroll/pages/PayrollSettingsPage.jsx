import { useEffect, useMemo, useState } from "react";
import { formatDate, todayIso } from "../../hcm/lib/format.js";
import { num, payrollApi, pct } from "../api.js";

// Fase 21: motor 100 % por horas. Las horas no laboradas no se pagan; el séptimo día es opcional (y por cuenta).
const TOGGLES = [
  ["seventh_day_penalty", "Pérdida del séptimo día por semana con Unjustified Absence (predeterminado; cada cuenta puede cambiarlo)"],
  ["publish_preliminary", "Publicar boletas preliminares en el portal en cada corrida previa al cierre"],
  ["require_closed_cutoffs", "Exigir cortes de asistencia cerrados para cerrar la planilla"],
];
const NUMBERS = [
  ["days_per_month", "Días por mes (prima de vacaciones)", "1"],
  ["hours_per_day", "Horas por día (séptimo día)", "0.25"],
  ["overtime_surcharge_percent", "Recargo de horas extra (%)", "0.01"],
  ["vacation_premium_percent", "Prima de vacaciones (%)", "0.01"],
  ["holiday_premium_percent", "Recargo por feriado laborado (%)", "0.01"],
  ["preliminary_lead_days", "Corridas preliminares: días antes del fin del corte", "1"],
];
const SETTLEMENT_NUMBERS = [
  ["minimum_wage_monthly", "Salario mínimo mensual", "0.01"],
  ["indemnity_days_per_year", "Indemnización: días por año", "1"],
  ["indemnity_cap_multiplier", "Indemnización: tope (× mínimo)", "0.01"],
  ["indemnity_min_days", "Indemnización: mínimo (días)", "1"],
  ["resignation_days_per_year", "Renuncia: días por año", "1"],
  ["resignation_cap_multiplier", "Renuncia: tope (× mínimo)", "0.01"],
  ["resignation_min_years", "Renuncia: años mínimos", "1"],
  ["vacation_days_per_year", "Vacaciones: días por año", "1"],
  ["aguinaldo_exempt_multiplier", "Aguinaldo exento de Renta (× mínimo)", "0.01"],
];
const METHOD = { PERCENTAGE: "Porcentaje", BRACKET: "Tabla por tramos", FIXED: "Monto fijo" };
const PARTY = { EMPLOYEE: "Laboral", EMPLOYER: "Patronal" };
const FREQ = { MONTHLY: "Mensual", BIWEEKLY: "Quincenal", WEEKLY: "Semanal" };

/**
 * Parámetros salariales (Fase 20): reglas de cálculo por país y vigencia, retenciones de ley (ISSS, AFP, Renta,
 * INSAFORP) con nuevas vigencias en lugar de ediciones, recargo nocturno (regla del país) y conceptos de la boleta.
 */
export default function PayrollSettingsPage() {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [reload, setReload] = useState(0);
  const [notice, setNotice] = useState(null);
  const [country, setCountry] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    payrollApi
      .settings({ signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [reload]);

  const data = state.data;
  const canManage = data?.can_manage;
  const countryId = Number(country) || data?.settings[0]?.country || data?.countries[0]?.id;
  const done = (promise) =>
    promise
      .then((b) => {
        setNotice({ ok: true, text: b.feedback });
        setReload((k) => k + 1);
      })
      .catch((err) => setNotice({ ok: false, text: err.message }));
  const settings = (data?.settings ?? []).filter((s) => s.country === countryId);
  const types = (data?.deduction_types ?? []).filter((t) => t.country === countryId);
  const night = (data?.night_rules ?? []).filter((r) => r.country === countryId);

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Parámetros salariales</h1>
          <p className="muted page-subtitle">
            Reglas del motor de planilla por país con vigencia. Un cambio de ley se registra como una <strong>nueva vigencia</strong>: las planillas ya
            calculadas conservan la versión que usaron. Valores de referencia de El Salvador: valídelos contra la normativa vigente.
          </p>
        </div>
        {data && data.countries.length > 1 && (
          <label className="field">
            <span className="field__label">País</span>
            <select value={countryId ?? ""} onChange={(e) => setCountry(e.target.value)}>
              {data.countries.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code} · {c.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </header>
      {notice && (
        <div className={`alert ${notice.ok ? "alert--ok" : "alert--error"} flash`} role="status">
          <p className="alert__text">{notice.text}</p>
        </div>
      )}
      {state.error && <p className="error-box">{state.error}</p>}
      {state.loading && !data && <p className="muted">Cargando…</p>}

      {data && (
        <>
          <h2 className="section-title">Reglas de cálculo</h2>
          {settings.length === 0 && <p className="empty">El país no tiene parámetros: cree la primera vigencia.</p>}
          {settings.map((s) => (
            <SettingForm key={`${s.id}-${reload}`} setting={s} canManage={canManage} onSave={(payload) => done(payrollApi.updateSetting(s.id, payload))} />
          ))}
          {canManage && <NewVersion label="Nueva vigencia de parámetros" onCreate={(start, name) => done(payrollApi.createSetting({ country: countryId, effective_start_date: start, name }))} withName />}

          <h2 className="section-title">Retenciones de ley y aportes patronales</h2>
          <div className="table-wrap">
            <table className="table pay-legal">
              <thead>
                <tr>
                  <th scope="col">Retención</th>
                  <th scope="col">Parte</th>
                  <th scope="col">Cálculo</th>
                  <th scope="col">Tope mensual</th>
                  <th scope="col">Vigencia</th>
                  <th scope="col">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {types.map((t) => (
                  <DeductionRow key={t.id} t={t} canManage={canManage} onVersion={(payload) => done(payrollApi.newDeductionVersion(t.id, payload))} />
                ))}
              </tbody>
            </table>
          </div>

          <h2 className="section-title">Recargo nocturno</h2>
          <p className="muted small">
            Se toma de la regla de nocturnidad del país (Horarios): {night.length
              ? night.map((r) => `${r.name}: ${r.start}–${r.end}, +${num(r.surcharge_percent)} % desde ${formatDate(r.effective_start_date)}`).join(" · ")
              : "no hay regla vigente"}
            . Se edita en /admin/ › Reglas de nocturnidad.
          </p>

          <h2 className="section-title">Séptimo día por cuenta</h2>
          <AccountRules canManage={canManage} onNotice={setNotice} />

          <h2 className="section-title">Conceptos de la boleta</h2>
          <div className="table-wrap">
            <table className="table pay-concepts">
              <thead>
                <tr>
                  <th scope="col">Concepto</th>
                  <th scope="col">Tipo</th>
                  <th scope="col">Cálculo / origen</th>
                  <th scope="col">Cotiza ISSS / AFP</th>
                  <th scope="col">Gravado (Renta)</th>
                  <th scope="col">Activo</th>
                </tr>
              </thead>
              <tbody>
                {data.concepts.map((c) => (
                  <tr key={c.code}>
                    <td>
                      <strong>{c.name}</strong>
                      <div className="muted small">{c.code}</div>
                    </td>
                    <td className="small">{c.kind_label}</td>
                    <td className="small">
                      {c.calculation_label}
                      {c.action_type_code && (
                        <div className="muted">
                          AP {c.action_type_code} · campo «{c.action_attribute_key}»
                        </div>
                      )}
                    </td>
                    {["affects_social_security", "affects_income_tax", "is_active"].map((k) => (
                      <td key={k}>
                        <input type="checkbox" aria-label={`${c.name}: ${k}`} checked={c[k]} disabled={!canManage || (c.kind === "DEDUCTION" && k !== "is_active")}
                          onChange={(e) => done(payrollApi.updateConcept(c.code, { [k]: e.target.checked }))} />
                      </td>
                    ))}
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

/** Fase 21: cada cuenta (cliente del roster) decide si aplica la pérdida del séptimo día. */
function AccountRules({ canManage, onNotice }) {
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState(null);
  useEffect(() => {
    const controller = new AbortController();
    payrollApi
      .accountRules({ signal: controller.signal })
      .then((d) => setRows(d.results))
      .catch(() => setRows([]));
    return () => controller.abort();
  }, []);
  const save = (r, patch) => {
    setBusy(r.client_id);
    payrollApi
      .saveAccountRule(r.client_id, patch)
      .then((d) => {
        setRows(d.results);
        onNotice({ ok: true, text: `Regla de la cuenta ${r.client_name} guardada.` });
      })
      .catch((err) => onNotice({ ok: false, text: err.message }))
      .finally(() => setBusy(null));
  };
  if (!rows) return <p className="muted">Cargando cuentas…</p>;
  if (!rows.length) return <p className="muted small">No hay cuentas (clientes) en el catálogo operativo.</p>;
  return (
    <div className="table-wrap">
      <table className="table table--compact pay-accounts">
        <thead>
          <tr>
            <th scope="col">Cuenta</th>
            <th scope="col">Séptimo día</th>
            <th scope="col">Regla</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.client_id}>
              <td>
                <strong>{r.client_name}</strong>
                <div className="muted small">{r.client_code}</div>
              </td>
              <td>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={!!r.seventh_day_penalty}
                    disabled={!canManage || busy === r.client_id}
                    onChange={(e) => save(r, { seventh_day_penalty: e.target.checked, is_active: true })}
                  />
                  <span>{r.seventh_day_penalty ? "Se descuenta" : "No se descuenta"}</span>
                </label>
              </td>
              <td className="small muted">{r.has_rule ? (r.is_active ? "Propia de la cuenta" : "Inactiva (usa el predeterminado)") : "Usa el predeterminado del país"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SettingForm({ setting, canManage, onSave }) {
  const [form, setForm] = useState(setting);
  const locked = !canManage || setting.used_by_closed_payroll;
  const current = setting.effective_start_date <= todayIso() && (!setting.effective_end_date || setting.effective_end_date >= todayIso());
  const dirty = useMemo(() => JSON.stringify(form) !== JSON.stringify(setting), [form, setting]);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  return (
    <form className="pay-setting" onSubmit={(e) => { e.preventDefault(); onSave(form); }}>
      <div className="pay-setting__head">
        <strong>{setting.name}</strong>
        <span className="muted small">
          {formatDate(setting.effective_start_date)} → {setting.effective_end_date ? formatDate(setting.effective_end_date) : "Now"}
        </span>
        {current && <span className="badge badge--ok">Vigente</span>}
        {setting.used_by_closed_payroll && <span className="badge badge--muted" title="Respaldó una planilla cerrada: cree una nueva vigencia">Usada en planillas cerradas</span>}
      </div>
      <div className="pay-setting__grid">
        {NUMBERS.map(([k, label, step]) => (
          <label key={k} className="field">
            <span className="field__label">{label}</span>
            <input type="number" step={step} value={form[k] ?? ""} disabled={locked} onChange={(e) => set(k, e.target.value)} />
          </label>
        ))}
      </div>
      <p className="muted small pay-setting__sub">Liquidaciones e indemnizaciones</p>
      <div className="pay-setting__grid">
        {SETTLEMENT_NUMBERS.map(([k, label, step]) => (
          <label key={k} className="field">
            <span className="field__label">{label}</span>
            <input type="number" step={step} value={form[k] ?? ""} disabled={locked} onChange={(e) => set(k, e.target.value)} />
          </label>
        ))}
      </div>
      <p className="muted small">
        Aguinaldo por antigüedad: {(form.aguinaldo_tiers ?? []).map((t) => `${t.min_years}+ años → ${t.days} días`).join(" · ") || "—"}
      </p>
      <div className="pay-setting__toggles">
        {TOGGLES.map(([k, label]) => (
          <label key={k} className="checkbox">
            <input type="checkbox" checked={!!form[k]} disabled={locked} onChange={(e) => set(k, e.target.checked)} />
            <span>{label}</span>
          </label>
        ))}
      </div>
      <label className="field">
        <span className="field__label">Base legal / política</span>
        <textarea rows={2} maxLength={300} value={form.legal_reference ?? ""} disabled={locked} onChange={(e) => set("legal_reference", e.target.value)} />
      </label>
      {!locked && (
        <button type="submit" className="button button--sm" disabled={!dirty}>
          Guardar parámetros
        </button>
      )}
    </form>
  );
}

function NewVersion({ label, onCreate, withName = false }) {
  const [open, setOpen] = useState(false);
  const [start, setStart] = useState("");
  const [name, setName] = useState("");
  if (!open)
    return (
      <button type="button" className="button button--ghost button--sm" onClick={() => setOpen(true)}>
        {label}
      </button>
    );
  return (
    <form className="pay-inline-form" onSubmit={(e) => { e.preventDefault(); onCreate(start, name); setOpen(false); }}>
      <label className="field">
        <span className="field__label">Vigente desde</span>
        <input type="date" required value={start} onChange={(e) => setStart(e.target.value)} />
      </label>
      {withName && (
        <label className="field">
          <span className="field__label">Nombre</span>
          <input required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
      )}
      <button type="submit" className="button button--sm" disabled={!start}>
        Crear (copia la vigencia anterior)
      </button>
      <button type="button" className="link-button" onClick={() => setOpen(false)}>
        Cancelar
      </button>
    </form>
  );
}

function DeductionRow({ t, canManage, onVersion }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ effective_start_date: "", rate: t.rate ?? "", base_cap: t.base_cap ?? "", fixed_amount: t.fixed_amount ?? "",
    brackets: t.brackets.map((b) => ({ ...b, upper_bound: b.upper_bound ?? "" })) });
  const closed = t.effective_end_date && t.effective_end_date < todayIso();
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const setBracket = (i, k, v) => setForm((f) => ({ ...f, brackets: f.brackets.map((b, j) => (j === i ? { ...b, [k]: v } : b)) }));
  const submit = (e) => {
    e.preventDefault();
    const payload = { effective_start_date: form.effective_start_date };
    if (t.method === "PERCENTAGE") Object.assign(payload, { rate: form.rate, base_cap: form.base_cap || null });
    if (t.method === "FIXED") payload.fixed_amount = form.fixed_amount;
    if (t.method === "BRACKET") payload.brackets = form.brackets.map((b) => ({ ...b, upper_bound: b.upper_bound === "" ? null : b.upper_bound }));
    onVersion(payload);
    setOpen(false);
  };
  return (
    <>
      <tr className={closed ? "is-muted" : ""}>
        <td>
          <strong>{t.name}</strong>
          <div className="muted small">
            {t.code}
            {t.reduces_taxable_base ? " · reduce la base de Renta" : ""}
          </div>
        </td>
        <td className="small">{PARTY[t.party]}</td>
        <td className="small">
          {METHOD[t.method]}
          {t.method === "PERCENTAGE" && ` · ${pct(t.rate)}`}
          {t.method === "FIXED" && ` · ${num(t.fixed_amount)}`}
          {t.method === "BRACKET" && (
            <ul className="pay-brackets">
              {t.brackets.map((b) => (
                <li key={b.id}>
                  {FREQ[b.pay_frequency]}: {num(b.lower_bound)}–{b.upper_bound ? num(b.upper_bound) : "∞"} → {num(b.fixed_fee)} + {pct(b.rate)} s/ exceso de{" "}
                  {num(b.excess_over)}
                </li>
              ))}
            </ul>
          )}
        </td>
        <td className="small">{t.base_cap ? num(t.base_cap) : "—"}</td>
        <td className="small">
          {formatDate(t.effective_start_date)} → {t.effective_end_date ? formatDate(t.effective_end_date) : "Now"}
        </td>
        <td>
          {canManage && !closed && (
            <button type="button" className="button button--ghost button--sm" onClick={() => setOpen((v) => !v)}>
              Nueva vigencia
            </button>
          )}
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={6}>
            <form className="pay-inline-form" onSubmit={submit}>
              <label className="field">
                <span className="field__label">Vigente desde</span>
                <input type="date" required value={form.effective_start_date} onChange={(e) => set("effective_start_date", e.target.value)} />
              </label>
              {t.method === "PERCENTAGE" && (
                <>
                  <label className="field">
                    <span className="field__label">Tasa (0.03 = 3 %)</span>
                    <input type="number" step="0.000001" min="0" max="1" required value={form.rate} onChange={(e) => set("rate", e.target.value)} />
                  </label>
                  <label className="field">
                    <span className="field__label">Tope mensual de la base</span>
                    <input type="number" step="0.01" min="0" value={form.base_cap} onChange={(e) => set("base_cap", e.target.value)} />
                  </label>
                </>
              )}
              {t.method === "FIXED" && (
                <label className="field">
                  <span className="field__label">Monto mensual</span>
                  <input type="number" step="0.01" min="0" required value={form.fixed_amount} onChange={(e) => set("fixed_amount", e.target.value)} />
                </label>
              )}
              {t.method === "BRACKET" && (
                <table className="table pay-bracket-edit">
                  <thead>
                    <tr>
                      <th scope="col">Frecuencia</th>
                      <th scope="col">Desde</th>
                      <th scope="col">Hasta</th>
                      <th scope="col">Tasa</th>
                      <th scope="col">Cuota fija</th>
                      <th scope="col">Exceso sobre</th>
                    </tr>
                  </thead>
                  <tbody>
                    {form.brackets.map((b, i) => (
                      <tr key={i}>
                        <td>{FREQ[b.pay_frequency]}</td>
                        {["lower_bound", "upper_bound", "rate", "fixed_fee", "excess_over"].map((k) => (
                          <td key={k}>
                            <input type="number" step={k === "rate" ? "0.000001" : "0.01"} aria-label={`${FREQ[b.pay_frequency]} tramo ${i + 1} ${k}`} value={b[k] ?? ""}
                              onChange={(e) => setBracket(i, k, e.target.value)} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <button type="submit" className="button button--sm" disabled={!form.effective_start_date}>
                Crear vigencia
              </button>
            </form>
          </td>
        </tr>
      )}
    </>
  );
}
