import { useCallback, useEffect, useMemo, useState } from "react";
import FeedbackPanel from "../../hcm/components/Feedback.jsx";
import { formatDate, formatDateTime, todayIso } from "../../hcm/lib/format.js";
import { rosterApi } from "../api.js";
import { useRosterConfig } from "../hooks/useRosterConfig.js";
import ChainOfCommandPanel from "./ChainOfCommandPanel.jsx";
import RosterField from "./RosterField.jsx";
import FieldHint from "../../../components/ui/FieldHint.jsx";

const NOW = <span className="badge badge--ok">Now</span>;

function Period({ interval }) {
  if (!interval) return <span className="muted">—</span>;
  return (
    <>
      {formatDate(interval.effective_start)} → {interval.is_now ? NOW : formatDate(interval.effective_end)}
    </>
  );
}

/** Historial temporal de un atributo, incluidas las versiones corregidas (auditoría). */
function AttributeHistory({ code, attribute, onClose }) {
  const [state, setState] = useState({ loading: true, items: [], error: null });
  useEffect(() => {
    const controller = new AbortController();
    rosterApi
      .history(code, attribute.code, { signal: controller.signal })
      .then((data) => setState({ loading: false, items: data.results, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, items: [], error: err.message }));
    return () => controller.abort();
  }, [code, attribute.code]);

  return (
    <div className="roster-history" role="region" aria-label={`Historial de ${attribute.name}`}>
      <div className="roster-history__head">
        <strong>Historial: {attribute.name}</strong>
        <button type="button" className="link-button" onClick={onClose}>
          Cerrar
        </button>
      </div>
      {state.loading && <p className="muted small">Cargando…</p>}
      {state.error && <p className="field__error">{state.error}</p>}
      {!state.loading && state.items.length === 0 && <p className="muted small">Sin registros.</p>}
      <ol className="timeline">
        {state.items.map((h) => (
          <li key={h.id} className={`timeline__item${h.superseded_at ? " roster-history__superseded" : ""}`}>
            <time>
              <Period interval={h} />
            </time>
            <div>
              <p className="timeline__summary">
                <strong>{h.label}</strong>
                {h.superseded_at && <span className="tag">Corregido</span>}
              </p>
              <p className="muted small">
                Registrado {formatDateTime(h.recorded_at)} por {h.recorded_by || "—"}
                {h.reason && ` · «${h.reason}»`}
                {h.superseded_at && ` · reemplazado ${formatDateTime(h.superseded_at)} por ${h.superseded_by ?? "—"}`}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

/**
 * Sección «Roster» del expediente: asignaciones operativas con vigencia
 * (cliente, marca, línea, sub-línea, wave, fechas clave, documento para reportes).
 * Los campos salen de la configuración del backend: lo que se habilite allí aparece aquí.
 */
export default function RosterPanel({ employee }) {
  const config = useRosterConfig();
  const code = employee.employee_code;
  const [asOf, setAsOf] = useState(todayIso());
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [reloadKey, setReloadKey] = useState(0);
  const [editing, setEditing] = useState(false);
  const [historyOf, setHistoryOf] = useState(null);
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    rosterApi
      .employee(code, asOf, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [code, asOf, reloadKey]);

  const byCode = useMemo(
    () => Object.fromEntries((state.data?.attributes ?? []).map((a) => [a.code, a])),
    [state.data],
  );

  if (config.error) return <p className="error-box">No se pudo cargar la configuración del roster: {config.error}</p>;
  if (config.loading || (state.loading && !state.data)) return <p className="muted">Cargando roster…</p>;
  if (state.error && !state.data) return <p className="error-box">{state.error}</p>;
  if (!config.attributes.length) {
    return <p className="muted">No hay atributos de roster activos. Un administrador los habilita en /admin/ › Roster operativo.</p>;
  }

  const canManage = state.data.can_manage && employee.employment_status !== "TERMINATED";

  return (
    <section aria-labelledby="roster-title" className="roster">
      <header className="docs-header">
        <h2 id="roster-title" className="section-title">
          Roster operativo
        </h2>
        <label className="roster__asof">
          <span className="muted small">Vigente al</span>
          <input type="date" value={asOf} onChange={(e) => e.target.value && setAsOf(e.target.value)} />
        </label>
        <button type="button" className="button button--ghost button--sm" onClick={() => setAsOf(todayIso())}>
          Hoy
        </button>
        {canManage && !editing && (
          <button type="button" className="button button--sm" onClick={() => setEditing(true)}>
            Registrar cambios
          </button>
        )}
      </header>
      <p className="muted small">
        Asignación operativa del empleado, independiente de su ficha. Cada cambio tiene fecha efectiva y conserva el
        historial («Now» = vigente sin fecha de fin).
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
        <RosterEditor
          employee={employee}
          config={config}
          onCancel={() => setEditing(false)}
          onSaved={(result) => {
            setEditing(false);
            setNotice(result.feedback);
            setAsOf(result.effective_date);
            setReloadKey((k) => k + 1);
          }}
        />
      )}

      {config.groups.map((group) => (
        <section key={group.name} className="detail-section">
          <h3 className="section-title">{group.name}</h3>
          <div className="table-wrap">
            <table className="table roster-table">
              <thead>
                <tr>
                  <th scope="col">Dato</th>
                  <th scope="col">Valor al {formatDate(asOf)}</th>
                  <th scope="col">Vigencia</th>
                  <th scope="col">Próximo cambio</th>
                  <th scope="col">
                    <span className="sr-only">Acciones</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {group.attributes.map((attribute) => {
                  const entry = byCode[attribute.code];
                  const current = entry?.current;
                  return (
                    <tr key={attribute.code}>
                      <th scope="row">{attribute.name}</th>
                      <td>{current ? <strong>{current.label}</strong> : <span className="muted">Sin asignar</span>}</td>
                      <td>
                        <Period interval={current} />
                      </td>
                      <td>
                        {entry?.next ? (
                          <>
                            {entry.next.label} <span className="muted small">desde {formatDate(entry.next.effective_start)}</span>
                          </>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td>
                        {entry?.intervals > 0 && (
                          <button type="button" className="link-button" onClick={() => setHistoryOf(attribute)}>
                            Historial ({entry.intervals})
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {historyOf && group.attributes.includes(historyOf) && (
            <AttributeHistory code={code} attribute={historyOf} onClose={() => setHistoryOf(null)} />
          )}
        </section>
      ))}

      <ChainOfCommandPanel employee={employee} chain={state.data.chain_of_command} canManage={canManage}
        onChanged={() => setReloadKey((k) => k + 1)} />
    </section>
  );
}

/** Editor de cambios con fecha efectiva: solo se envían los campos modificados. */
function RosterEditor({ employee, config, onCancel, onSaved }) {
  const code = employee.employee_code;
  const [effectiveDate, setEffectiveDate] = useState(todayIso());
  const [reason, setReason] = useState("");
  const [baseline, setBaseline] = useState(null); // valores vigentes a la fecha efectiva
  const [values, setValues] = useState({});
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(null);
  const [loadError, setLoadError] = useState(null);

  // Al cambiar la fecha efectiva se cargan los valores vigentes en esa fecha (punto de partida).
  useEffect(() => {
    if (!effectiveDate) return undefined;
    const controller = new AbortController();
    rosterApi
      .employee(code, effectiveDate, { signal: controller.signal })
      .then((data) => {
        const base = Object.fromEntries(data.attributes.map((a) => [a.code, a.current]));
        setBaseline(base);
        setValues(Object.fromEntries(Object.entries(base).map(([k, v]) => [k, v?.value ?? ""])));
        setLoadError(null);
      })
      .catch((err) => err.name !== "AbortError" && setLoadError(err.message));
    return () => controller.abort();
  }, [code, effectiveDate]);

  const changed = useMemo(() => {
    if (!baseline) return {};
    const diff = {};
    Object.entries(values).forEach(([k, v]) => {
      const before = baseline[k]?.value ?? "";
      if ((v ?? "") !== before) diff[k] = v === "" ? null : v;
    });
    return diff;
  }, [values, baseline]);

  const setValue = useCallback(
    (attrCode, value) => {
      setValues((current) => {
        const next = { ...current, [attrCode]: value };
        // Si cambia el padre (p. ej. Cliente), se limpia el hijo que ya no le pertenece (Marca).
        config.attributes
          .filter((a) => a.depends_on === attrCode && next[a.code])
          .forEach((child) => {
            const ok = config.optionsFor(child, { country: employee.country, parentValue: value }).some((o) => o.code === next[child.code]);
            if (!ok) next[child.code] = "";
          });
        return next;
      });
      setResult(null);
    },
    [config, employee.country],
  );

  const payload = () => ({ effective_date: effectiveDate, reason, values: changed });
  const fieldErrors = Object.fromEntries((result?.errors ?? []).filter((e) => e.field).map((e) => [e.field, e.message]));
  const labels = Object.fromEntries(config.attributes.map((a) => [a.code, a.name]));

  async function run(kind) {
    setBusy(kind);
    try {
      const body = kind === "validate" ? await rosterApi.validate(code, payload()) : await rosterApi.apply(code, payload());
      if (kind === "save" && body.saved) onSaved({ ...body, effective_date: effectiveDate });
      else setResult(body);
    } catch (err) {
      setResult(err.body?.errors ? err.body : { feedback: err.message, errors: [{ message: err.message }] });
    } finally {
      setBusy(null);
    }
  }

  const count = Object.keys(changed).length;
  return (
    <form
      className="roster-editor"
      onSubmit={(e) => {
        e.preventDefault();
        run("save");
      }}
      noValidate
    >
      <h3 className="section-title">Registrar cambios de roster</h3>
      <div className="form-grid">
        <div className="field">
          <label htmlFor="roster-effective" className="field__label">
            Fecha efectiva<span className="field__req">*</span>
          </label>
          <input
            id="roster-effective"
            type="date"
            value={effectiveDate}
            min={employee.hire_date}
            max={employee.termination_date ?? undefined}
            onChange={(e) => setEffectiveDate(e.target.value)}
            aria-invalid={Boolean(fieldErrors.effective_date)}
          />
          {fieldErrors.effective_date ? (
            <small className="field__error">{fieldErrors.effective_date}</small>
          ) : (
            <FieldHint>Los cambios rigen desde esta fecha; puede ser pasada (corrección) o futura.</FieldHint>
          )}
        </div>
        <div className="field">
          <label htmlFor="roster-reason" className="field__label">
            Motivo
          </label>
          <input
            id="roster-reason"
            value={reason}
            maxLength={300}
            placeholder="p. ej. Reasignación a nueva campaña"
            onChange={(e) => setReason(e.target.value)}
          />
          <FieldHint>Queda en el historial y la auditoría.</FieldHint>
        </div>
      </div>
      {loadError && <p className="error-box">{loadError}</p>}

      {baseline &&
        config.groups.map((group) => (
          <fieldset key={group.name} className="form-section">
            <legend className="form-section__title">{group.name}</legend>
            <div className="form-grid">
              {group.attributes.map((attribute) => {
                const parent = attribute.depends_on ? config.byCode[attribute.depends_on] : null;
                return (
                  <div key={attribute.code} className={changed[attribute.code] !== undefined ? "roster-field--changed" : undefined}>
                    <RosterField
                      attribute={attribute}
                      value={values[attribute.code]}
                      onChange={(v) => setValue(attribute.code, v)}
                      options={
                        attribute.data_type === "DIMENSION"
                          ? config.optionsFor(attribute, { country: employee.country, parentValue: parent ? values[parent.code] : undefined })
                          : undefined
                      }
                      currentLabel={baseline[attribute.code]?.label}
                      parentName={parent?.name.toLowerCase()}
                      error={fieldErrors[attribute.code]}
                      disabled={Boolean(busy)}
                    />
                  </div>
                );
              })}
            </div>
          </fieldset>
        ))}

      <FeedbackPanel
        result={result}
        labels={labels}
        title={result ? (result.valid ? "Resultado de la validación" : "El servidor rechazó los cambios") : null}
      />
      <footer className="form-actions">
        <span className="muted small roster-editor__count">
          {count ? `${count} dato${count === 1 ? "" : "s"} modificado${count === 1 ? "" : "s"}` : "Sin cambios"}
        </span>
        <button type="button" className="button button--ghost" onClick={onCancel} disabled={Boolean(busy)}>
          Cancelar
        </button>
        <button type="button" className="button button--ghost" onClick={() => run("validate")} disabled={!count || Boolean(busy)}>
          {busy === "validate" ? "Validando…" : "Validar sin guardar"}
        </button>
        <button type="submit" className="button" disabled={!count || !effectiveDate || Boolean(busy)}>
          {busy === "save" ? "Guardando…" : "Guardar cambios"}
        </button>
      </footer>
    </form>
  );
}
