import { useEffect, useState } from "react";
import { formatDate, todayIso } from "../../hcm/lib/format.js";
import { generalIdsApi } from "../api.js";
import { useGeneralIdCatalogs } from "../hooks/useGeneralIdCatalogs.js";
import FieldHint from "../../../components/ui/FieldHint.jsx";

const EMPTY = { id_type: "", value: "", client: "", brand: "", effective_start: "", effective_end: "", notes: "" };

function Status({ row }) {
  if (row.is_current) return <span className="badge badge--ok">{row.is_now ? "Vigente · Now" : "Vigente"}</span>;
  if (row.is_future) return <span className="badge badge--info">Programado</span>;
  return <span className="badge badge--muted">Cerrado</span>;
}

/**
 * Pestaña «General IDs» del expediente (Fase 7): identificadores del empleado en herramientas externas
 * (ACD ID, Payroll Tool ID…), con vigencias. Varios IDs pueden estar activos a la vez; las reglas
 * (cliente/marca, valor único, uno vigente por tipo) las valida el backend y las garantiza SQL Server.
 */
export default function GeneralIdsPanel({ employee }) {
  const code = employee.employee_code;
  const catalogs = useGeneralIdCatalogs();
  const [asOf, setAsOf] = useState(todayIso());
  const [history, setHistory] = useState(false);
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [reloadKey, setReloadKey] = useState(0);
  const [editing, setEditing] = useState(null); // null | {mode: "new"} | {mode: "correct", row}
  const [closing, setClosing] = useState(null); // fila a cerrar
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    generalIdsApi
      .employee(code, history ? { history: 1, as_of: asOf } : { as_of: asOf }, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [code, asOf, history, reloadKey]);

  const saved = (feedback) => {
    setEditing(null);
    setClosing(null);
    setNotice(feedback);
    setReloadKey((k) => k + 1);
  };

  if (catalogs.error) return <p className="error-box">No se pudo cargar la configuración de General IDs: {catalogs.error}</p>;
  if (catalogs.loading || (state.loading && !state.data)) return <p className="muted">Cargando General IDs…</p>;
  if (state.error && !state.data) return <p className="error-box">{state.error}</p>;

  const rows = state.data.results;
  const canManage = state.data.can_manage;

  return (
    <section aria-labelledby="gid-title" className="roster">
      <header className="docs-header">
        <h2 id="gid-title" className="section-title">
          General IDs
        </h2>
        <label className="roster__asof">
          <span className="muted small">Vigentes al</span>
          <input type="date" value={asOf} onChange={(e) => e.target.value && setAsOf(e.target.value)} disabled={history} />
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={history} onChange={(e) => setHistory(e.target.checked)} />
          <span>Ver todo el historial</span>
        </label>
        {canManage && !editing && (
          <button type="button" className="button button--sm" onClick={() => setEditing({ mode: "new" })}>
            Registrar ID
          </button>
        )}
      </header>
      <p className="muted small">
        Llaves para cruzar reportes (ACD, planilla y otras herramientas). Un empleado puede tener varios IDs activos a la vez;
        cada uno tiene su vigencia («Now» = sin fecha de fin). Los tipos, herramientas y a qué clientes/marcas aplican se
        configuran en /admin/.
      </p>
      {notice && (
        <div className="alert alert--ok flash" role="status">
          <p className="alert__text">{notice}</p>
          <button type="button" className="button button--ghost button--sm" onClick={() => setNotice(null)}>
            Cerrar
          </button>
        </div>
      )}

      {editing && (
        <GeneralIdEditor
          code={code}
          catalogs={catalogs}
          row={editing.row}
          defaultStart={employee.hire_date && employee.hire_date > todayIso() ? employee.hire_date : todayIso()}
          onCancel={() => setEditing(null)}
          onSaved={saved}
        />
      )}

      <div className="table-wrap">
        <table className="table roster-table">
          <thead>
            <tr>
              <th scope="col">Tipo</th>
              <th scope="col">Herramienta</th>
              <th scope="col">Valor</th>
              <th scope="col">Cliente / marca</th>
              <th scope="col">Vigencia</th>
              <th scope="col">Estado</th>
              <th scope="col">
                <span className="sr-only">Acciones</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id}>
                <th scope="row">{row.id_type_name}</th>
                <td>{row.tool_name}</td>
                <td>
                  <code>{row.value}</code>
                </td>
                <td>{row.client_name ? `${row.client_name}${row.brand_name ? ` › ${row.brand_name}` : ""}` : <span className="muted">—</span>}</td>
                <td>
                  {formatDate(row.effective_start)} → {row.is_now ? <strong>Now</strong> : formatDate(row.effective_end)}
                </td>
                <td>
                  <Status row={row} />
                </td>
                <td>
                  {canManage && (
                    <span className="gid-actions">
                      {(row.is_now || !row.effective_end) && (
                        <button type="button" className="link-button" onClick={() => setClosing(row)}>
                          Cerrar vigencia
                        </button>
                      )}
                      <button type="button" className="link-button" onClick={() => setEditing({ mode: "correct", row })}>
                        Corregir
                      </button>
                    </span>
                  )}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="empty">
                  {history ? "El empleado no tiene General IDs registrados." : `Sin General IDs vigentes al ${formatDate(asOf)}.`}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {closing && <CloseForm code={code} row={closing} onCancel={() => setClosing(null)} onSaved={saved} />}
    </section>
  );
}

