import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { todayIso } from "../../hcm/lib/format.js";
import { actionsApi } from "../api.js";
import EmployeePicker from "../components/EmployeePicker.jsx";
import { AttachmentQueue, uploadQueue } from "../components/Attachments.jsx";
import RehireAlert from "../components/RehireAlert.jsx";
import WeeklyScheduleEditor, { defaultSchedule, scheduleFromSummary, scheduleInput } from "../components/WeeklyScheduleEditor.jsx";
import FieldHint from "../../../components/ui/FieldHint.jsx";

/** Asignación ADICIONAL (Fase 10): parte de un bloque corto el sábado; se suma al horario principal. */
const defaultAdditional = () => ({
  days: { mon: null, tue: null, wed: null, thu: null, fri: null, sat: [{ start: "08:00", end: "12:00", lunch_minutes: 0 }], sun: null },
  lunch_allocation: "PROPORTIONAL",
});

function AttributeField({ attr, value, onChange, error, context }) {
  const id = `pa-${attr.key}`;
  const label = (
    <span className="field__label">
      {attr.label}
      {attr.required && <span className="field__req">*</span>}
    </span>
  );
  if (attr.data_type === "SCHEDULE") {
    return (
      <fieldset className="form-section form-section--full">
        <legend className="form-section__title">
          {attr.label}
          {attr.required && <span className="field__req">*</span>}
        </legend>
        {attr.help_text && <p className="muted small">{attr.help_text}</p>}
        <WeeklyScheduleEditor value={value ?? defaultSchedule()} onChange={onChange} errors={error ?? []} employeeCode={context.employeeCode} effectiveDate={context.effectiveDate} idPrefix={`values.${attr.key}`} />
      </fieldset>
    );
  }
  const message = Array.isArray(error) ? error.map((e) => e.message).join(" ") : null;
  // Fase 22: valor vigente del roster / expediente (campos «Dato del roster»).
  const current = attr.data_type === "ROSTER" ? (attr.key === "cost_center" ? context.costCenter : context.roster?.[attr.key]) : null;
  let input;
  const asSelect = attr.data_type === "CHOICE" || attr.data_type === "ACTIVITY" || (attr.data_type === "ROSTER" && attr.input === "select");
  if (asSelect) {
    const options = attr.data_type === "ROSTER" && context.country ? attr.options.filter((o) => !o.country || o.country === context.country) : attr.options;
    input = (
      <select id={id} name={`values.${attr.key}`} value={value ?? ""} onChange={(e) => onChange(e.target.value)} required={attr.required}>
        <option value="">{attr.data_type === "ROSTER" && !attr.required ? "— Sin cambio —" : "— Seleccione —"}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
            {attr.data_type === "ACTIVITY" ? (o.paid ? " · pagado" : " · no pagado") : ""}
          </option>
        ))}
      </select>
    );
  } else if (attr.data_type === "TIME") {
    input = (
      <input id={id} type="time" step="1" name={`values.${attr.key}`} value={value ?? ""} onChange={(e) => onChange(e.target.value)} required={attr.required} />
    );
  } else if (attr.data_type === "BOOLEAN" || attr.input === "boolean") {
    input = <input id={id} type="checkbox" name={`values.${attr.key}`} checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />;
  } else if (attr.data_type === "LONG_TEXT") {
    input = <textarea id={id} name={`values.${attr.key}`} rows={3} value={value ?? ""} maxLength={attr.max_length ?? 2000} onChange={(e) => onChange(e.target.value)} required={attr.required} />;
  } else {
    const type = attr.data_type === "DATE" || attr.input === "date" ? "date" : ["INTEGER", "DECIMAL"].includes(attr.data_type) ? "number" : "text";
    input = (
      <input
        id={id}
        type={type}
        name={`values.${attr.key}`}
        value={value ?? ""}
        step={attr.data_type === "DECIMAL" ? "0.01" : attr.data_type === "INTEGER" ? "1" : undefined}
        min={attr.min_value ?? undefined}
        max={attr.max_value ?? undefined}
        maxLength={attr.max_length ?? undefined}
        onChange={(e) => onChange(e.target.value)}
        required={attr.required}
      />
    );
  }
  return (
    <label className="field" htmlFor={id}>
      {label}
      {input}
      {message ? (
        <small className="field__error">{message}</small>
      ) : (
        (attr.help_text || current) && (
          <FieldHint>
            {current && `Vigente: ${current}. `}
            {attr.help_text}
          </FieldHint>
        )
      )}
    </label>
  );
}

