import { patternFor } from "../lib/formSpec.js";
import { formatWithMask, isNumericMask, maskPlaceholder, maxMaskLength } from "../lib/mask.js";

const INPUT_TYPES = { DATE: "date", EMAIL: "email" };

/**
 * Renderiza UN campo de la plantilla según su data_type:
 * STRING/EMAIL/DATE -> input; DECIMAL/INTEGER -> input numérico; CHOICE/choices -> select;
 * BOOLEAN -> Sí/No. Muestra obligatorio/recomendado, ayuda, ejemplo y errores.
 * Fase 7: `mask` de la plantilla formatea mientras se escribe (sin teclear guiones) y los campos con
 * `catalog` (bancos) se muestran como lista desplegable con los nombres del catálogo.
 */
export default function DynamicField({
  field,
  value,
  values,
  onChange,
  onBlur,
  error,
  serverError,
  disabled = false,
  options, // [{value, label}] para opciones con etiqueta (catálogos)
  restricted = false,
}) {
  const id = `field-${field.key}`;
  const describedBy = [];
  const message = error || serverError;
  if (message) describedBy.push(`${id}-error`);
  const rule = patternFor(field, values);
  const mask = rule?.mask;
  const hint = field.help || (rule?.example ? `Ejemplo: ${rule.example}` : null);
  if (hint) describedBy.push(`${id}-hint`);

  const common = {
    id,
    name: field.key,
    disabled: disabled || restricted,
    "aria-invalid": Boolean(message),
    "aria-describedby": describedBy.join(" ") || undefined,
    "aria-required": field.required || undefined,
    onBlur: () => onBlur?.(field.key),
  };
  const set = (v) => onChange(field.key, v);
  // Catálogos (p. ej. bancos): solo opciones activas, más el valor actual si quedó inactivo.
  const catalogOptions = field.options?.filter((o) => o.is_active || o.value === value);
  const choiceOptions = options ?? catalogOptions ?? field.choices?.map((c) => ({ value: c, label: c }));

  let control;
  if (restricted) {
    control = <input {...common} value="Restringido por su rol" readOnly />;
  } else if (field.data_type === "BOOLEAN") {
    control = (
      <select {...common} value={value ?? ""} onChange={(e) => set(e.target.value)}>
        <option value="">— Seleccione —</option>
        <option value="true">Sí</option>
        <option value="false">No</option>
      </select>
    );
  } else if (choiceOptions?.length) {
    const known = choiceOptions.some((o) => String(o.value).toUpperCase() === String(value ?? "").toUpperCase());
    control = (
      <select {...common} value={known ? choiceOptions.find((o) => String(o.value).toUpperCase() === String(value).toUpperCase()).value : value ?? ""} onChange={(e) => set(e.target.value)}>
        <option value="">{field.required ? "— Seleccione —" : "— Sin especificar —"}</option>
        {!known && value ? <option value={value}>{value} (valor actual)</option> : null}
        {choiceOptions.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    );
  } else {
    const numeric = field.data_type === "DECIMAL" || field.data_type === "INTEGER";
    const masked = Boolean(mask) && !INPUT_TYPES[field.data_type];
    control = (
      <input
        {...common}
        type={INPUT_TYPES[field.data_type] ?? "text"}
        inputMode={
          field.data_type === "DECIMAL" ? "decimal" : field.data_type === "INTEGER" || (masked && isNumericMask(mask)) ? "numeric" : undefined
        }
        value={masked ? formatWithMask(mask, value) : value ?? ""}
        maxLength={(masked ? maxMaskLength(mask) : null) ?? field.max_length ?? undefined}
        placeholder={rule?.example ?? (masked ? maskPlaceholder(mask) : numeric ? "0.00" : undefined)}
        autoComplete="off"
        onChange={(e) => set(masked ? formatWithMask(mask, e.target.value) : e.target.value)}
        data-mask={masked ? [].concat(mask).join(" | ") : undefined}
        className={field.transform === "upper" ? "input--upper" : undefined}
      />
    );
  }

  return (
    <div className={`field${message ? " field--invalid" : ""}`}>
      <label htmlFor={id} className="field__label">
        {field.label}
        {field.required && (
          <span className="field__req" aria-label="obligatorio" title="Obligatorio">
            *
          </span>
        )}
        {!field.required && field.recommended && <span className="tag tag--warn">Recomendado</span>}
        {field.kind === "attribute" && <span className="tag">País</span>}
      </label>
      {control}
      {hint && !message && (
        <small id={`${id}-hint`} className="field__hint">
          {hint}
        </small>
      )}
      {message && (
        <small id={`${id}-error`} className="field__error" role="alert">
          {message}
        </small>
      )}
    </div>
  );
}
