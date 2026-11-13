import { useCallback, useEffect, useMemo, useState } from "react";
import { adhApi, durationText, fmtDuration, parseDuration } from "../api.js";
import ActivityIcon from "../components/ActivityIcon.jsx";

const EMPTY = { code: "", name: "", category: "OTHER", color: "#64748b", is_paid: true, is_billable: false, is_default: false, duration: "",
  description: "", is_active: true, sort_order: 100, icon: "clock", clients: [], rules: [{ primary_status: "ON_QUEUE", aux_code: "", role: "PRIMARY" }],
  utilization_category: "", requires_acd_login: true, allows_full_day: false, allows_partial: true, requires_ap: false, client_paid: "NONE",
  review_areas: [] };
const FLAGS = [
  ["requires_acd_login", "Requiere sesión en el ACD"],
  ["allows_full_day", "Puede cubrir el día completo"],
  ["allows_partial", "Puede ser parcial"],
  ["requires_ap", "Requiere AP aprobada (respaldo legal)"],
];
const SYSTEM_LABELS = { LATENESS: "Lateness (automático)", ABSENCE: "Unjustified Absence (automático)", LEGAL_LUNCH: "Legal Benefit Lunch (automático)" };

/** Actividad del API → valores del formulario. */
const toForm = (a) => ({ ...a, duration: durationText(a.default_seconds), utilization_category: a.utilization_category?.code ?? "",
  rules: a.rules.map((r) => ({ ...r, aux_code: r.aux_code ?? "" })) });

/**
 * Actividades (segmentos preconfigurados): qué estados / auxiliares del ACD cumplen cada una y con qué rol. El auxiliar
 * PRIMARIO es el trabajo principal (llamadas, chats, tickets, back office); el SECUNDARIO es un auxiliar pagado por
 * diseño del segmento (p. ej. ACW dentro de Producción). La actividad predeterminada rellena el resto del turno.
 */
