import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { adhApi } from "../api.js";

const fmt = (iso) => (iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)} ${iso.slice(11, 16)}` : "—");

/**
 * Justificaciones (WFM): ventanas respaldadas por una Acción de Personal APROBADA del mismo empleado (permiso, cita
 * médica, tiempo extra autorizado…). Ese tiempo no se marca como Out of Adherence ni Unpaid Excess Login y, si se
 * indica, se paga.
 */
export default function JustificationsPage() {
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => ({ employee: params.get("employee") ?? "", from: params.get("from") ?? "", to: params.get("to") ?? "" }), [params]);
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [notice, setNotice] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [form, setForm] = useState({ employee_code: "", folio: "", start: "", end: "", is_paid: true, reason: "" });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    adhApi
      .exceptions(filters, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [filters, reloadKey]);

  const done = useCallback((b) => {
    setNotice({ ok: true, text: b.feedback });
    setReloadKey((k) => k + 1);
  }, []);
  const fail = useCallback((err) => setNotice({ ok: false, text: err.message }), []);
  const update = (changes) => setParams(Object.fromEntries(Object.entries({ ...filters, ...changes }).filter(([, v]) => v)), { replace: true });

  const submit = (e) => {
    e.preventDefault();
    setBusy(true);
    adhApi
      .createException(form)
      .then((b) => {
        done(b);
        setForm((f) => ({ ...f, folio: "", start: "", end: "", reason: "" }));
      })
      .catch(fail)
      .finally(() => setBusy(false));
  };
  const remove = (x) => {
    if (!window.confirm(`¿Eliminar la justificación ${x.folio} de ${x.employee_code}?`)) return;
    adhApi.deleteException(x.id).then(done).catch(fail);
  };
  const canManage = state.data?.can_manage;

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Justificaciones (AP)</h1>
          <p className="muted page-subtitle">
            Tiempo fuera del plan respaldado por una Acción de Personal aprobada (p. ej. «Justificación de tiempo»): no se marca como Out of Adherence ni
            Unpaid Excess Login. Horas en hora local de la operación.
          </p>
        </div>
      </header>
      {notice && (
        <div className={`alert ${notice.ok ? "alert--ok" : "alert--error"} flash`} role="status">
          <p className="alert__text">{notice.text}</p>
        </div>
      )}
      {canManage && (
        <form className="form-section" onSubmit={submit}>
          <h2 className="form-section__title">Nueva justificación</h2>
          <div className="form-grid">
            <label className="field">
              <span className="field__label">Agente (ID)</span>
              <input required value={form.employee_code} placeholder="SV-2026-000001-7" onChange={(e) => setForm({ ...form, employee_code: e.target.value.toUpperCase() })} />
            </label>
            <label className="field">
              <span className="field__label">Folio de la AP aprobada</span>
              <input required value={form.folio} placeholder="APJ-2026-000001" onChange={(e) => setForm({ ...form, folio: e.target.value.toUpperCase() })} />
            </label>
            <label className="field">
              <span className="field__label">Desde</span>
              <input type="datetime-local" step="1" required value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} />
            </label>
            <label className="field">
              <span className="field__label">Hasta</span>
              <input type="datetime-local" step="1" required min={form.start} value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} />
            </label>
            <label className="field">
              <span className="field__label">Motivo</span>
              <input required maxLength={200} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
            </label>
          </div>
          <label className="checkbox">
            <input type="checkbox" checked={form.is_paid} onChange={(e) => setForm({ ...form, is_paid: e.target.checked })} /> Tiempo pagado
          </label>
          <div className="form-actions form-actions--start">
            <button type="submit" className="button button--sm" disabled={busy}>
              Registrar
            </button>
          </div>
        </form>
      )}
      <div className="filters" role="search">
        <label className="field">
          <span className="field__label">Agente (ID)</span>
          <input type="search" defaultValue={filters.employee} onKeyDown={(e) => e.key === "Enter" && update({ employee: e.currentTarget.value.trim().toUpperCase() })} />
        </label>
        <label className="field">
          <span className="field__label">Desde</span>
          <input type="date" value={filters.from} onChange={(e) => update({ from: e.target.value })} />
        </label>
        <label className="field">
          <span className="field__label">Hasta</span>
          <input type="date" value={filters.to} onChange={(e) => update({ to: e.target.value })} />
        </label>
      </div>
      {state.error && <p className="error-box">{state.error}</p>}
      {state.data && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Agente</th>
                <th>Desde</th>
                <th>Hasta</th>
                <th>AP</th>
                <th>Motivo</th>
                <th>Pago</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {state.data.results.length === 0 && (
                <tr>
                  <td colSpan={7} className="empty">Sin justificaciones registradas.</td>
                </tr>
              )}
              {state.data.results.map((x) => (
                <tr key={x.id}>
                  <td>
                    {x.full_name}
                    <div className="muted small">{x.employee_code}</div>
                  </td>
                  <td>{fmt(x.start)}</td>
                  <td>{fmt(x.end)}</td>
                  <td>
                    {x.folio}
                    <div className="muted small">{x.action_type}</div>
                  </td>
                  <td>{x.reason}</td>
                  <td>{x.is_paid ? "Pagado" : "No pagado"}</td>
                  <td>
                    {canManage && (
                      <button type="button" className="link-button" onClick={() => remove(x)}>
                        Eliminar
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
