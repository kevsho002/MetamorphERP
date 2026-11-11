/**
 * Utilidades del formulario dinámico de empleados.
 *
 * La especificación llega del backend (GET /hcm/employee-templates/applicable/ -> form.fields):
 * cada campo trae key, label, kind (core|attribute), data_type, required, recommended,
 * default, pattern, example, patterns_by_type, choices, min, max, min_length,
 * max_length, transform y help. Aquí se agrupa en secciones, se valida en el
 * navegador (retroalimentación inmediata) y se arma el cuerpo para la API.
 * La validación definitiva SIEMPRE es la del servidor (mismas reglas + BD).
 */

export const SECTIONS = [
  { id: "personal", title: "Datos personales", keys: ["first_name", "middle_name", "last_name", "second_last_name", "birth_date", "gender"] },
  { id: "identity", title: "Documento de identidad", keys: ["national_id_type", "national_id_number"] },
  { id: "contact", title: "Contacto", keys: ["work_email", "personal_email", "phone_number"] },
  { id: "job", title: "Contratación y compensación", keys: ["cost_center", "base_salary", "pay_frequency"] },
];

/** Campos que el formulario gestiona fuera de la plantilla (cabecera / estado laboral). */
export const HEADER_KEYS = new Set(["hire_date"]);

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const DECIMAL_RE = /^-?\d{1,16}([.,]\d+)?$/;
const INTEGER_RE = /^-?\d+$/;

export const isBlank = (value) => value === undefined || value === null || String(value).trim() === "";

export function applyTransform(field, value) {
  if (typeof value !== "string") return value;
  switch (field.transform) {
    case "upper":
      return value.toUpperCase();
    case "lower":
      return value.toLowerCase();
    case "strip_spaces":
      return value.replace(/\s+/g, "");
    default:
      return value;
  }
}

function safeRegExp(pattern) {
  try {
    return new RegExp(pattern, "u");
  } catch {
    return null; // sintaxis exclusiva de Python: lo valida el servidor
  }
}

/** Regla de formato efectiva (national_id_number depende del tipo de documento). */
export function patternFor(field, values) {
  if (field.patterns_by_type) {
    const type = String(values.national_id_type ?? "").toUpperCase();
    const rule = field.patterns_by_type[type];
    return rule ? { pattern: rule.pattern, example: rule.example, message: rule.message } : null;
  }
  return field.pattern ? { pattern: field.pattern, example: field.example, message: field.pattern_message } : null;
}

function ageAt(birth, on) {
  const b = new Date(`${birth}T00:00:00`);
  const d = new Date(`${on}T00:00:00`);
  if (Number.isNaN(b.getTime()) || Number.isNaN(d.getTime())) return null;
  let age = d.getFullYear() - b.getFullYear();
  if (d.getMonth() < b.getMonth() || (d.getMonth() === b.getMonth() && d.getDate() < b.getDate())) age -= 1;
  return age;
}

/** Devuelve el mensaje de error de UN campo, o null. */
export function validateField(field, rawValue, values, rules = {}) {
  if (isBlank(rawValue)) {
    if (field.required && isBlank(field.default)) return "Campo obligatorio.";
    return null;
  }
  const value = applyTransform(field, String(rawValue).trim());

  switch (field.data_type) {
    case "EMAIL":
      if (!EMAIL_RE.test(value)) return "Ingrese un correo válido (ej. nombre@empresa.com).";
      break;
    case "DECIMAL":
      if (!DECIMAL_RE.test(value)) return "Ingrese un número (ej. 850.00).";
      break;
    case "INTEGER":
      if (!INTEGER_RE.test(value)) return "Ingrese un número entero.";
      break;
    case "DATE":
      if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return "Ingrese una fecha válida.";
      break;
    default:
  }
  if (field.data_type === "DECIMAL" || field.data_type === "INTEGER") {
    const n = Number(value.replace(",", "."));
    if (field.min !== null && field.min !== undefined && n < Number(field.min)) return `El mínimo es ${field.min}.`;
    if (field.max !== null && field.max !== undefined && n > Number(field.max)) return `El máximo es ${field.max}.`;
  }
  if (field.choices?.length && !field.choices.some((c) => c.toUpperCase() === value.toUpperCase())) {
    return `Seleccione una opción válida: ${field.choices.join(", ")}.`;
  }
  if (field.min_length && value.length < field.min_length) return `Debe tener al menos ${field.min_length} caracteres.`;
  if (field.max_length && value.length > field.max_length) return `Máximo ${field.max_length} caracteres.`;

  const rule = patternFor(field, values);
  const re = rule && safeRegExp(rule.pattern);
  if (re && !re.test(value)) {
    const hint = rule.message ? ` (${rule.message})` : "";
    return rule.example ? `Formato inválido${hint}. Ejemplo válido: ${rule.example}.` : `Formato inválido${hint}.`;
  }

  if (field.key === "birth_date" && values.hire_date && rules.min_age) {
    const age = ageAt(value, values.hire_date);
    if (age !== null && age < Number(rules.min_age)) {
      return `A la fecha de ingreso tendría ${age} años; el mínimo del país es ${rules.min_age}.`;
    }
  }
  return null;
}

