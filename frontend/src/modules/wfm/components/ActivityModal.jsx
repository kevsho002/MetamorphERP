import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ATTENDANCE, addSeconds, adhApi, fmtDuration, groupByCategory, hhmm, hhmmss } from "../api.js";
import ActivityIcon from "./ActivityIcon.jsx";

const STATUS_CLS = { PENDING: "badge--warn", APPROVED: "badge--ok", REJECTED: "badge--error", CANCELLED: "badge--muted" };
const ABSENCE_ROLES = ["ABSENCE", "LEGAL_LUNCH"];

function LockIcon() {
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true">
      <path d="M6 11h12v9H6z M9 11V8a3 3 0 0 1 6 0v3" />
    </svg>
  );
}

/** Selector de actividad agrupado por categoría del Time Utilization (las del sistema no se ofrecen). */
function ActivitySelect({ activities, value, onChange, label = "Actividad" }) {
  return (
    <label className="field">
      <span className="field__label">{label}</span>
      <select value={value} required onChange={(e) => onChange(e.target.value)}>
        <option value="" disabled>
          Elija una actividad…
        </option>
        {groupByCategory(activities).map((g) => (
          <optgroup key={g.code || "none"} label={g.department ? `${g.department} › ${g.name}` : g.name}>
            {g.items.map((a) => (
              <option key={a.code} value={a.code}>
                {a.name}
                {a.requires_ap ? " · requiere AP" : ""}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
    </label>
  );
}

/**
 * Formulario de la ventana: editar / agregar / reemplazar (WFM) o solicitar a la cola (agente, supervisor, WFM lectura).
 * `action` = { type: edit | add | replace | request-change | request-add | request-delete, row }.
 */
function ActionForm({ action, day, onSubmit, onCancel, busy }) {
  const { type, row } = action;
  const isRequest = type.startsWith("request");
  const locked = Boolean(row?.is_locked);
  const activities = day.activities;
  const initialActivity = type === "edit" || type === "request-change" ? (locked ? "" : row.activity) : "";
  const [form, setForm] = useState(() => ({
    activity: initialActivity,
    start: row ? hhmmss(row.start) : hhmmss(day.containers[0]?.start) || "08:00:00",
    end: row ? hhmmss(row.end) : addSeconds(hhmmss(day.containers[0]?.start) || "08:00:00", 900),
    notes: type === "edit" ? row?.notes ?? "" : "",
    folio: "",
    reason: "",
    scope: "segment",
  }));
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const activity = activities.find((a) => a.code === form.activity);
  const needsFolio = locked || activity?.requires_ap;
  const titles = {
    edit: "Editar segmento",
    add: "Agregar segmento",
    replace: `Reemplazar ${row?.activity_name ?? ""} (con AP)`,
    "request-change": locked ? `Solicitar reemplazo de ${row?.activity_name}` : `Solicitar cambio de ${row?.activity_name}`,
    "request-add": "Solicitar un segmento",
    "request-delete": `Solicitar quitar ${row?.activity_name}`,
  };
  const submit = (e) => {
    e.preventDefault();
    onSubmit(form);
  };
  return (
    <form className="act-modal__form" onSubmit={submit} aria-label={titles[type]}>
      <h3 className="act-modal__form-title">{titles[type]}</h3>
      {type !== "request-delete" && (
        <div className="act-modal__grid">
          <ActivitySelect activities={activities} value={form.activity} onChange={(v) => {
            const a = activities.find((x) => x.code === v);
            setForm((f) => ({ ...f, activity: v, end: !row && a?.default_seconds ? addSeconds(f.start, a.default_seconds) : f.end }));
          }} label={locked ? "Actividad documentada que lo reemplaza" : "Actividad"} />
          {!(type === "replace" && form.scope === "day") && (
            <>
              <label className="field">
                <span className="field__label">Inicio (HH:MM:SS)</span>
                <input type="time" step="1" required value={form.start} onChange={(e) => set("start", e.target.value)} />
              </label>
              <label className="field">
                <span className="field__label">Fin (HH:MM:SS)</span>
                <input type="time" step="1" required value={form.end} onChange={(e) => set("end", e.target.value)} />
              </label>
            </>
          )}
          <label className="field">
            <span className="field__label">Folio de la AP {needsFolio ? "(obligatorio)" : "(si el cambio la exige)"}</span>
            <input value={form.folio} required={needsFolio} placeholder="APJ-2026-000001" onChange={(e) => set("folio", e.target.value.toUpperCase())} />
          </label>
          <label className="field act-modal__wide">
            <span className="field__label">Notas del segmento</span>
            <input value={form.notes} maxLength={200} onChange={(e) => set("notes", e.target.value)} />
          </label>
        </div>
      )}
      {type === "replace" && ABSENCE_ROLES.includes(row.system_role) && (
        <label className="checkbox">
          <input type="checkbox" checked={form.scope === "day"} onChange={(e) => set("scope", e.target.checked ? "day" : "segment")} /> Reemplazar toda la
          ausencia del día (incluido el Legal Benefit Lunch), p. ej. con un permiso respaldado por AP
        </label>
      )}
      {isRequest && (
        <label className="field">
          <span className="field__label">Motivo / observaciones para WFM</span>
          <textarea required minLength={5} maxLength={500} rows={2} value={form.reason} onChange={(e) => set("reason", e.target.value)} />
        </label>
      )}
      {locked && (
        <p className="muted small">
          El segmento lo insertó el sistema: no se elimina ni se mueve. Solo se reemplaza con un segmento documentado y la AP aprobada (justificación) que lo
          respalda; lo que quede fuera del rango sigue bloqueado.
        </p>
      )}
      <div className="form-actions form-actions--start">
        <button type="submit" className={`button button--sm${type === "request-delete" ? " button--danger" : ""}`} disabled={busy}>
          {busy ? "Enviando…" : isRequest ? "Enviar a la cola de WFM" : type === "replace" ? "Reemplazar" : "Guardar"}
        </button>
        <button type="button" className="link-button" onClick={onCancel}>
          Cancelar
        </button>
      </div>
    </form>
  );
}

/**
 * Ventana flotante de detalle y auditoría de un día (Fase 19). Se abre al hacer clic en una actividad o en el
 * pre-contenedor de la grilla. Tabla: actividad, inicio, fin, duración, notas / observaciones y respaldo (origen y AP).
 *
 * * WFM con permiso de edición: edita, agrega, elimina y reemplaza (Lateness / ausencia solo con AP).
 * * Agente, supervisor de su cadena de mando y WFM de solo lectura: MODO LECTURA; las correcciones de segmentos van a
 *   la cola de aprobación de WFM y los cambios del día completo al flujo de AP.
 */
export default function ActivityModal({ target, onClose, onChanged, onAudit }) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [reload, setReload] = useState(0);
  const [action, setAction] = useState(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const panel = useRef(null);
  const opener = useRef(typeof document !== "undefined" ? document.activeElement : null);

  useEffect(() => {
    const controller = new AbortController();
    adhApi
      .day({ employee: target.employee_code, date: target.date }, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [target.employee_code, target.date, reload]);

  useEffect(() => {
    panel.current?.focus();
    const back = opener.current;
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      if (back && typeof back.focus === "function") back.focus();
    };
  }, [onClose]);

  const day = state.data;
  const edit = day?.mode === "edit";
  const focus = target.focus;

  const finish = useCallback((body) => {
    setNotice({ ok: true, text: body.feedback });
    setAction(null);
    setReload((k) => k + 1);
    onChanged?.(body);
  }, [onChanged]);
  const fail = (err) => setNotice({ ok: false, text: err.message });

  const run = (promise) => {
    setBusy(true);
    setNotice(null);
    promise.then(finish).catch(fail).finally(() => setBusy(false));
  };

  const submit = (form) => {
    const { type, row } = action;
    const times = { start: form.start, end: form.end };
    const folio = form.folio ? { folio: form.folio } : {};
    const base = { employee_code: day.employee_code, shift_date: day.date };
    if (type === "edit") run(adhApi.updateSegment(row.segment_id, { activity: form.activity, ...times, notes: form.notes, ...folio }));
    else if (type === "add") run(adhApi.createSegment({ ...base, activity: form.activity, ...times, notes: form.notes, ...folio }));
    else if (type === "replace") {
      run(adhApi.replaceSegment(row.segment_id, { activity: form.activity, notes: form.notes, folio: form.folio,
        ...(form.scope === "day" ? { scope: "day" } : times) }));
    } else {
      const kind = { "request-change": "CHANGE", "request-add": "ADD", "request-delete": "DELETE" }[type];
      run(adhApi.createRequest({ ...base, kind, segment_id: row?.segment_id, reason: form.reason, notes: form.notes, ...folio,
        ...(kind === "DELETE" ? {} : { activity: form.activity || row?.activity, ...times }) }));
    }
  };
  const remove = (row) => {
    if (!window.confirm(`¿Eliminar ${row.activity_name} ${hhmm(row.start)}–${hhmm(row.end)}?`)) return;
    run(adhApi.deleteSegment(row.segment_id));
  };
  const cancelRequest = (r) => run(adhApi.cancelRequest(r.id));
  const att = day?.attendance ? ATTENDANCE[day.attendance] : null;
  const fullDayAp = `/personnel-actions/new?employee=${encodeURIComponent(target.employee_code)}`;

  return (
    <div className="act-modal__backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="act-modal" role="dialog" aria-modal="true" aria-labelledby="act-modal-title" tabIndex={-1} ref={panel}>
        <header className="act-modal__head">
          <div>
            <h2 id="act-modal-title" className="act-modal__title">
              {target.full_name ?? day?.full_name ?? target.employee_code}
            </h2>
            <p className="muted small">
              {target.employee_code} · turno del {target.date}
              {day?.containers?.length ? ` · ${day.containers.map((c) => `${hhmm(c.start)}–${hhmm(c.end)}`).join(", ")}` : ""}
            </p>
          </div>
          <div className="act-modal__badges">
            {day && (
              <span className={`badge ${edit ? "badge--ok" : "badge--info"}`}>
                {edit ? "Edición (WFM)" : `Modo lectura · ${day.role_label}`}
              </span>
            )}
            {att && <span className={`badge ${att.cls}`}>{att.label}</span>}
            {onAudit && (
              <button type="button" className="link-button" onClick={() => onAudit(target)}>
                Audit trail
              </button>
            )}
            <button type="button" className="act-modal__close" onClick={onClose} aria-label="Cerrar">
              ×
            </button>
          </div>
        </header>

        {state.loading && <p className="muted">Cargando…</p>}
        {state.error && <p className="error-box">{state.error}</p>}
        {notice && (
          <div className={`alert ${notice.ok ? "alert--ok" : "alert--error"}`} role="status">
            <p className="alert__text">{notice.text}</p>
          </div>
        )}

        {day && (
          <>
            {day.containers.length === 0 ? (
              <p className="empty">Sin turno (pre-contenedor) en esta fecha.</p>
            ) : (
              <div className="table-wrap act-modal__table-wrap">
                <table className="table act-modal__table">
                  <thead>
                    <tr>
                      <th scope="col">Actividad</th>
                      <th scope="col">Inicio</th>
                      <th scope="col">Fin</th>
                      <th scope="col">Duración</th>
                      <th scope="col">Notas / observaciones</th>
                      <th scope="col">Respaldo</th>
                      <th scope="col">
                        <span className="sr-only">Acciones</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {day.table.map((r) => {
                      const isFocus = (focus === "container" && r.kind === "container") || (r.segment_id && r.segment_id === focus);
                      return (
                        <tr key={`${r.start}-${r.segment_id ?? "c"}`} className={`${isFocus ? "is-focus" : ""}${r.kind === "container" ? " is-container" : ""}`}>
                          <td>
                            <span className="adh-icon-swatch" style={{ background: r.color }} aria-hidden="true">
                              <ActivityIcon name={r.icon} size={13} />
                            </span>{" "}
                            <strong>{r.activity_name}</strong> {r.is_locked && <span className="act-modal__lock" title="Bloqueado: solo se reemplaza con AP"><LockIcon /></span>}
                            {r.category && <div className="muted small">{r.category}</div>}
                          </td>
                          <td className="num">{hhmmss(r.start)}</td>
                          <td className="num">{hhmmss(r.end)}</td>
                          <td className="num">{fmtDuration(r.seconds)}</td>
                          <td>{r.notes || <span className="muted">—</span>}</td>
                          <td className="small">
                            {r.origin_label}
                            {r.folio && (
                              <div>
                                AP <Link to={`/personnel-actions/${r.folio}`}>{r.folio}</Link>
                              </div>
                            )}
                            {r.created_by && <div className="muted">por {r.created_by}</div>}
                          </td>
                          <td className="act-modal__row-actions">
                            {r.kind === "segment" && edit && !r.is_locked && (
                              <>
                                <button type="button" className="link-button" onClick={() => setAction({ type: "edit", row: r })}>
                                  Editar
                                </button>
                                <button type="button" className="link-button act-modal__danger" onClick={() => remove(r)} disabled={busy}>
                                  Eliminar
                                </button>
                              </>
                            )}
                            {r.kind === "segment" && edit && r.is_locked && (
                              <button type="button" className="link-button" onClick={() => setAction({ type: "replace", row: r })}>
                                Reemplazar con AP
                              </button>
                            )}
                            {r.kind === "segment" && !edit && (
                              <>
                                <button type="button" className="link-button" onClick={() => setAction({ type: "request-change", row: r })}>
                                  {r.is_locked ? "Solicitar reemplazo" : "Solicitar cambio"}
                                </button>
                                {!r.is_locked && (
                                  <button type="button" className="link-button" onClick={() => setAction({ type: "request-delete", row: r })}>
                                    Solicitar quitar
                                  </button>
                                )}
                              </>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            {day.warnings.length > 0 && (
              <ul className="msg-list msg-list--warn">
                {day.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}

            {action ? (
              <ActionForm key={`${action.type}-${action.row?.segment_id ?? "new"}`} action={action} day={day} busy={busy} onSubmit={submit}
                onCancel={() => setAction(null)} />
            ) : (
              day.containers.length > 0 && (
                <div className="act-modal__footer">
                  <button type="button" className="button button--ghost button--sm" onClick={() => setAction({ type: edit ? "add" : "request-add", row: null })}>
                    {edit ? "+ Agregar segmento" : "+ Solicitar un segmento"}
                  </button>
                  <span className="muted small">
                    {edit
                      ? `Segmentos operativos: libres. Exigen AP aprobada las actividades marcadas, el día completo${day.policy.ap_required_seconds ? ` y los de ${fmtDuration(day.policy.ap_required_seconds)} o más` : ""}.`
                      : "Las correcciones de segmentos pasan por la cola de aprobación de WFM."}{" "}
                    Día completo:{" "}
                    <Link to={fullDayAp} onClick={onClose}>
                      tramitar AP
                    </Link>
                    .
                  </span>
                </div>
              )
            )}

            {day.requests.length > 0 && (
              <section className="act-modal__requests" aria-label="Solicitudes del día">
                <h3 className="act-modal__form-title">Cola de WFM de este día</h3>
                <ul className="audit-list">
                  {day.requests.map((r) => (
                    <li key={r.id} className="act-modal__request">
                      <span className={`badge ${STATUS_CLS[r.status]}`}>{r.status_label}</span>{" "}
                      <strong>#{r.id} {r.kind_label}</strong>
                      {r.activity_name && ` → ${r.activity_name} ${hhmm(r.start)}–${hhmm(r.end)}`}
                      {r.before && ` (antes: ${r.before.activity_name} ${hhmm(r.before.start)}–${hhmm(r.before.end)})`}
                      <div className="muted small">
                        {r.requester_role_label} {r.requested_by} · «{r.reason}»
                        {r.decided_by && ` · resolvió ${r.decided_by}${r.decision_comment ? `: «${r.decision_comment}»` : ""}`}
                      </div>
                      {r.status === "PENDING" && !edit && (
                        <button type="button" className="link-button" onClick={() => cancelRequest(r)} disabled={busy}>
                          Anular
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
                {edit && (
                  <Link to="/wfm/requests" className="small" onClick={onClose}>
                    Ir a la cola de aprobación
                  </Link>
                )}
              </section>
            )}
          </>
        )}
      </div>
    </div>
  );
}
