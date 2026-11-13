import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { leadersApi } from "../api.js";

/**
 * Cadena de mando en el ROSTER (Fase 18; antes WFM › Jerarquía operativa): Operations Director → Operations Manager →
 * Account Supervisor → Team Manager. Cada líder es un colaborador y reporta a un líder del nivel inmediato superior.
 * Al agente se le asigna su Team Manager en su roster (atributo «Team Manager», con fechas); los niveles superiores
 * se derivan de esta cadena y alimentan los filtros y la grilla de WFM y la consulta de roster.
 */
export default function ChainOfCommandPage() {
  const [params] = useSearchParams();
  const focus = (params.get("employee") ?? "").toUpperCase();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [showInactive, setShowInactive] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [editing, setEditing] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    leadersApi
      .list({ include_inactive: showInactive ? 1 : "" }, { signal: controller.signal })
      .then(setData)
      .catch((err) => err.name !== "AbortError" && setError(err.message));
    return () => controller.abort();
  }, [showInactive, reloadKey]);

  const done = useCallback((b) => {
    setNotice({ ok: true, text: b.feedback });
    setEditing(null);
    setReloadKey((k) => k + 1);
  }, []);
  const fail = useCallback((err) => setNotice({ ok: false, text: err.message, errors: err.body?.errors }), []);

  const leaders = useMemo(() => data?.results ?? [], [data]);
  const children = useMemo(() => {
    const map = new Map();
    leaders.forEach((l) => map.set(l.reports_to_id ?? 0, [...(map.get(l.reports_to_id ?? 0) ?? []), l]));
    return map;
  }, [leaders]);
  const levelLabel = (v) => data?.levels.find((l) => l.value === v)?.label ?? v;
  const ctx = { children, levelLabel, canManage: Boolean(data?.can_manage), editing, setEditing, leaders, data, done, fail, focus };
  const roots = leaders.filter((l) => !l.reports_to_id || !leaders.some((x) => x.id === l.reports_to_id));

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Cadena de mando</h1>
          <p className="muted page-subtitle">
            Operations Director → Operations Manager → Account Supervisor → Team Manager. Es parte del roster: el Team Manager de cada agente se asigna en su
            roster (con fechas, en el expediente › Roster) y el resto de la cadena se deriva de aquí; alimenta los filtros y la grilla de WFM y la{" "}
            <Link to="/roster/report">consulta de roster</Link>.
          </p>
        </div>
        <label className="checkbox">
          <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} /> Mostrar inactivos
        </label>
      </header>
      {error && <p className="error-box">{error}</p>}
      {notice && (
        <div className={`alert ${notice.ok ? "alert--ok" : "alert--error"} flash`} role="status">
          <p className="alert__text">{notice.text}</p>
        </div>
      )}
      {data?.can_manage && <LeaderNew data={data} leaders={leaders} employeeCode={focus} onDone={done} onError={fail} />}
      {data && leaders.length === 0 && <p className="empty">Aún no hay líderes registrados.</p>}
      {roots.length > 0 && (
        <ul className="org">
          {roots.map((l) => (
            <OrgNode key={l.id} lead={l} ctx={ctx} />
          ))}
        </ul>
      )}
    </section>
  );
}

