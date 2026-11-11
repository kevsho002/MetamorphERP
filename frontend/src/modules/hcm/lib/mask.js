/**
 * Máscaras de entrada definidas en la plantilla JSON del país (regla `mask`, Fase 7).
 *
 *   "########-#"                         DUI:      012345678  ->  01234567-8
 *   ["########-#", "####-######-###-#"]  NIT SV:   se usa la máscara más corta en la que caben los caracteres
 *
 * Marcadores: # dígito, @ letra, * letra o dígito; cualquier otro carácter es literal y lo inserta
 * el sistema (el usuario no escribe guiones ni espacios). Los literales se agregan solo cuando ya hay
 * un carácter después, de modo que borrar con Retroceso funciona con naturalidad.
 * El backend aplica la misma regla (apps/employees/masks.py) y siempre valida con `pattern`.
 */

const SLOTS = {
  "#": (c) => c >= "0" && c <= "9",
  "@": (c) => /\p{L}/u.test(c),
  "*": (c) => (c >= "0" && c <= "9") || /\p{L}/u.test(c),
};

export const capacity = (mask) => [...mask].filter((c) => SLOTS[c]).length;

export function normalizeMasks(mask) {
  if (!mask) return [];
  const list = Array.isArray(mask) ? mask : [mask];
  return list.filter((m) => typeof m === "string" && m).sort((a, b) => capacity(a) - capacity(b));
}

/** Aplica la máscara a lo que el usuario escribió o pegó. */
export function formatWithMask(mask, raw) {
  const masks = normalizeMasks(mask);
  const text = raw === null || raw === undefined ? "" : String(raw);
  if (!masks.length || !text) return text;
  const literals = new Set(masks.flatMap((m) => [...m].filter((c) => !SLOTS[c])));
  const significant = [...text].filter((c) => !literals.has(c) && !/\s/u.test(c));
  const chosen = masks.find((m) => capacity(m) >= significant.length) ?? masks[masks.length - 1];
  let out = "";
  let i = 0;
  for (const slot of chosen) {
    if (SLOTS[slot]) {
      while (i < significant.length && !SLOTS[slot](significant[i])) i += 1; // descarta caracteres que no calzan
      if (i >= significant.length) break;
      out += significant[i];
      i += 1;
    } else {
      if (i >= significant.length) break;
      out += slot;
    }
  }
  return out;
}

/** Texto de ayuda: "########-#" -> "00000000-0". */
export function maskPlaceholder(mask) {
  const masks = normalizeMasks(mask);
  if (!masks.length) return undefined;
  return masks.map((m) => m.replace(/#/g, "0").replace(/@/g, "A").replace(/\*/g, "X")).join(" o ");
}

/** Teclado numérico en móviles si la máscara solo admite dígitos. */
export const isNumericMask = (mask) => normalizeMasks(mask).every((m) => ![...m].some((c) => c === "@" || c === "*"));

export const maxMaskLength = (mask) => Math.max(0, ...normalizeMasks(mask).map((m) => m.length)) || undefined;