/** Fase 22: en los permisos «Día laborable completo» no se piden horas (se cubre todo el turno de cada día). */
function visibleAttr(type, attr, values) {
  if (type.effect === "LEAVE" && ["desde", "hasta"].includes(attr.key)) return values.alcance === "HORAS";
  return true;
}

/**
 * Elaborar una Acción de Personal: tipo (parametrizado en /admin/), empleado, fecha efectiva, justificación y los
 * campos EAV del tipo. Se guarda como borrador o se envía directo a la cadena de firmas.
 */
export default function NewActionPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [types, setTypes] = useState({ loading: true, rows: [], error: null });
  const [form, setForm] = useState({
    action_type: params.get("type") ?? "",
    employee_code: (params.get("employee") ?? "").toUpperCase(),
    effective_date: todayIso(),
    justification: "",
    values: {},
    acknowledge: [],
  });
  const [rehireAlert, setRehireAlert] = useState(null);
  const [employee, setEmployee] = useState(null);
  const [busy, setBusy] = useState(null);
  const [result, setResult] = useState(null);
  const [files, setFiles] = useState([]); // Fase 24: evidencias en cola

  useEffect(() => {
    const controller = new AbortController();
    actionsApi
      .types({ signal: controller.signal })
      .then((data) => setTypes({ loading: false, rows: data.results.filter((t) => t.can_create), error: null }))
      .catch((err) => err.name !== "AbortError" && setTypes({ loading: false, rows: [], error: err.message }));
    return () => controller.abort();
  }, []);

  // Datos del empleado: horario vigente para precargar el editor y si ya tiene su Primera AP.
  useEffect(() => {
    if (!/^[A-Z0-9]+-\d{4}-\d{6}-\d$/.test(form.employee_code)) {
      setEmployee(null);
      return undefined;
    }
    const controller = new AbortController();
    actionsApi
      .employee(form.employee_code, { signal: controller.signal })
      .then(setEmployee)
      .catch((err) => err.name !== "AbortError" && setEmployee({ error: err.status === 404 ? "No existe un empleado con ese ID." : err.message }));
    return () => controller.abort();
  }, [form.employee_code]);

  const type = types.rows.find((t) => t.code === form.action_type);
  const scheduleAttr = type?.attributes.find((a) => a.data_type === "SCHEDULE");

  // Al elegir un tipo de horario se precarga el horario vigente (o la fecha de ingreso para la Primera AP).
  useEffect(() => {
    if (!type || !employee || employee.error) return;
    setForm((f) => {
      const next = { ...f };
      if (type.is_initial_schedule && employee.hire_date) next.effective_date = employee.hire_date;
      if (scheduleAttr && !f.values[scheduleAttr.key]) {
        next.values = {
          ...f.values,
          [scheduleAttr.key]: type.schedule_mode === "ADDITIONAL" ? defaultAdditional() : scheduleFromSummary(employee.current_schedule?.schedule),
        };
      }
      return next;
    });
  }, [type, employee, scheduleAttr]);

  const set = (patch) => {
    setForm((f) => ({ ...f, ...patch }));
    setResult(null);
    if ("employee_code" in patch || "action_type" in patch) setRehireAlert(null);
  };
  // Fase 21: la alerta formal de recontratación llega como advertencia de la validación.
  useEffect(() => {
    const w = (result?.warnings ?? []).find((x) => x.code === "rehire_not_recommended");
    if (w) setRehireAlert(w);
  }, [result]);
  const acknowledged = form.acknowledge.includes("rehire_not_recommended");
  const setAcknowledged = (on) =>
    setForm((f) => ({ ...f, acknowledge: on ? ["rehire_not_recommended"] : [] }));
  const setValue = (key, value) => set({ values: { ...form.values, [key]: value } });
  const errorsFor = useMemo(() => {
    const map = {};
    (result?.errors ?? []).forEach((e) => {
      const field = String(e.field ?? "");
      const key = field.startsWith("values.") ? field.split(".")[1] : field || "_";
      (map[key] ??= []).push(e);
    });
    return map;
  }, [result]);

  const payload = (submit) => ({
    ...form,
    submit,
    values: Object.fromEntries(
      Object.entries(form.values).map(([k, v]) => [k, scheduleAttr && k === scheduleAttr.key ? scheduleInput(v) : v]),
    ),
  });

  const run = async (mode) => {
    setBusy(mode);
    try {
      if (mode === "validate") {
        setResult(await actionsApi.validate(payload(false)));
      } else {
        // Fase 24: con adjuntos, la AP se crea en borrador, se suben las evidencias y luego se envía (así una AP sin
        // firmas no queda aprobada —y congelada— antes de tener sus respaldos).
        const body = await actionsApi.create(payload(mode === "submit" && files.length === 0));
        let feedback = body.feedback;
        if (files.length) {
          const errors = await uploadQueue(body.action.folio, files);
          feedback += errors.length ? ` No se adjuntaron: ${errors.join(" · ")}` : ` ${files.length} adjunto(s) agregados.`;
          if (mode === "submit") {
            try {
              feedback = `${(await actionsApi.submit(body.action.folio)).feedback} ${files.length - errors.length} adjunto(s).`;
            } catch (err) {
              feedback += ` Quedó en borrador: ${err.message}`;
            }
          }
        }
        navigate(`/personnel-actions/${body.action.folio}`, { state: { feedback } });
      }
    } catch (err) {
      setResult(err.body && typeof err.body === "object" ? { valid: false, ...err.body } : { valid: false, errors: [{ message: err.message }] });
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Nueva acción de personal</h1>
          <p className="muted page-subtitle">
            Cada AP tiene folio único, fecha efectiva, justificación y firmas de aprobación por rol. Al aprobarse se aplica su
            efecto (por ejemplo, el nuevo horario desde la fecha efectiva).
          </p>
        </div>
      </header>
      {types.error && <p className="error-box">{types.error}</p>}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          run("submit");
        }}
      >
        <div className="form-grid">
          <label className="field">
            <span className="field__label">
              Tipo de acción<span className="field__req">*</span>
            </span>
            <select value={form.action_type} onChange={(e) => set({ action_type: e.target.value, values: {} })} required>
              <option value="">— Seleccione —</option>
              {types.rows.map((t) => (
                <option key={t.code} value={t.code}>
                  {t.name}
                </option>
              ))}
            </select>
            {type && (
              <FieldHint>
                {type.description}
                {type.creator_roles_labels?.length > 0 && ` · La elaboran: ${type.creator_roles_labels.join(", ")}.`}
              </FieldHint>
            )}
          </label>
          <div className="field">
            <span className="field__label">
              Colaborador<span className="field__req">*</span>
            </span>
            {/* Fase 23: solo colaboradores bajo su jerarquía directa o indirecta (el servidor lo valida). */}
            <EmployeePicker
              value={form.employee_code}
              selected={employee && !employee.error ? employee : null}
              onChange={(code) => set({ employee_code: code, values: {} })}
              includeTerminated={type?.effect === "REHIRE"}
              error={employee?.error ?? (errorsFor.employee_code ?? []).map((e) => e.message).join(" ")}
            />
            {employee && !employee.error && (
              <FieldHint>
                {employee.country} · ingreso {employee.hire_date}
                {!employee.initial_action && " · sin Primera AP de horario"}
              </FieldHint>
            )}
          </div>
          <label className="field">
            <span className="field__label">
              Fecha efectiva<span className="field__req">*</span>
            </span>
            <input type="date" value={form.effective_date} onChange={(e) => set({ effective_date: e.target.value })} readOnly={type?.is_initial_schedule} required />
            {type?.is_initial_schedule && <FieldHint>La Primera AP rige desde la fecha de ingreso.</FieldHint>}
            {type?.schedule_mode === "ADDITIONAL" && (
              <FieldHint>
                Asignación adicional: se suma al horario principal (turno partido o doble asignación) hasta «Vigente hasta»; sus bloques no
                pueden pedir las mismas horas que otro horario.
              </FieldHint>
            )}
          </label>
        </div>
        <label className="field">
          <span className="field__label">
            Observaciones / justificación<span className="field__req">*</span>
          </span>
          <textarea rows={3} maxLength={2000} value={form.justification} onChange={(e) => set({ justification: e.target.value })} required />
        </label>
        {type && (
          <div className="form-grid">
            {type.attributes.filter((attr) => visibleAttr(type, attr, form.values)).map((attr) => (
              <AttributeField
                key={attr.key}
                attr={attr}
                value={form.values[attr.key]}
                onChange={(v) => setValue(attr.key, v)}
                error={errorsFor[attr.key]}
                context={{
                  employeeCode: employee && !employee.error ? form.employee_code : null,
                  effectiveDate: form.effective_date,
                  roster: employee?.roster,
                  costCenter: employee?.cost_center,
                  country: employee && !employee.error ? employee.country : null,
                }}
              />
            ))}
          </div>
        )}
        {type && (
          <p className="muted small">
            Firmas: {type.steps.length ? type.steps.map((s) => `${s.order}. ${s.label} (${s.role_label})`).join(" → ") : "sin firmas (se aprueba al enviarse)"}
            {type.creator_signs_first_step && " · si su rol corresponde al primer paso, su envío cuenta como esa firma"}
            {type.admin_signs_any_step === false && " · firma estricta: cada paso lo firma únicamente su rol"}
          </p>
        )}
        <fieldset className="form-section attach-fieldset">
          <legend className="field__label">Adjuntos de respaldo (opcional)</legend>
          <AttachmentQueue files={files} onChange={setFiles} disabled={Boolean(busy)} />
        </fieldset>
        <RehireAlert alert={rehireAlert} acknowledged={acknowledged} onAcknowledge={setAcknowledged} />
        {result && (
          <div className={`alert ${result.valid ? "alert--ok" : "alert--error"}`} role="status">
            <p className="alert__text">{result.valid ? "La AP es válida." : "Revise lo siguiente:"}</p>
            {[...(result.errors ?? []), ...(result.warnings ?? [])].length > 0 && (
              <ul className="msg-list">
                {[...(result.errors ?? []), ...(result.warnings ?? []).filter((w) => w.code !== "rehire_not_recommended")].map((m, i) => (
                  <li key={i}>{m.message}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        <div className="form-actions">
          <Link className="button button--ghost" to={form.employee_code ? `/hcm/employees/${form.employee_code}?tab=actions` : "/personnel-actions"}>
            Cancelar
          </Link>
          <button type="button" className="button button--ghost" disabled={!type || Boolean(busy)} onClick={() => run("validate")}>
            {busy === "validate" ? "Validando…" : "Validar"}
          </button>
          <button type="button" className="button button--ghost" disabled={!type || Boolean(busy)} onClick={() => run("draft")}>
            {busy === "draft" ? "Guardando…" : "Guardar borrador"}
          </button>
          <button type="submit" className="button" disabled={!type || Boolean(busy) || (rehireAlert && !acknowledged)}>
            {busy === "submit" ? "Enviando…" : "Enviar a aprobación"}
          </button>
        </div>
      </form>
    </section>
  );
}