function Messages({ result }) {
  if (!result) return null;
  return (
    <div className={`alert ${result.valid ? "alert--ok" : "alert--error"}`} role="status">
      <p className="alert__text">{result.feedback}</p>
    </div>
  );
}

/** Alta (row = undefined) o corrección de un General ID. */
function GeneralIdEditor({ code, catalogs, row, defaultStart, onCancel, onSaved }) {
  const correcting = Boolean(row);
  const [values, setValues] = useState(
    row
      ? {
          id_type: row.id_type,
          value: row.value,
          client: row.client ?? "",
          brand: row.brand ?? "",
          effective_start: row.effective_start,
          effective_end: row.effective_end ?? "",
          notes: row.notes ?? "",
        }
      : { ...EMPTY, effective_start: defaultStart },
  );
  const [busy, setBusy] = useState(null);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const type = catalogs.typesByCode[values.id_type];
  const scope = catalogs.scopeFor(type);
  const client = scope.clients.find((c) => c.code === values.client);
  const set = (patch) => {
    setValues((v) => ({ ...v, ...patch }));
    setResult(null);
  };
  const errorsFor = (field) => result?.errors?.filter((e) => e.field === field).map((e) => e.message).join(" ");

  const body = () => ({
    ...values,
    client: values.client || null,
    brand: values.brand || null,
    effective_end: values.effective_end || null,
  });

  const submit = async (dryRun) => {
    setBusy(dryRun ? "validate" : "save");
    setError(null);
    try {
      const response = correcting
        ? await generalIdsApi.correct(code, row.id, body(), { dryRun })
        : dryRun
          ? await generalIdsApi.validate(code, body())
          : await generalIdsApi.create(code, body());
      if (dryRun) setResult(response);
      else onSaved(response.feedback);
    } catch (err) {
      if (err.body?.errors) setResult(err.body);
      else setError(err.message);
    } finally {
      setBusy(null);
    }
  };

  const types = catalogs.types.filter((t) => t.is_active || t.code === values.id_type);

  return (
    <form
      className="roster-editor"
      onSubmit={(e) => {
        e.preventDefault();
        submit(false);
      }}
      noValidate
    >
      <h3 className="section-title">{correcting ? `Corregir ${row.id_type_name} «${row.value}»` : "Registrar General ID"}</h3>
      <div className="form-section">
        <div className="form-grid">
          <div className="field">
            <label htmlFor="gid-type" className="field__label">
              Tipo de ID<span className="field__req">*</span>
            </label>
            <select
              id="gid-type"
              value={values.id_type}
              onChange={(e) => set({ id_type: e.target.value, client: "", brand: "" })}
              disabled={correcting}
              aria-invalid={Boolean(errorsFor("id_type"))}
            >
              <option value="">— Seleccione —</option>
              {types.map((t) => (
                <option key={t.code} value={t.code}>
                  {t.name} · {t.tool_name}
                </option>
              ))}
            </select>
            {errorsFor("id_type") ? (
              <small className="field__error">{errorsFor("id_type")}</small>
            ) : (
              type && (
                <FieldHint>
                  {type.scope_level_label}
                  {type.allow_multiple_active ? " · admite varios vigentes" : " · uno vigente a la vez"}
                </FieldHint>
              )
            )}
          </div>
          <div className="field">
            <label htmlFor="gid-value" className="field__label">
              Valor<span className="field__req">*</span>
            </label>
            <input
              id="gid-value"
              value={values.value}
              onChange={(e) => set({ value: type?.transform === "UPPER" ? e.target.value.toUpperCase() : e.target.value })}
              maxLength={type?.max_length ?? 100}
              placeholder={type?.example ?? undefined}
              autoComplete="off"
              spellCheck={false}
              aria-invalid={Boolean(errorsFor("value"))}
            />
            {errorsFor("value") ? (
              <small className="field__error">{errorsFor("value")}</small>
            ) : (
              type?.pattern_message && <FieldHint>{type.pattern_message}</FieldHint>
            )}
          </div>
          {type && type.scope_level !== "GLOBAL" && (
            <>
              <div className="field">
                <label htmlFor="gid-client" className="field__label">
                  Cliente{type.scope_level === "CLIENT" && <span className="field__req">*</span>}
                </label>
                <select
                  id="gid-client"
                  value={values.client}
                  onChange={(e) => set({ client: e.target.value, brand: "" })}
                  aria-invalid={Boolean(errorsFor("client"))}
                >
                  <option value="">— Seleccione —</option>
                  {scope.clients.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.name}
                    </option>
                  ))}
                </select>
                {errorsFor("client") ? (
                  <small className="field__error">{errorsFor("client")}</small>
                ) : (
                  !type.applies_to.all && <FieldHint>Solo los clientes a los que aplica este tipo de ID.</FieldHint>
                )}
              </div>
              <div className="field">
                <label htmlFor="gid-brand" className="field__label">
                  Marca
                  {(type.scope_level === "BRAND" || (client && scope.clientNeedsBrand(client))) && <span className="field__req">*</span>}
                </label>
                <select
                  id="gid-brand"
                  value={values.brand}
                  onChange={(e) => set({ brand: e.target.value })}
                  disabled={!client}
                  aria-invalid={Boolean(errorsFor("brand"))}
                >
                  <option value="">{client ? "— Todas / sin marca —" : "Elija primero el cliente"}</option>
                  {(client?.brands ?? []).map((b) => (
                    <option key={b.code} value={b.code}>
                      {b.name}
                    </option>
                  ))}
                </select>
                {errorsFor("brand") && <small className="field__error">{errorsFor("brand")}</small>}
              </div>
            </>
          )}
          <div className="field">
            <label htmlFor="gid-start" className="field__label">
              Vigente desde<span className="field__req">*</span>
            </label>
            <input
              id="gid-start"
              type="date"
              value={values.effective_start}
              onChange={(e) => set({ effective_start: e.target.value })}
              aria-invalid={Boolean(errorsFor("effective_start"))}
            />
            {errorsFor("effective_start") && <small className="field__error">{errorsFor("effective_start")}</small>}
          </div>
          <div className="field">
            <label htmlFor="gid-end" className="field__label">
              Vigente hasta
            </label>
            <input
              id="gid-end"
              type="date"
              value={values.effective_end}
              min={values.effective_start || undefined}
              onChange={(e) => set({ effective_end: e.target.value })}
              aria-invalid={Boolean(errorsFor("effective_end"))}
            />
            {errorsFor("effective_end") ? (
              <small className="field__error">{errorsFor("effective_end")}</small>
            ) : (
              <FieldHint>Vacío = «Now» (vigente sin fecha de fin).</FieldHint>
            )}
          </div>
          <div className="field">
            <label htmlFor="gid-notes" className="field__label">
              Notas
            </label>
            <input id="gid-notes" value={values.notes} maxLength={300} onChange={(e) => set({ notes: e.target.value })} />
          </div>
        </div>
      </div>
      <Messages result={result} />
      {error && (
        <p className="alert alert--error" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="button" className="button button--ghost" onClick={onCancel} disabled={Boolean(busy)}>
          Cancelar
        </button>
        <button type="button" className="button button--ghost" onClick={() => submit(true)} disabled={Boolean(busy)}>
          {busy === "validate" ? "Validando…" : "Validar sin guardar"}
        </button>
        <button type="submit" className="button" disabled={Boolean(busy)}>
          {busy === "save" ? "Guardando…" : correcting ? "Guardar corrección" : "Registrar ID"}
        </button>
      </div>
    </form>
  );
}