/** Valida todos los campos visibles. Devuelve {clave: mensaje}. */
export function validateAll(fields, values, rules, { skip = new Set() } = {}) {
  const errors = {};
  fields.forEach((field) => {
    if (skip.has(field.key)) return;
    const message = validateField(field, values[field.key], values, rules);
    if (message) errors[field.key] = message;
  });
  return errors;
}

/**
 * Agrupa los campos en secciones. Con `layout` (pestañas/secciones de la plantilla JSON del país)
 * se respeta el diseño del país; sin él, secciones fijas + atributos del país al final.
 */
export function groupFields(fields, countryName, layout) {
  const byKey = Object.fromEntries(fields.map((f) => [f.key, f]));
  if (Array.isArray(layout) && layout.length) {
    const placed = new Set();
    const sections = [];
    layout.forEach((tab) =>
      tab.sections.forEach((section) => {
        const list = section.fields.map((k) => byKey[k]).filter((f) => f && !HEADER_KEYS.has(f.key));
        list.forEach((f) => placed.add(f.key));
        if (list.length) {
          sections.push({ id: `${tab.id}-${section.id}`, tab: tab.label, title: section.title, description: section.description, fields: list });
        }
      }),
    );
    const rest = fields.filter((f) => !placed.has(f.key) && !HEADER_KEYS.has(f.key));
    if (rest.length) sections.push({ id: "other", title: "Otros datos", fields: rest });
    return sections;
  }
  const sections = SECTIONS.map((s) => ({
    ...s,
    fields: s.keys.map((k) => byKey[k]).filter(Boolean),
  })).filter((s) => s.fields.length);
  const placed = new Set(SECTIONS.flatMap((s) => s.keys));
  const remainingCore = fields.filter((f) => f.kind === "core" && !placed.has(f.key) && !HEADER_KEYS.has(f.key));
  if (remainingCore.length) sections.push({ id: "other", title: "Otros datos", fields: remainingCore });
  const attributes = fields.filter((f) => f.kind === "attribute");
  if (attributes.length) {
    sections.push({
      id: "country",
      title: `Datos requeridos por ${countryName ?? "el país"}`,
      description: "Campos definidos por la plantilla vigente del país (seguridad social, pensiones, datos bancarios…).",
      fields: attributes,
    });
  }
  return sections;
}

/** Valores iniciales: defaults de la plantilla sin pisar lo que el usuario ya escribió. */
export function withDefaults(fields, values) {
  const next = { ...values };
  fields.forEach((f) => {
    if (isBlank(next[f.key]) && !isBlank(f.default)) next[f.key] = f.default;
  });
  return next;
}

/** Valores de un empleado existente en la forma del formulario. */
export function valuesFromEmployee(employee) {
  const values = {};
  [
    "first_name", "middle_name", "last_name", "second_last_name", "national_id_type", "national_id_number",
    "birth_date", "gender", "work_email", "personal_email", "phone_number", "hire_date", "base_salary",
    "pay_frequency", "cost_center", "employment_status", "termination_date",
  ].forEach((k) => {
    values[k] = employee[k] ?? "";
  });
  Object.entries(employee.attributes ?? {}).forEach(([k, v]) => {
    values[k] = v ?? "";
  });
  return values;
}

/**
 * Cuerpo para POST/PATCH: campos base al primer nivel, atributos en `attributes`.
 * `omit` excluye campos restringidos por RBAC (p. ej. salario sin permiso de planilla).
 */
export function buildPayload(fields, values, { country, extra = {}, omit = new Set() } = {}) {
  const payload = { ...extra };
  if (country) payload.country = country;
  const attributes = {};
  fields.forEach((f) => {
    if (omit.has(f.key)) return;
    const raw = values[f.key];
    const value = typeof raw === "string" ? applyTransform(f, raw.trim()) : raw ?? "";
    if (f.kind === "attribute") attributes[f.key] = value;
    else payload[f.key] = value;
  });
  if (!omit.has("hire_date") && values.hire_date !== undefined) payload.hire_date = values.hire_date;
  payload.attributes = attributes;
  return payload;
}

/** Errores del servidor ({field, message}[]) -> {campo: "mensaje 1 · mensaje 2"}. */
export function serverErrorsByField(errors = []) {
  const map = {};
  errors.forEach((e) => {
    const key = (e.field ?? "").replace(/^attributes\./, "") || "_general";
    map[key] = map[key] ? `${map[key]} · ${e.message}` : e.message;
  });
  return map;
}
