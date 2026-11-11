import { useCallback, useEffect, useMemo, useState } from "react";
import { acdApi } from "../api.js";

/**
 * Grupos / perfiles de agentes (WFM): división, auxiliares permitidos y agentes del grupo. Un auxiliar «restringido»
 * solo lo ven los grupos con acceso; dar acceso al auxiliar padre incluye sus sub-auxiliares. Los estados operativos
 * y el catálogo de auxiliares se parametrizan en /admin/ › Estados y auxiliares ACD.
 */
export default function AcdGroupsPage() {
  const [catalogs, setCatalogs] = useState(null);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    acdApi
      .catalogs({ signal: controller.signal })
      .then((data) => {
        setCatalogs(data);
        setSelected((s) => s || data.groups[0]?.code || "");
      })
      .catch((err) => err.name !== "AbortError" && setError(err.message));
    return () => controller.abort();
  }, [reloadKey]);

  const canManage = catalogs?.can_manage;
  const done = useCallback((body) => {
    setNotice({ ok: true, text: body.feedback });
    setReloadKey((k) => k + 1);
  }, []);
  const fail = useCallback((err) => setNotice({ ok: false, text: err.message }), []);

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Grupos y auxiliares</h1>
          <p className="muted page-subtitle">
            Qué auxiliares ve y usa cada grupo de agentes. Los estados operativos (Available, On Queue, Break, Meal…) y el catálogo de auxiliares /
            sub-auxiliares se parametrizan en /admin/ › Estados y auxiliares ACD.
          </p>
        </div>
      </header>
      {error && <p className="error-box">{error}</p>}
      {notice && (
        <div className={`alert ${notice.ok ? "alert--ok" : "alert--error"} flash`} role="status">
          <p className="alert__text">{notice.text}</p>
        </div>
      )}
      {catalogs && (
        <div className="acd-groups">
          <nav className="acd-groups__list" aria-label="Grupos">
            {catalogs.groups.map((g) => (
              <button
                key={g.code}
                type="button"
                className={`acd-groups__item${g.code === selected ? " acd-groups__item--active" : ""}`}
                onClick={() => setSelected(g.code)}
                aria-current={g.code === selected}
              >
                <strong>{g.name}</strong>
                <span className="muted small">
                  {g.code} · {g.division.name} · {g.members_count} agente(s){g.is_active ? "" : " · inactivo"}
                </span>
              </button>
            ))}
            {canManage && <NewGroup divisions={catalogs.divisions} onDone={(b) => { done(b); setSelected(b.group.code); }} onError={fail} />}
          </nav>
          {selected && (
            <GroupDetail key={`${selected}-${reloadKey}`} code={selected} catalogs={catalogs} canManage={canManage} onDone={done} onError={fail} />
          )}
        </div>
      )}
    </section>
  );
}

function NewGroup({ divisions, onDone, onError }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ code: "", name: "", division: divisions[0]?.code ?? "" });
  if (!open)
    return (
      <button type="button" className="button button--ghost button--sm" onClick={() => setOpen(true)}>
        + Nuevo grupo
      </button>
    );
  const submit = (e) => {
    e.preventDefault();
    acdApi.createGroup(form).then((b) => { setOpen(false); onDone(b); }).catch(onError);
  };
  return (
    <form className="form-section" onSubmit={submit}>
      <label className="field">
        <span className="field__label">Código</span>
        <input required value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })} placeholder="CAMPANA_X" />
      </label>
      <label className="field">
        <span className="field__label">Nombre</span>
        <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      </label>
      <label className="field">
        <span className="field__label">División</span>
        <select value={form.division} onChange={(e) => setForm({ ...form, division: e.target.value })}>
          {divisions.filter((d) => d.is_active).map((d) => (
            <option key={d.code} value={d.code}>
              {d.name}
            </option>
          ))}
        </select>
      </label>
      <div className="form-actions form-actions--start">
        <button type="submit" className="button button--sm">Crear</button>
        <button type="button" className="link-button" onClick={() => setOpen(false)}>Cancelar</button>
      </div>
    </form>
  );
}

