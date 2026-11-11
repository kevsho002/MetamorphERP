const LOCALE = "es-SV";

/** "2026-03-01" -> "01/03/2026" (sin desfase de zona horaria). */
export function formatDate(value) {
  if (!value) return "—";
  const [y, m, d] = String(value).slice(0, 10).split("-");
  return d && m && y ? `${d}/${m}/${y}` : String(value);
}

export function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? String(value)
    : date.toLocaleString(LOCALE, { dateStyle: "short", timeStyle: "short" });
}

export function formatMoney(value, currency) {
  if (value === undefined || value === null || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  try {
    return new Intl.NumberFormat(LOCALE, { style: "currency", currency: currency || "USD" }).format(n);
  } catch {
    return `${n.toFixed(2)} ${currency ?? ""}`.trim();
  }
}

/** Fecha local de hoy en ISO (AAAA-MM-DD). */
export function todayIso() {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}