export default function ActivityTypesPage() {
  const [catalogs, setCatalogs] = useState(null);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null); // código o "new"
  const [notice, setNotice] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    adhApi.catalogs({ signal: controller.signal }).then(setCatalogs).catch((err) => err.name !== "AbortError" && setError(err.message));
    return () => controller.abort();
  }, [reloadKey]);

  const done = useCallback((b) => {
    setNotice({ ok: true, text: b.feedback });
    setEditing(null);
    setReloadKey((k) => k + 1);
  }, []);
  const fail = useCallback((err) => setNotice({ ok: false, text: err.message }), []);
  const canManage = catalogs?.can_manage;
  // Fase 19: el catálogo del Time Utilization es largo: filtro por categoría (segmento principal) y búsqueda.
  const [category, setCategory] = useState("");
  const [search, setSearch] = useState("");
  const shown = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (catalogs?.activities ?? []).filter((a) =>
      (!category || (category === "-" ? !a.utilization_category : a.utilization_category?.code === category))
      && (!q || a.name.toLowerCase().includes(q) || a.code.toLowerCase().includes(q)));
  }, [catalogs, category, search]);

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Actividades (segmentos)</h1>
          <p className="muted page-subtitle">
            Segmentos que WFM inserta en el turno y los estados del ACD que los cumplen. Pagada = el tiempo programado se paga; facturable = el tiempo en
            adherencia se factura al cliente.
          </p>
        </div>
        {canManage && editing !== "new" && (
          <button type="button" className="button button--ghost" onClick={() => setEditing("new")}>
            + Nueva actividad
          </button>
        )}
      </header>
      {error && <p className="error-box">{error}</p>}
      {notice && (
        <div className={`alert ${notice.ok ? "alert--ok" : "alert--error"} flash`} role="status">
          <p className="alert__text">{notice.text}</p>
        </div>
      )}
      {catalogs && editing === "new" && <ActivityForm catalogs={catalogs} initial={{ ...EMPTY, utilization_category: category === "-" ? "" : category }}
        isNew onDone={done} onError={fail} onCancel={() => setEditing(null)} />}
      {catalogs && (
        <div className="filters" role="search">
          <label className="field">
            <span className="field__label">Categoría (Time Utilization)</span>
            <select value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">Todas ({catalogs.activities.length})</option>
              {catalogs.utilization_categories.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.department_label} › {c.name} ({catalogs.activities.filter((a) => a.utilization_category?.code === c.code).length})
                </option>
              ))}
              <option value="-">Sin categoría</option>
            </select>
          </label>
          <label className="field filters__search">
            <span className="field__label">Buscar</span>
            <input type="search" value={search} placeholder="Nombre o código" onChange={(e) => setSearch(e.target.value)} />
          </label>
        </div>
      )}
      {catalogs && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Actividad</th>
                <th>Categoría</th>
                <th>Estados ACD que la cumplen</th>
                <th>Reglas</th>
                <th>Pago / billing</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {shown.length === 0 && (
                <tr>
                  <td colSpan={6} className="empty">
                    No hay actividades con ese filtro.
                  </td>
                </tr>
              )}
              {shown.map((a) =>
                editing === a.code ? (
                  <tr key={a.code}>
                    <td colSpan={6}>
                      <ActivityForm catalogs={catalogs} initial={toForm(a)} onDone={done} onError={fail} onCancel={() => setEditing(null)} />
                    </td>
                  </tr>
                ) : (
                  <tr key={a.code} className={a.is_active ? "" : "muted"}>
                    <td>
                      <span className="adh-icon-swatch" style={{ background: a.color }} aria-hidden="true">
                        <ActivityIcon name={a.icon} size={14} />
                      </span>{" "}
                      <strong>{a.name}</strong>
                      <div className="muted small">
                        {a.code}
                        {a.default_seconds ? ` · ${fmtDuration(a.default_seconds)} sugeridos` : ""}
                        {a.is_default && <span className="badge badge--info"> Predeterminada del contenedor</span>}
                        {!a.is_active && " · inactiva"}
                        {a.clients.length > 0 && ` · solo ${a.clients.join(", ")}`}
                      </div>
                    </td>
                    <td>
                      {a.utilization_category ? (
                        <>
                          {a.utilization_category.name}
                          <div className="muted small">{a.utilization_category.department_label}</div>
                        </>
                      ) : (
                        <span className="muted">—</span>
                      )}
                      <div className="muted small">{a.category_label}</div>
                    </td>
                    <td>
                      {!a.requires_acd_login && <span className="muted small">No requiere sesión ACD</span>}
                      <ul className="adh-rules">
                        {a.rules.map((r) => (
                          <li key={r.id}>
                            <span className={`badge ${r.role === "PRIMARY" ? "badge--ok" : "badge--info"}`}>{r.role === "PRIMARY" ? "Primario" : "Secundario pagado"}</span>{" "}
                            {r.primary_label}
                            {r.aux_name ? ` · ${r.aux_name}` : " (cualquier auxiliar)"}
                          </li>
                        ))}
                      </ul>
                    </td>
                    <td>
                      <span className="adh-flag-list">
                        {a.system_role && <span className="badge badge--warn">{SYSTEM_LABELS[a.system_role]}</span>}
                        {a.requires_ap && <span className="badge badge--error">Requiere AP</span>}
                        {a.allows_full_day && <span className="badge badge--info">{a.allows_partial ? "Parcial o día completo" : "Solo día completo"}</span>}
                        {a.review_areas.length > 0 && <span className="muted small">Revisan: {a.review_areas.join(", ")}</span>}
                      </span>
                    </td>
                    <td>
                      {a.is_paid ? "Pagada" : "No pagada"}
                      {a.is_billable ? " · facturable" : ""}
                      {a.client_paid !== "NONE" && <div className="muted small">{a.client_paid_label}</div>}
                    </td>
                    <td>
                      {canManage && (
                        <button type="button" className="link-button" onClick={() => setEditing(a.code)}>
                          Editar
                        </button>
                      )}
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function ActivityForm({ catalogs, initial, isNew = false, onDone, onError, onCancel }) {
  const [form, setForm] = useState(initial);
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const setRule = (i, changes) => setForm((f) => ({ ...f, rules: f.rules.map((r, j) => (j === i ? { ...r, ...changes } : r)) }));
  const seconds = parseDuration(form.duration);
  const isSystem = Boolean(form.system_role);
  const durationError = form.duration.trim() !== "" && (seconds === null || seconds < 60 || seconds > 43200);
  const submit = (e) => {
    e.preventDefault();
    if (durationError) return;
    setBusy(true);
    const { duration, ...rest } = form;
    const payload = { ...rest, default_seconds: duration.trim() === "" ? null : seconds,
      rules: form.requires_acd_login ? form.rules.map((r) => ({ primary_status: r.primary_status, aux_code: r.aux_code || null, role: r.role })) : [] };
    if (isSystem) delete payload.rules;
    (isNew ? adhApi.createActivity(payload) : adhApi.updateActivity(form.code, payload)).then(onDone).catch(onError).finally(() => setBusy(false));
  };
  return (
    <form className="form-section" onSubmit={submit}>
      <div className="form-grid">
        <label className="field">
          <span className="field__label">Código</span>
          <input required disabled={!isNew} value={form.code} onChange={(e) => set("code", e.target.value.toUpperCase())} placeholder="CHATS" />
        </label>
        <label className="field">
          <span className="field__label">Nombre</span>
          <input required value={form.name} onChange={(e) => set("name", e.target.value)} />
        </label>
        <label className="field">
          <span className="field__label">Categoría</span>
          <select value={form.category} onChange={(e) => set("category", e.target.value)}>
            {catalogs.categories.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Categoría del Time Utilization</span>
          <select value={form.utilization_category} onChange={(e) => set("utilization_category", e.target.value)}>
            <option value="">— Sin categoría —</option>
            {catalogs.utilization_categories.map((c) => (
              <option key={c.code} value={c.code}>
                {c.department_label} › {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Pagado por el cliente</span>
          <select value={form.client_paid} onChange={(e) => set("client_paid", e.target.value)}>
            {catalogs.client_paid.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Color</span>
          <input type="color" value={form.color} onChange={(e) => set("color", e.target.value)} />
        </label>
        <label className="field">
          <span className="field__label">Duración sugerida (HH:MM:SS)</span>
          <input value={form.duration} inputMode="numeric" placeholder="00:15:00" aria-invalid={durationError}
            onChange={(e) => set("duration", e.target.value)} />
          <small className={durationError ? "field__error" : "field__hint"}>
            {durationError ? "De 00:01:00 a 12:00:00." : seconds ? `= ${fmtDuration(seconds)} (al segundo)` : "Vacío = 30 min al soltarla en la grilla."}
          </small>
        </label>
        <label className="field">
          <span className="field__label">Icono (barra de segmentos)</span>
          <span className="adh-icon-pick">
            <span className="adh-icon-swatch" style={{ background: form.color }} aria-hidden="true">
              <ActivityIcon name={form.icon} size={14} />
            </span>
            <select value={form.icon} onChange={(e) => set("icon", e.target.value)}>
              {(catalogs.icons ?? []).map((i) => (
                <option key={i.value} value={i.value}>
                  {i.label}
                </option>
              ))}
            </select>
          </span>
        </label>
        <label className="field">
          <span className="field__label">Orden</span>
          <input type="number" min={0} value={form.sort_order} onChange={(e) => set("sort_order", e.target.value)} />
        </label>
      </div>
      <div className="adh-flags">
        {[["is_paid", "Tiempo pagado"], ["is_billable", "Facturable (billing)"], ["is_default", "Predeterminada del contenedor"], ["is_active", "Activa"]].map(([k, label]) => (
          <label key={k} className="checkbox">
            <input type="checkbox" checked={Boolean(form[k])} onChange={(e) => set(k, e.target.checked)} /> {label}
          </label>
        ))}
      </div>
      <div className="adh-flags" aria-label="Matriz del Time Utilization">
        {FLAGS.map(([k, label]) => (
          <label key={k} className="checkbox">
            <input type="checkbox" checked={Boolean(form[k])} disabled={isSystem && k !== "allows_full_day" && k !== "allows_partial"}
              onChange={(e) => set(k, e.target.checked)} /> {label}
          </label>
        ))}
      </div>
      <fieldset className="adh-rule-editor">
        <legend className="field__label">Áreas que revisan</legend>
        <div className="adh-flags">
          {catalogs.review_areas.map((r) => (
            <label key={r.value} className="checkbox" title={r.label}>
              <input type="checkbox" checked={form.review_areas.includes(r.value)}
                onChange={(e) => set("review_areas", e.target.checked ? [...form.review_areas, r.value] : form.review_areas.filter((x) => x !== r.value))} />{" "}
              {r.value}
            </label>
          ))}
        </div>
      </fieldset>
      {(catalogs.clients ?? []).length > 0 && (
        <fieldset className="adh-rule-editor">
          <legend className="field__label">Cuentas donde se ofrece en la barra de segmentos (ninguna marcada = todas)</legend>
          <div className="adh-flags">
            {catalogs.clients.map((c) => (
              <label key={c.code} className="checkbox">
                <input type="checkbox" checked={form.clients.includes(c.code)}
                  onChange={(e) => set("clients", e.target.checked ? [...form.clients, c.code] : form.clients.filter((x) => x !== c.code))} /> {c.name}
              </label>
            ))}
          </div>
        </fieldset>
      )}
      {form.requires_acd_login && !isSystem && (
      <fieldset className="adh-rule-editor">
        <legend className="field__label">Estados ACD que cumplen la actividad</legend>
        {form.rules.map((r, i) => (
          <div key={i} className="adh-rule-editor__row">
            <select value={r.primary_status} aria-label="Estado primario" onChange={(e) => setRule(i, { primary_status: e.target.value, aux_code: "" })}>
              {catalogs.primary_statuses.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.label} — {s.name}
                </option>
              ))}
            </select>
            <select value={r.aux_code} aria-label="Auxiliar" onChange={(e) => setRule(i, { aux_code: e.target.value })}>
              <option value="">Cualquier auxiliar</option>
              {catalogs.aux_codes.filter((a) => a.primary_status === r.primary_status).map((a) => (
                <option key={a.code} value={a.code}>
                  {a.name}
                </option>
              ))}
            </select>
            <select value={r.role} aria-label="Rol" onChange={(e) => setRule(i, { role: e.target.value })}>
              {catalogs.roles.map((x) => (
                <option key={x.value} value={x.value}>
                  {x.label}
                </option>
              ))}
            </select>
            <button type="button" className="link-button" onClick={() => setForm((f) => ({ ...f, rules: f.rules.filter((_, j) => j !== i) }))}>
              Quitar
            </button>
          </div>
        ))}
        <button type="button" className="button button--ghost button--sm"
          onClick={() => setForm((f) => ({ ...f, rules: [...f.rules, { primary_status: catalogs.primary_statuses[0]?.code ?? "", aux_code: "", role: "PRIMARY" }] }))}>
          + Agregar estado
        </button>
      </fieldset>
      )}
      <div className="form-actions form-actions--start">
        <button type="submit" className="button button--sm" disabled={busy}>
          {isNew ? "Crear" : "Guardar"}
        </button>
        <button type="button" className="link-button" onClick={onCancel}>
          Cancelar
        </button>
      </div>
    </form>
  );
}
