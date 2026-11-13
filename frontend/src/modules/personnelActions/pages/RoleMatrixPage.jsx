import { useEffect, useState } from "react";
import { actionsApi } from "../api.js";

/**
 * Fase 21 — Control de AP por roles: qué perfiles (Generalista de RRHH, WFM, Administrador) elaboran cada tipo y qué rol
 * firma cada paso. Lo consulta cualquiera que vea AP; solo el Administrador lo cambia (queda en la auditoría).
 */
export default function RoleMatrixPage() {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [busy, setBusy] = useState(null);
  const [feedback, setFeedback] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    actionsApi
      .roleMatrix({ signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, []);

  const save = async (type, patch) => {
    setBusy(type.code);
    setFeedback(null);
    try {
      const data = await actionsApi.updateRoles(type.code, patch);
      setState({ loading: false, data, error: null });
      setFeedback({ ok: true, text: `Roles de «${type.name}» actualizados.` });
    } catch (err) {
      setFeedback({ ok: false, text: err.message });
    } finally {
      setBusy(null);
    }
  };

  if (state.loading) return <p className="muted">Cargando roles…</p>;
  if (!state.data) return <p className="error-box">{state.error}</p>;
  const { roles, results, can_edit: canEdit } = state.data;
  const roleLabel = Object.fromEntries(roles.map((r) => [r.value, r.label]));
  const creatorRoles = roles.filter((r) => r.value !== "EMPLOYEE");

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Roles por tipo de AP</h1>
          <p className="muted page-subtitle">
            Validación estricta: solo los roles marcados elaboran cada tipo (además del permiso del tipo) y cada paso de la cadena lo firma su rol.
            Con «firma estricta», el Administrador tampoco puede firmar pasos de otro rol.
          </p>
        </div>
      </header>
      {!canEdit && <p className="muted small">Solo el Administrador puede cambiar esta matriz.</p>}
      {feedback && <p className={feedback.ok ? "alert alert--ok" : "error-box"}>{feedback.text}</p>}
      <div className="table-wrap">
        <table className="table pa-roles">
          <thead>
            <tr>
              <th scope="col">Tipo de AP</th>
              <th scope="col">Elaboran</th>
              <th scope="col">Cadena de firmas</th>
              <th scope="col">Firma estricta</th>
            </tr>
          </thead>
          <tbody>
            {results.map((t) => (
              <tr key={t.code} className={t.is_active ? "" : "is-muted"}>
                <td>
                  <strong>{t.name}</strong>
                  <div className="muted small">
                    {t.code} · {t.effect_label}
                  </div>
                </td>
                <td>
                  <div className="pa-roles__checks">
                    {creatorRoles.map((r) => {
                      const on = t.creator_roles.includes(r.value);
                      return (
                        <label key={r.value} className="checkbox">
                          <input
                            type="checkbox"
                            checked={on}
                            disabled={!canEdit || busy === t.code}
                            onChange={() =>
                              save(t, { creator_roles: on ? t.creator_roles.filter((x) => x !== r.value) : [...t.creator_roles, r.value] })
                            }
                          />
                          <span>{r.label}</span>
                        </label>
                      );
                    })}
                  </div>
                  {t.creator_roles.length === 0 && <small className="muted">Cualquier rol con el permiso «{t.create_permission}».</small>}
                </td>
                <td>
                  {t.steps.length === 0 && <span className="muted">Sin firmas (se aprueba al enviarse)</span>}
                  <ol className="pa-roles__steps">
                    {t.steps.map((s) => (
                      <li key={s.order}>
                        <span>{s.label}</span>{" "}
                        {canEdit ? (
                          <select
                            value={s.role}
                            disabled={busy === t.code}
                            aria-label={`Rol que firma el paso ${s.order} de ${t.name}`}
                            onChange={(e) => save(t, { steps: [{ order: s.order, role: e.target.value }] })}
                          >
                            {creatorRoles.map((r) => (
                              <option key={r.value} value={r.value}>
                                {r.label}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="badge">{roleLabel[s.role] ?? s.role}</span>
                        )}
                      </li>
                    ))}
                  </ol>
                </td>
                <td>
                  <label className="checkbox">
                    <input
                      type="checkbox"
                      checked={!t.admin_signs_any_step}
                      disabled={!canEdit || busy === t.code}
                      onChange={() => save(t, { admin_signs_any_step: !t.admin_signs_any_step })}
                    />
                    <span>{t.admin_signs_any_step ? "El Administrador firma cualquier paso" : "Solo el rol de cada paso"}</span>
                  </label>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