/** Cierra la vigencia de un ID («Now» -> fecha). */
function CloseForm({ code, row, onCancel, onSaved }) {
  const [end, setEnd] = useState(todayIso() < row.effective_start ? row.effective_start : todayIso());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = await generalIdsApi.close(code, row.id, { effective_end: end });
      onSaved(`${body.feedback} ${row.id_type_name} «${row.value}» vigente hasta el ${formatDate(end)}.`);
    } catch (err) {
      setError(err.body?.errors?.map((x) => x.message).join(" ") || err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="roster-history" onSubmit={submit}>
      <div className="roster-history__head">
        <strong>
          Cerrar {row.id_type_name} «{row.value}»
        </strong>
      </div>
      <div className="form-grid">
        <div className="field">
          <label htmlFor="gid-close" className="field__label">
            Vigente hasta
          </label>
          <input id="gid-close" type="date" value={end} min={row.effective_start} onChange={(e) => setEnd(e.target.value)} />
        </div>
      </div>
      {error && (
        <p className="alert alert--error" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="button" className="button button--ghost button--sm" onClick={onCancel} disabled={busy}>
          Cancelar
        </button>
        <button type="submit" className="button button--sm" disabled={busy || !end}>
          {busy ? "Guardando…" : "Cerrar vigencia"}
        </button>
      </div>
    </form>
  );
}
