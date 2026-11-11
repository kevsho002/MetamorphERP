import { formatDate, formatMoney } from "../lib/format.js";

/** Resumen de la plantilla aplicada: nombre, vigencia, campos y reglas del país. */
export default function TemplateInfo({ template, loading, error, country, waiting }) {
  if (waiting) return <p className="template-info template-info--idle">Seleccione un país para cargar su plantilla.</p>;
  if (loading) return <p className="template-info template-info--idle">Buscando la plantilla vigente…</p>;
  if (error) {
    return (
      <p className="template-info template-info--error" role="alert">
        {error}
      </p>
    );
  }
  if (!template) return null;
  const fields = template.form?.fields ?? [];
  const required = fields.filter((f) => f.required).length;
  const rules = template.form?.rules ?? {};
  const ruleText = [
    rules.min_age && `edad mínima ${rules.min_age} años`,
    rules.max_age && `edad máxima ${rules.max_age} años`,
    rules.min_base_salary && `salario mínimo de referencia ${formatMoney(rules.min_base_salary, country?.currency)}`,
    rules.max_future_hire_days && `ingreso hasta ${rules.max_future_hire_days} días en el futuro`,
  ].filter(Boolean);

  return (
    <div className="template-info" aria-live="polite">
      <p>
        <strong>{template.name}</strong> · vigente desde {formatDate(template.effective_date)}
      </p>
      <p className="muted small">
        {fields.length} campos ({required} obligatorios)
        {ruleText.length > 0 && <> · Reglas: {ruleText.join(" · ")}</>}
      </p>
    </div>
  );
}
