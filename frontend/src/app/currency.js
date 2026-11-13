/**
 * Fase 22 — Símbolos de moneda dinámicos según el país de la cuenta / empresa (core.catCountry.CurrencyCode).
 * Cada planilla, boleta y liquidación trae su `currency`; aquí se traduce a su símbolo local. Los países que comparten
 * «$» se distinguen cuando conviven en la misma pantalla (MX$, COL$).
 */
export const CURRENCIES = {
  USD: { symbol: "$", name: "Dólar estadounidense", country: "SV" },
  GTQ: { symbol: "Q", name: "Quetzal", country: "GT" },
  MXN: { symbol: "MX$", name: "Peso mexicano", country: "MX" },
  COP: { symbol: "COL$", name: "Peso colombiano", country: "CO" },
};

const COUNTRY_CURRENCY = Object.fromEntries(Object.entries(CURRENCIES).map(([code, c]) => [c.country, code]));

export function currencySymbol(code) {
  return CURRENCIES[code]?.symbol ?? code ?? "$";
}

export function currencyOfCountry(countryCode) {
  return COUNTRY_CURRENCY[countryCode] ?? "USD";
}

/** 1234.5, "GTQ" → «Q 1,234.50»; negativos «-Q 12.00». */
export function formatCurrency(value, currency = "USD", digits = 2) {
  if (value === undefined || value === null || value === "") return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  const body = Math.abs(n).toLocaleString("es-SV", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  const symbol = currencySymbol(currency);
  const sep = symbol.length > 1 && /[A-Z]$/i.test(symbol) ? " " : symbol === "Q" ? " " : "";
  return `${n < 0 ? "-" : ""}${symbol}${sep}${body}`;
}
