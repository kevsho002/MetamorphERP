import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useBlocker, useNavigate, useParams } from "react-router-dom";
import { useAuth } from "../../../auth/AuthContext.jsx";
import { employeesApi } from "../api.js";
import AccountOptions from "../components/AccountOptions.jsx";
import DynamicField from "../components/DynamicField.jsx";
import FeedbackPanel from "../components/Feedback.jsx";
import TemplateInfo from "../components/TemplateInfo.jsx";
import TemporaryPassword from "../components/TemporaryPassword.jsx";
import { useApplicableTemplate } from "../hooks/useApplicableTemplate.js";
import { useCatalogs } from "../hooks/useCatalogs.js";
import {
  buildPayload,
  groupFields,
  serverErrorsByField,
  validateAll,
  valuesFromEmployee,
  withDefaults,
} from "../lib/formSpec.js";
import { formatDateTime, todayIso } from "../lib/format.js";

const FIXED_LABELS = {
  country: "País",
  hire_date: "Fecha de ingreso",
  employment_status: "Estado laboral",
  termination_date: "Fecha de retiro",
  employee_code: "ID corporativo",
};

/**
 * Alta (/hcm/employees/new) y edición (/hcm/employees/:code/edit) de un empleado.
 * La `key` reinicia el formulario por completo al pasar de un empleado a otro (o a un alta).
 */
export default function EmployeeFormPage() {
  const { code } = useParams();
  return <EmployeeForm key={code ?? "new"} code={code} />;
}

