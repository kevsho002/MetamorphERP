/**
 * Campo del roster dibujado a partir de su definición (GET /roster/attributes/):
 * texto, número, fecha, sí/no, lista de opciones o elemento de una dimensión
 * (filtrado por país y por el valor vigente del atributo del que depende).
 */
export default function RosterField({ attribute, value, onChange, options = [], currentLabel, error, disabled, parentName }) {
  const id = `roster-${attribute.code}`;
  const common = {
    id,
    name: attribute.code,
    disabled,
    "aria-invalid": Boolean(error),
    "aria-describedby": `${id}-hint`,
  };
  let input;
  switch (attribute.data_type) {
    case "DIMENSION": {
      const known = options.some((o) => o.code === value);
      input = (
        <select {...common} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
          <option value="">— Sin valor —</option>
          {value && !known && (
            <option value={value} disabled>
              {currentLabel ?? value} (no disponible)
            </option>
          )}
          {options.map((o) => (
            <option key={o.code} value={o.code}>
              {o.name}
            </option>
          ))}
        </select>
      );
      break;
    }
    case "CHOICE":
      input = (
        <select {...common} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
          <option value="">— Sin valor —</option>
          {attribute.choices.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      );
      break;
    case "BOOLEAN":
      input = (
        <select {...common} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
          <option value="">— Sin valor —</option>
          <option value="true">Sí</option>
          <option value="false">No</option>
        </select>
      );
      break;
    case "DATE":
      input = <input {...common} type="date" value={value ?? ""} onChange={(e) => onChange(e.target.value)} />;
      break;
    case "INTEGER":
      input = (
        <input
          {...common}
          type="number"
          step="1"
          min={attribute.rules?.min}
          max={attribute.rules?.max}
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
        />
      );
      break;
    default:
      input = (
        <input
          {...common}
          type="text"
          maxLength={attribute.rules?.max_length ?? 500}
          placeholder={attribute.rules?.example}
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
        />
      );
  }
  const hint =
    attribute.data_type === "DIMENSION" && attribute.depends_on && !options.length
      ? `Elija primero ${parentName ?? "el valor del que depende"}.`
      : attribute.help;
  return (
    <div className="field">
      <label htmlFor={id} className="field__label">
        {attribute.name}
      </label>
      {input}
      {error ? (
        <small id={`${id}-hint`} className="field__error" role="alert">
          {error}
        </small>
      ) : (
        hint && (
          <small id={`${id}-hint`} className="field__hint">
            {hint}
          </small>
        )
      )}
    </div>
  );
}
