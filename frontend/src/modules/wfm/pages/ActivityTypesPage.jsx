import { useCallback, useEffect, useState } from "react";
import { adhApi } from "../api.js";

const EMPTY = { code: "", name: "", category: "OTHER", color: "#64748b", is_paid: true, is_billable: false, is_default: false, default_minutes: "",
  description: "", is_active: true, sort_order: 100, rules: [{ primary_status: "ON_QUEUE", aux_code: "", role: "PRIMARY" }] };

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
      {catalogs && editing === "new" && <ActivityForm catalogs={catalogs} initial={EMPTY} isNew onDone={done} onError={fail} onCancel={() => setEditing(null)} />}
      {catalogs && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Actividad</th>
                <th>Categoría</th>
                <th>Estados ACD que la cumplen</th>
                <th>Pago / billing</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {catalogs.activities.map((a) =>
                editing === a.code ? (
                  <tr key={a.code}>
                    <td colSpan={5}>
                      <ActivityForm catalogs={catalogs} initial={{ ...a, default_minutes: a.default_minutes ?? "", rules: a.rules.map((r) => ({ ...r, aux_code: r.aux_code ?? "" })) }}
                        onDone={done} onError={fail} onCancel={() => setEditing(null)} />
                    </td>
                  </tr>
                ) : (
                  <tr key={a.code} className={a.is_active ? "" : "muted"}>
                    <td>
                      <span className="adh-swatch" style={{ background: a.color }} aria-hidden="true" /> <strong>{a.name}</strong>
                      <div className="muted small">
                        {a.code}
                        {a.default_minutes ? ` · ${a.default_minutes} min sugeridos` : ""}
                        {a.is_default && <span className="badge badge--info"> Predeterminada del contenedor</span>}
                        {!a.is_active && " · inactiva"}
                      </div>
                    </td>
                    <td>{a.category_label}</td>
                    <td>
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
                      {a.is_paid ? "Pagada" : "No pagada"}
                      {a.is_billable ? " · facturable" : ""}
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
  const submit = (e) => {
    e.preventDefault();
    setBusy(true);
    const payload = { ...form, default_minutes: form.default_minutes === "" ? null : Number(form.default_minutes),
      rules: form.rules.map((r) => ({ primary_status: r.primary_status, aux_code: r.aux_code || null, role: r.role })) };
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
          <span className="field__label">Color</span>
          <input type="color" value={form.color} onChange={(e) => set("color", e.target.value)} />
        </label>
        <label className="field">
          <span className="field__label">Duración sugerida (min)</span>
          <input type="number" min={1} max={720} value={form.default_minutes} onChange={(e) => set("default_minutes", e.target.value)} />
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