/** El formulario se construye con la plantilla vigente del país a la fecha de ingreso. */
function EmployeeForm({ code }) {
  const isEdit = Boolean(code);
  const navigate = useNavigate();
  const { hasPermission } = useAuth();
  const catalogs = useCatalogs();

  const [employee, setEmployee] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [country, setCountry] = useState("");
  const [values, setValues] = useState({ hire_date: todayIso() });
  const [touched, setTouched] = useState(() => new Set());
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(null); // "validate" | "save" | null
  const [result, setResult] = useState(null); // respuesta de validar/guardar
  const [serverErrors, setServerErrors] = useState({});
  const [requestError, setRequestError] = useState(null);
  const [created, setCreated] = useState(null);
  const [dirty, setDirty] = useState(false);
  // Fase 5: cuenta Metamorph vinculada (solo en el alta y si el rol puede crear usuarios).
  const canCreateAccount = !isEdit && hasPermission("users.create");
  const [account, setAccount] = useState({ create: false, role: "EMPLOYEE", username: "" });
  const formRef = useRef(null);

  // ----------------------------------------------------------- carga (edición)
  const loadEmployee = useCallback(
    (signal) => {
      setLoadError(null);
      return employeesApi
        .get(code, { signal })
        .then((emp) => {
          setEmployee(emp);
          setCountry(emp.country);
          setValues(valuesFromEmployee(emp));
          setDirty(false);
          setResult(null);
          setServerErrors({});
          setRequestError(null);
        })
        .catch((err) => err.name !== "AbortError" && setLoadError(err.status === 404 ? "El empleado no existe." : err.message));
    },
    [code],
  );

  useEffect(() => {
    if (!isEdit) return undefined;
    const controller = new AbortController();
    loadEmployee(controller.signal);
    return () => controller.abort();
  }, [isEdit, loadEmployee]);

  // ----------------------------------------------------------- plantilla vigente
  const { template, loading: templateLoading, error: templateError } = useApplicableTemplate(country, values.hire_date);
  const fields = useMemo(() => (template?.form?.fields ?? []).filter((f) => f.key !== "hire_date"), [template]);
  const rules = useMemo(() => template?.form?.rules ?? {}, [template]);
  const countryInfo = catalogs.country(country);

  useEffect(() => {
    if (fields.length) setValues((v) => withDefaults(fields, v));
  }, [fields]);

  const restricted = useMemo(() => {
    const set = new Set(employee?.restricted_fields ?? []);
    if (!hasPermission("payroll.view")) set.add("base_salary");
    return set;
  }, [employee, hasPermission]);

  const labels = useMemo(
    () => ({ ...FIXED_LABELS, ...Object.fromEntries(fields.map((f) => [f.key, f.label])) }),
    [fields],
  );
  const sections = useMemo(
    () => groupFields(fields, countryInfo?.name, template?.form?.layout),
    [fields, countryInfo, template],
  );

  // ----------------------------------------------------------- validación local
  const statusErrors = useMemo(() => {
    if (!isEdit) return {};
    const errs = {};
    if (values.employment_status === "TERMINATED" && !values.termination_date) {
      errs.termination_date = "Indique la fecha de retiro.";
    } else if (values.employment_status !== "TERMINATED" && values.termination_date) {
      errs.termination_date = "Solo un empleado «Retirado» puede tener fecha de retiro.";
    } else if (values.termination_date && values.hire_date && values.termination_date < values.hire_date) {
      errs.termination_date = "La fecha de retiro es anterior a la fecha de ingreso.";
    }
    return errs;
  }, [isEdit, values]);

  const clientErrors = useMemo(() => {
    const errs = { ...validateAll(fields, values, rules, { skip: restricted }), ...statusErrors };
    if (!country) errs.country = "Seleccione el país.";
    if (!values.hire_date) errs.hire_date = "Campo obligatorio.";
    return errs;
  }, [fields, values, rules, restricted, statusErrors, country]);

  const visibleError = (key) => (submitted || touched.has(key) ? clientErrors[key] : null);

  // ----------------------------------------------------------- cambios
  const onChange = useCallback((key, value) => {
    setValues((v) => ({ ...v, [key]: value }));
    setServerErrors((e) => {
      if (!e[key]) return e;
      const next = { ...e };
      delete next[key];
      return next;
    });
    setDirty(true);
  }, []);
  const onBlur = useCallback((key) => setTouched((t) => (t.has(key) ? t : new Set(t).add(key))), []);

  const changeCountry = (next) => {
    setCountry(next);
    // El centro de costos y los atributos dependen del país: se limpian para no arrastrar valores de otro país.
    setValues((v) => ({ hire_date: v.hire_date, ...Object.fromEntries(Object.entries(v).filter(([k]) => CARRY_OVER.has(k))) }));
    setServerErrors({});
    setResult(null);
    setDirty(true);
  };

  // ----------------------------------------------------------- envío
  const payload = () =>
    buildPayload(fields, values, {
      country: isEdit ? undefined : country,
      omit: restricted,
      extra: isEdit
        ? {
            employment_status: values.employment_status,
            termination_date: values.termination_date || "",
            row_version: employee?.row_version,
          }
        : canCreateAccount && account.create
          ? { user_account: { create: true, role: account.role, username: account.username } }
          : {},
    });

  const changeAccount = (next) => {
    setAccount(next);
    setServerErrors(({ user_account: _a, "user_account.role": _r, "user_account.username": _u, ...rest }) => rest);
    setDirty(true);
  };

  const focusFirstError = (errs) => {
    const first = Object.keys(errs)[0];
    const el = first && formRef.current?.querySelector(`[name="${CSS.escape(first)}"]`);
    el?.focus();
  };

  const handleResponse = (body) => {
    setResult(body);
    setServerErrors(serverErrorsByField(body.errors));
    if (body.errors?.length) focusFirstError(serverErrorsByField(body.errors));
  };

  const handleError = (err) => {
    if (err.body && Array.isArray(err.body.errors)) {
      handleResponse(err.body);
    } else {
      setRequestError({ message: err.message, stale: err.status === 409 });
    }
  };

  async function onValidate() {
    setBusy("validate");
    setRequestError(null);
    try {
      const body = isEdit ? await employeesApi.validateUpdate(code, payload()) : await employeesApi.validateCreate(payload());
      handleResponse(body);
    } catch (err) {
      handleError(err);
    } finally {
      setBusy(null);
    }
  }

  async function onSubmit(e) {
    e.preventDefault();
    setSubmitted(true);
    setRequestError(null);
    if (Object.keys(clientErrors).length) {
      setResult(null);
      focusFirstError(clientErrors);
      return;
    }
    setBusy("save");
    try {
      if (isEdit) {
        const body = await employeesApi.update(code, payload());
        setDirty(false);
        navigate(`/hcm/employees/${code}`, { state: { flash: body } });
      } else {
        const body = await employeesApi.create(payload());
        setDirty(false);
        setCreated(body);
      }
    } catch (err) {
      handleError(err);
    } finally {
      setBusy(null);
    }
  }

  const resetForAnother = () => {
    setCreated(null);
    setResult(null);
    setServerErrors({});
    setSubmitted(false);
    setTouched(new Set());
    setValues((v) => withDefaults(fields, { hire_date: v.hire_date }));
    setAccount((a) => ({ ...a, username: "" }));
    setDirty(false);
  };

  // ----------------------------------------------------------- cambios sin guardar
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) => dirty && !busy && currentLocation.pathname !== nextLocation.pathname,
  );
  useEffect(() => {
    if (blocker.state !== "blocked") return;
    if (window.confirm("Hay cambios sin guardar. ¿Desea salir de todas formas?")) blocker.proceed();
    else blocker.reset();
  }, [blocker]);
  useEffect(() => {
    if (!dirty) return undefined;
    const handler = (ev) => {
      ev.preventDefault();
      ev.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  // ----------------------------------------------------------- render
  if (isEdit && loadError) {
    return (
      <section className="card">
        <h1 className="page-title">Editar empleado</h1>
        <p className="error-box">{loadError}</p>
        <Link to="/hcm/employees">← Volver a la lista</Link>
      </section>
    );
  }
  if (isEdit && !employee) return <p className="muted">Cargando empleado…</p>;

  if (created) {
    const emp = created.employee;
    return (
      <section className="card">
        <div className="success-hero">
          <span className="success-hero__icon" aria-hidden="true">
            ✓
          </span>
          <div>
            <h1 className="page-title">Empleado registrado</h1>
            <p className="success-hero__code">
              <code>{emp.employee_code}</code> · {emp.full_name}
            </p>
          </div>
        </div>
        <FeedbackPanel result={created} labels={labels} />
        {created.user_account && (
          <TemporaryPassword username={created.user_account.username} password={created.user_account.temporary_password} />
        )}
        <div className="actions">
          <Link className="button" to={`/hcm/employees/${emp.employee_code}`}>
            Ver expediente del empleado
          </Link>
          <Link className="button button--ghost" to={`/hcm/employees/${emp.employee_code}?tab=documents`}>
            Cargar documentos y foto
          </Link>
          <button type="button" className="button button--ghost" onClick={resetForAnother}>
            Registrar otro en {countryInfo?.name ?? country}
          </button>
          <Link className="button button--ghost" to="/hcm/employees">
            Ir a la lista
          </Link>
        </div>
      </section>
    );
  }

  const pendingErrors = submitted ? Object.keys(clientErrors).length : 0;
  const ccOptions = catalogs
    .costCentersFor(country)
    .map((cc) => ({ value: cc.code, label: `${cc.code} — ${cc.name}` }));
  const optionsFor = (field) => {
    if (field.key === "cost_center") return ccOptions;
    const catalog = catalogs.optionsFor(field.key);
    if (!catalog) return undefined;
    return field.choices ? catalog.filter((o) => field.choices.includes(o.value)) : catalog;
  };

  return (
    <form ref={formRef} className="card card--form" onSubmit={onSubmit} noValidate>
      <nav className="breadcrumb" aria-label="Ruta">
        <Link to="/hcm/employees">Empleados</Link>
        {isEdit && (
          <>
            <span aria-hidden="true">/</span>
            <Link to={`/hcm/employees/${code}`}>{code}</Link>
          </>
        )}
        <span aria-hidden="true">/</span>
        <span>{isEdit ? "Editar" : "Nuevo"}</span>
      </nav>
      <header className="card__header">
        <div>
          <h1 className="page-title">{isEdit ? `Editar a ${employee.full_name}` : "Alta de empleado"}</h1>
          <p className="muted page-subtitle">
            {isEdit
              ? "Los cambios se validan con la plantilla del país vigente a la fecha de ingreso."
              : "Elija el país y la fecha de ingreso: el formulario se arma con la plantilla vigente de ese país."}
          </p>
        </div>
      </header>

      {/* ---------------------------------------------- país + fecha de ingreso */}
      <fieldset className="form-section">
        <legend className="form-section__title">Ubicación y vigencia</legend>
        <div className="form-grid">
          {isEdit ? (
            <div className="field">
              <span className="field__label">País</span>
              <p className="field__static">
                {employee.country_name} ({employee.country}) <span className="muted small">· no editable</span>
              </p>
            </div>
          ) : (
            <div className="field">
              <label htmlFor="field-country" className="field__label">
                País<span className="field__req">*</span>
              </label>
              <select
                id="field-country"
                name="country"
                value={country}
                onChange={(e) => changeCountry(e.target.value)}
                aria-invalid={Boolean(visibleError("country") || serverErrors.country)}
                onBlur={() => onBlur("country")}
              >
                <option value="">— Seleccione el país —</option>
                {catalogs.activeCountries.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.name} ({c.code})
                  </option>
                ))}
              </select>
              {(visibleError("country") || serverErrors.country) && (
                <small className="field__error" role="alert">
                  {visibleError("country") || serverErrors.country}
                </small>
              )}
            </div>
          )}
          <div className="field">
            <label htmlFor="field-hire_date" className="field__label">
              Fecha de ingreso<span className="field__req">*</span>
            </label>
            <input
              id="field-hire_date"
              name="hire_date"
              type="date"
              value={values.hire_date ?? ""}
              onChange={(e) => onChange("hire_date", e.target.value)}
              onBlur={() => onBlur("hire_date")}
              aria-invalid={Boolean(visibleError("hire_date") || serverErrors.hire_date)}
            />
            {visibleError("hire_date") || serverErrors.hire_date ? (
              <small className="field__error" role="alert">
                {visibleError("hire_date") || serverErrors.hire_date}
              </small>
            ) : (
              <small className="field__hint">Define qué versión de la plantilla del país aplica.</small>
            )}
          </div>
          {isEdit && (
            <div className="field">
              <span className="field__label">ID corporativo</span>
              <p className="field__static">
                <code>{employee.employee_code}</code> <span className="muted small">· generado por el sistema</span>
              </p>
            </div>
          )}
        </div>
        <TemplateInfo
          template={template}
          loading={templateLoading}
          error={templateError}
          country={countryInfo}
          waiting={!country}
        />
      </fieldset>

      {/* ---------------------------------------------- secciones dinámicas */}
      {template &&
        sections.map((section, i) => (
          <Fragment key={section.id}>
          {section.tab && section.tab !== sections[i - 1]?.tab && <h2 className="form-section__tab">{section.tab}</h2>}
          <fieldset className="form-section">
            <legend className="form-section__title">{section.title}</legend>
            {section.description && <p className="muted small form-section__desc">{section.description}</p>}
            <div className="form-grid">
              {section.fields.map((field) => (
                <DynamicField
                  key={field.key}
                  field={field}
                  value={values[field.key]}
                  values={values}
                  onChange={onChange}
                  onBlur={onBlur}
                  error={visibleError(field.key)}
                  serverError={serverErrors[field.key]}
                  options={optionsFor(field)}
                  restricted={restricted.has(field.key)}
                />
              ))}
            </div>
          </fieldset>
          </Fragment>
        ))}

      {/* ---------------------------------------------- estado laboral (solo edición) */}
      {template && isEdit && (
        <fieldset className="form-section">
          <legend className="form-section__title">Estado laboral</legend>
          <div className="form-grid">
            <DynamicField
              field={{ key: "employment_status", label: "Estado laboral", data_type: "CHOICE", required: true }}
              value={values.employment_status}
              values={values}
              onChange={onChange}
              onBlur={onBlur}
              serverError={serverErrors.employment_status}
              options={catalogs.optionsFor("employment_status")}
            />
            <DynamicField
              field={{
                key: "termination_date",
                label: "Fecha de retiro",
                data_type: "DATE",
                help: "Obligatoria solo si el estado es «Retirado».",
              }}
              value={values.termination_date}
              values={values}
              onChange={onChange}
              onBlur={onBlur}
              error={visibleError("termination_date")}
              serverError={serverErrors.termination_date}
            />
          </div>
        </fieldset>
      )}

      {/* ---------------------------------------------- cuenta Metamorph (alta) */}
      {template && canCreateAccount && (
        <AccountOptions
          value={account}
          onChange={changeAccount}
          preview={result?.user_account_preview}
          serverErrors={serverErrors}
          disabled={Boolean(busy)}
        />
      )}

      {/* ---------------------------------------------- retroalimentación */}
      {pendingErrors > 0 && !result && (
        <p className="alert alert--error" role="alert">
          Revise {pendingErrors === 1 ? "el campo marcado" : `los ${pendingErrors} campos marcados`} antes de guardar.
        </p>
      )}
      {requestError && (
        <div className="alert alert--error" role="alert">
          <p className="alert__text">{requestError.message}</p>
          {requestError.stale && (
            <button type="button" className="button button--sm" onClick={() => loadEmployee()}>
              Recargar datos actuales
            </button>
          )}
        </div>
      )}
      <FeedbackPanel
        result={result}
        labels={labels}
        title={result ? (result.valid ? "Resultado de la validación" : "El servidor rechazó los datos") : null}
      />

      <footer className="form-actions">
        <Link className="button button--ghost" to={isEdit ? `/hcm/employees/${code}` : "/hcm/employees"}>
          Cancelar
        </Link>
        <button type="button" className="button button--ghost" onClick={onValidate} disabled={!template || Boolean(busy)}>
          {busy === "validate" ? "Validando…" : "Validar sin guardar"}
        </button>
        <button type="submit" className="button" disabled={!template || Boolean(busy)}>
          {busy === "save" ? "Guardando…" : isEdit ? "Guardar cambios" : "Dar de alta"}
        </button>
      </footer>
      {isEdit && employee.updated_at && (
        <p className="muted small">
          Última modificación: {formatDateTime(employee.updated_at)} por {employee.updated_by}
        </p>
      )}
    </form>
  );
}

/** Al cambiar de país se conservan los datos personales (no dependen del país). */
const CARRY_OVER = new Set([
  "first_name", "middle_name", "last_name", "second_last_name", "birth_date", "gender",
  "work_email", "personal_email", "base_salary", "pay_frequency",
]);
