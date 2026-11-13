import { useSyncExternalStore } from "react";
import { api } from "../services/apiClient.js";
import { setTimeMode } from "./timeFormat.js";

/**
 * Fase 22 — Apariencia y configuraciones visuales.
 *
 * Preferencias PERSONALES: modo día / noche / según el sistema, densidad, formato de tiempos y (Fase 23) una paleta
 * PERSONAL opcional. Se guardan en el perfil del usuario (PUT /system/appearance/me/) y en este navegador.
 * La paleta CORPORATIVA global la define el Administrador (GET /system/client-config/ → brand_palette) y es el respaldo
 * de fábrica: sin paleta personal, rige la global (y el Django Admin muestra la misma paleta efectiva).
 * Se aplican como atributos del <html> (data-theme, data-density, data-palette) que redefinen los tokens de color.
 */
const KEY = "metamorph.appearance";
export const THEMES = [
  { value: "system", label: "Según el sistema" },
  { value: "light", label: "Día (claro)" },
  { value: "dark", label: "Noche (oscuro)" },
];
export const DENSITIES = [
  { value: "comfortable", label: "Cómoda" },
  { value: "compact", label: "Compacta" },
];
/** Paletas corporativas: color primario (barra superior) y acento (botones, enlaces, foco). */
export const PALETTES = {
  NAVY: { label: "Azul corporativo", primary: "#1f3a5f", accent: "#2f7dd1" },
  TEAL: { label: "Verde azulado", primary: "#0f4c5c", accent: "#0f9b8e" },
  WINE: { label: "Vino", primary: "#5b1a32", accent: "#b23a63" },
  GRAPHITE: { label: "Grafito", primary: "#25282d", accent: "#5b7cfa" },
  FOREST: { label: "Bosque", primary: "#1f4d2b", accent: "#3a9d5d" },
};

const DEFAULTS = { theme: "system", density: "comfortable" };

function read() {
  try {
    return { ...DEFAULTS, ...JSON.parse(window.localStorage.getItem(KEY) || "{}") };
  } catch {
    return { ...DEFAULTS };
  }
}

let prefs = typeof window === "undefined" ? { ...DEFAULTS } : read();
let brand = { palette: "NAVY", accent: "" };
let personal = { palette: "", accent: "" };
const listeners = new Set();
const media = typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

function emit() {
  apply();
  listeners.forEach((fn) => fn());
}

function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function resolvedTheme(p = prefs) {
  if (p.theme === "dark" || p.theme === "light") return p.theme;
  return media?.matches ? "dark" : "light";
}

function hexToRgb(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function shade(hex, factor) {
  const rgb = hexToRgb(hex);
  if (!rgb) return hex;
  const f = (c) => Math.max(0, Math.min(255, Math.round(factor < 0 ? c * (1 + factor) : c + (255 - c) * factor)));
  return `#${rgb.map((c) => f(c).toString(16).padStart(2, "0")).join("")}`;
}

/** Paleta efectiva: la personal si el usuario eligió una; si no, la global. */
function effectivePalette() {
  return personal.palette ? personal : brand;
}

/** Colores de una paleta (la personalizada deriva el primario del acento). Sin argumentos: la efectiva. */
export function paletteColors(palette = effectivePalette().palette, accent = effectivePalette().accent) {
  if (palette === "CUSTOM" && hexToRgb(accent)) return { primary: shade(accent, -0.55), accent };
  return PALETTES[palette] ?? PALETTES.NAVY;
}

export function apply() {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.dataset.theme = resolvedTheme();
  root.dataset.density = prefs.density;
  const { primary, accent } = paletteColors();
  const dark = root.dataset.theme === "dark";
  root.style.setProperty("--color-primary", dark ? shade(primary, -0.35) : primary);
  root.style.setProperty("--color-accent", dark ? shade(accent, 0.25) : accent);
  root.style.colorScheme = dark ? "dark" : "light";
}

export function setAppearance(patch) {
  prefs = { ...prefs, ...patch };
  try {
    window.localStorage.setItem(KEY, JSON.stringify(prefs));
  } catch {
    // almacenamiento bloqueado: la preferencia dura esta visita
  }
  emit();
  saveProfile(patch);
}

/** La paleta corporativa llega con la configuración del cliente (y al guardarla en Apariencia). */
export function setBrand(palette, accent) {
  if (palette === brand.palette && (accent || "") === brand.accent) return;
  brand = { palette: palette || "NAVY", accent: accent || "" };
  emit();
}

media?.addEventListener?.("change", () => prefs.theme === "system" && emit());

let snapshot = {};
function getSnapshot() {
  const next = {
    ...prefs, palette: brand.palette, accent: brand.accent, personalPalette: personal.palette, personalAccent: personal.accent,
    source: personal.palette ? "personal" : "global", resolved: resolvedTheme(),
  };
  if (Object.keys(next).some((k) => next[k] !== snapshot[k])) snapshot = next;
  return snapshot;
}

// ------------------------------------------------------------- perfil (Fase 23)
let saveTimer = null;
let pendingPatch = {};

/** Guarda en el perfil (con un pequeño retardo para agrupar cambios seguidos). */
export function saveProfile(patch) {
  pendingPatch = { ...pendingPatch, ...patch };
  window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(() => {
    const body = pendingPatch;
    pendingPatch = {};
    api.put("/system/appearance/me/", body).catch(() => {});
  }, 400);
}

/** Paleta personal: vista previa inmediata; `persist` la guarda en el perfil. */
export function setPersonalPalette(palette, accent = "", persist = false) {
  personal = { palette: palette || "", accent: palette === "CUSTOM" ? accent || "" : "" };
  emit();
  if (persist) return api.put("/system/appearance/me/", { palette: personal.palette, accent: personal.accent });
  return Promise.resolve(null);
}

/** Descarta la paleta personal: vuelve a la global (respaldo de fábrica). */
export function resetPersonalPalette() {
  personal = { palette: "", accent: "" };
  emit();
  return api.delete("/system/appearance/me/");
}

/** Al cerrar sesión: la paleta personal deja de aplicar (la pantalla de acceso usa la global). */
export function clearPersonal() {
  personal = { palette: "", accent: "" };
  emit();
}

/** Carga las preferencias del perfil al iniciar sesión (siguen al usuario entre equipos). */
export async function loadProfile() {
  try {
    const { personal: p } = await api.get("/system/appearance/me/");
    if (!p) return;
    if (p.saved) {
      prefs = { ...prefs, theme: p.theme, density: p.density };
      try {
        window.localStorage.setItem(KEY, JSON.stringify(prefs));
      } catch {
        // sin almacenamiento local
      }
      setTimeMode(p.time_mode);
    }
    personal = { palette: p.palette || "", accent: p.accent || "" };
    emit();
  } catch {
    // sin conexión: se conservan las preferencias locales
  }
}

export function useAppearance() {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

apply();
