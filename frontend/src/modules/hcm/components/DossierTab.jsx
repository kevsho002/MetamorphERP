import { formatDate, formatDateTime, formatMoney } from "../lib/format.js";
import { formatWithMask } from "../lib/mask.js";

const RESTRICTED = (
  <span className="restricted" title="Su rol no tiene acceso a este dato">
    Restringido
  </span>
);

function displayValue(field, employee, catalogs) {
  const value = field.value;
  if (value === null || value === undefined || value === "") return null;
  switch (field.key) {
    case "base_salary":
      return formatMoney(value, employee.currency);
    case "gender":
      return catalogs.genderLabel(value);
    case "pay_frequency":
      return catalogs.payFrequencyLabel(value);
    case "cost_center":
      return `${value}${employee.cost_center_name ? ` — ${employee.cost_center_name}` : ""}`;
    default:
  }
  if (field.display) return field.display; // catálogos: nombre del banco en vez del código
  if (field.mask) return formatWithMask(field.mask, value);
  if (field.data_type === "DATE") return formatDate(value);
  if (field.data_type === "BOOLEAN") return value === "true" || value === true ? "Sí" : "No";
  return String(value);
}

/**
 * Una pestaña del expediente: secciones y campos tal como los define la plantilla del país
 * (layout JSON), con los valores del empleado (núcleo + EAV) y su procedencia.
 */
export default function DossierTab({ tab, employee, catalogs, templateId }) {
  return (
    <div className="dossier-tab">
      {tab.description && <p className="muted small">{tab.description}</p>}
      {tab.sections.map((section) => (
        <section key={section.id} className="detail-section">
          <h3 className="section-title">{section.title}</h3>
          {section.description && <p className="muted small form-section__desc">{section.description}</p>}
          <dl className="detail-grid">
            {section.fields.map((field) => {
              const shown = field.restricted ? RESTRICTED : displayValue(field, employee, catalogs);
              const recorded = field.recorded;
              const otherVersion = recorded && templateId && recorded.template_id !== templateId;
              return (
                <div key={field.key} className={`detail-item${field.missing ? " detail-item--missing" : ""}`}>
                  <dt>
                    {field.label}
                    {field.required && <span className="field__req" title="Obligatorio en esta versión de la plantilla">*</span>}
                  </dt>
                  <dd>
                    {shown ?? <span className="muted">—</span>}
                    {field.missing && <span className="tag tag--warn">Pendiente</span>}
                  </dd>
                  {otherVersion && (
                    <small className="detail-item__note" title={`Actualizado ${formatDateTime(recorded.updated_at)} por ${recorded.updated_by || "—"}`}>
                      Registrado con «{recorded.template_name}» (desde {formatDate(recorded.template_effective_date)})
                    </small>
                  )}
                </div>
              );
            })}
          </dl>
        </section>
      ))}
    </div>
  );
}