function OrgNode({ lead, ctx }) {
  const { children, levelLabel, canManage, editing, setEditing, leaders, data, done, fail, focus } = ctx;
  const kids = children.get(lead.id) ?? [];
  return (
    <li className={`org__node${lead.is_active ? "" : " is-inactive"}${focus && focus === lead.employee_code ? " is-focus" : ""}`}>
      <div className="org__card">
        <span className={`org__level org__level--${lead.level.toLowerCase()}`}>{levelLabel(lead.level)}</span>
        <Link to={`/hcm/employees/${lead.employee_code}?tab=roster`}>
          <strong>{lead.full_name}</strong>
        </Link>
        <span className="muted small">
          {lead.employee_code}
          {lead.client_name ? ` · ${lead.client_name}` : ""}
          {lead.agents !== undefined ? ` · ${lead.agents} agente(s) hoy` : ""}
          {!lead.is_active ? " · inactivo" : ""}
        </span>
        {canManage && (
          <button type="button" className="link-button" onClick={() => setEditing(editing === lead.id ? null : lead.id)}>
            {editing === lead.id ? "Cerrar" : "Editar"}
          </button>
        )}
        {editing === lead.id && <LeaderEdit lead={lead} leaders={leaders} data={data} onDone={done} onError={fail} />}
      </div>
      {kids.length > 0 && (
        <ul className="org__children">
          {kids.map((c) => (
            <OrgNode key={c.id} lead={c} ctx={ctx} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function bossesFor(level, data, leaders) {
  const parent = data.levels.find((l) => l.value === level)?.parent;
  return parent ? leaders.filter((l) => l.level === parent && l.is_active) : [];
}

/** Alta de un líder. `employeeCode` fija el colaborador (alta desde su roster). */
export function LeaderNew({ data, leaders, employeeCode = "", fixedEmployee = false, title = "Registrar líder", onDone, onError }) {
  const [form, setForm] = useState({ level: "OPS_DIRECTOR", employee_code: employeeCode, reports_to: "", client: "" });
  const [busy, setBusy] = useState(false);
  const bosses = bossesFor(form.level, data, leaders);
  const submit = (e) => {
    e.preventDefault();
    setBusy(true);
    leadersApi
      .create({ ...form, reports_to: form.reports_to ? Number(form.reports_to) : null })
      .then((b) => {
        if (!fixedEmployee) setForm((f) => ({ ...f, employee_code: "" }));
        onDone(b);
      })
      .catch(onError)
      .finally(() => setBusy(false));
  };
  return (
    <form className="form-section" onSubmit={submit}>
      <h2 className="form-section__title">{title}</h2>
      <div className="adh-new__grid">
        <label className="field">
          <span className="field__label">Nivel</span>
          <select value={form.level} onChange={(e) => setForm({ ...form, level: e.target.value, reports_to: "" })}>
            {data.levels.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
        </label>
        {!fixedEmployee && (
          <label className="field">
            <span className="field__label">Colaborador (ID corporativo)</span>
            <input required value={form.employee_code} placeholder="SV-2026-000001-7" onChange={(e) => setForm({ ...form, employee_code: e.target.value.toUpperCase() })} />
          </label>
        )}
        <label className="field">
          <span className="field__label">Reporta a</span>
          <select value={form.reports_to} disabled={form.level === "OPS_DIRECTOR"} required={form.level !== "OPS_DIRECTOR"}
            onChange={(e) => setForm({ ...form, reports_to: e.target.value })}>
            <option value="">{form.level === "OPS_DIRECTOR" ? "— (nivel superior)" : bosses.length ? "Elija…" : "Registre primero el nivel superior"}</option>
            {bosses.map((b) => (
              <option key={b.id} value={b.id}>
                {b.full_name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Cuenta (opcional)</span>
          <select value={form.client} onChange={(e) => setForm({ ...form, client: e.target.value })}>
            <option value="">—</option>
            {data.clients.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="form-actions form-actions--start">
        <button type="submit" className="button button--sm" disabled={busy}>
          Registrar
        </button>
      </div>
    </form>
  );
}

export function LeaderEdit({ lead, leaders, data, onDone, onError }) {
  const [form, setForm] = useState({ reports_to: lead.reports_to_id ?? "", client: lead.client ?? "", is_active: lead.is_active });
  const [busy, setBusy] = useState(false);
  const bosses = bossesFor(lead.level, data, leaders);
  const submit = (e) => {
    e.preventDefault();
    setBusy(true);
    leadersApi
      .update(lead.id, { ...form, reports_to: form.reports_to ? Number(form.reports_to) : null })
      .then(onDone)
      .catch(onError)
      .finally(() => setBusy(false));
  };
  return (
    <form className="org__edit" onSubmit={submit}>
      {lead.level !== "OPS_DIRECTOR" && (
        <select value={form.reports_to} aria-label="Reporta a" onChange={(e) => setForm({ ...form, reports_to: e.target.value })}>
          {bosses.map((b) => (
            <option key={b.id} value={b.id}>
              {b.full_name}
            </option>
          ))}
        </select>
      )}
      <select value={form.client} aria-label="Cuenta" onChange={(e) => setForm({ ...form, client: e.target.value })}>
        <option value="">Sin cuenta</option>
        {data.clients.map((c) => (
          <option key={c.code} value={c.code}>
            {c.name}
          </option>
        ))}
      </select>
      <label className="checkbox">
        <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} /> Activo
      </label>
      <button type="submit" className="button button--sm" disabled={busy}>
        Guardar
      </button>
    </form>
  );
}