function GroupDetail({ code, catalogs, canManage, onDone, onError }) {
  const [state, setState] = useState({ loading: true, data: null });
  const [access, setAccess] = useState(new Set());
  const [memberCode, setMemberCode] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    acdApi
      .group(code, { signal: controller.signal })
      .then((data) => {
        setState({ loading: false, data });
        setAccess(new Set(data.group.aux_codes));
      })
      .catch((err) => err.name !== "AbortError" && onError(err));
    return () => controller.abort();
  }, [code, onError]);

  const tree = useMemo(() => {
    const byPrimary = new Map();
    for (const st of catalogs.primary_statuses) byPrimary.set(st.code, { status: st, roots: [] });
    const roots = catalogs.aux_codes.filter((a) => !a.parent);
    for (const a of roots) byPrimary.get(a.primary_status)?.roots.push({ ...a, children: catalogs.aux_codes.filter((c) => c.parent === a.code) });
    return [...byPrimary.values()].filter((x) => x.roots.length);
  }, [catalogs]);

  const g = state.data?.group;
  if (!g) return <p className="muted">Cargando grupo…</p>;
  const original = new Set(g.aux_codes);
  const dirty = access.size !== original.size || [...access].some((c) => !original.has(c));
  const toggle = (c) => {
    const next = new Set(access);
    if (next.has(c)) next.delete(c);
    else next.add(c);
    setAccess(next);
  };
  const save = () => {
    setSaving(true);
    acdApi.updateGroup(code, { aux_codes: [...access] }).then(onDone).catch(onError).finally(() => setSaving(false));
  };
  const visible = (a, parentGranted = false) => !a.is_restricted || access.has(a.code) || parentGranted;

  return (
    <div className="acd-groups__detail">
      <h2 className="section-title">
        {g.name} <code className="small">{g.code}</code>
      </h2>
      <p className="muted small">
        División: {g.division.name} (<code>{g.division.id}</code>){g.description ? ` · ${g.description}` : ""}
      </p>

      <h3 className="form-section__title">Auxiliares</h3>
      <div className="acd-access">
        {tree.map(({ status, roots }) => (
          <fieldset key={status.code} className="acd-access__status">
            <legend>
              <span className="acd-pill" style={{ "--status-color": status.color }}>{status.label}</span> {status.name}
            </legend>
            {roots.map((a) => (
              <div key={a.code} className="acd-access__aux">
                <label>
                  <input type="checkbox" disabled={!canManage || !a.is_restricted} checked={visible(a)} onChange={() => toggle(a.code)} />{" "}
                  {a.name} {!a.is_restricted && <span className="badge badge--muted shift-grid__badge">todos los grupos</span>}
                  {!a.is_active && <span className="badge badge--warn shift-grid__badge">inactivo</span>}
                </label>
                {a.children.length > 0 && (
                  <div className="acd-access__children">
                    {a.children.map((c) => (
                      <label key={c.code}>
                        <input
                          type="checkbox"
                          disabled={!canManage || !c.is_restricted || access.has(a.code)}
                          checked={visible(c, access.has(a.code) || !a.is_restricted)}
                          onChange={() => toggle(c.code)}
                        />{" "}
                        {c.name}
                      </label>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </fieldset>
        ))}
      </div>
      {canManage && (
        <div className="form-actions form-actions--start">
          <button type="button" className="button button--sm" disabled={!dirty || saving} onClick={save}>
            {saving ? "Guardando…" : "Guardar acceso"}
          </button>
          {dirty && <span className="muted small">Cambios sin guardar</span>}
        </div>
      )}

      <h3 className="form-section__title">Agentes ({g.members.length})</h3>
      {canManage && (
        <form
          className="filters"
          onSubmit={(e) => {
            e.preventDefault();
            acdApi.addMember(code, memberCode.trim()).then((b) => { setMemberCode(""); onDone(b); }).catch(onError);
          }}
        >
          <label className="field">
            <span className="field__label">ID corporativo</span>
            <input required value={memberCode} onChange={(e) => setMemberCode(e.target.value.toUpperCase())} placeholder="SV-2026-000001-7" />
          </label>
          <button type="submit" className="button button--sm">Asignar al grupo</button>
          <span className="muted small">Si el agente estaba en otro grupo, se mueve a este (sin sesión abierta).</span>
        </form>
      )}
      {g.members.length === 0 ? (
        <p className="muted">Sin agentes asignados.</p>
      ) : (
        <ul className="acd-members">
          {g.members.map((m) => (
            <li key={m.employee_code}>
              {m.full_name} <code className="small">{m.employee_code}</code>
              {canManage && (
                <button type="button" className="link-button" onClick={() => acdApi.removeMember(code, m.employee_code).then(onDone).catch(onError)}>
                  Retirar
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
