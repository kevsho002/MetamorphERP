import { useSyncExternalStore } from "react";

/**
 * Fase 21 — Formato dual de tiempos: HH:MM:SS (estricto) u horas decimales con dos decimales.
 * La preferencia es global (selector de la barra superior), se recuerda en este navegador y cambia al instante
 * en toda pantalla que muestre totales o cúmulos de tiempo (cada componente se suscribe con `useTimeFormat`).
 */
const KEY = "metamorph.timeFormat";
export const TIME_MODES = [
  { value: "hms", label: "HH:MM:SS" },
  { value: "decimal", label: "Horas decimales" },
];

function read() {
  try {
    return window.localStorage.getItem(KEY) === "decimal" ? "decimal" : "hms";
  } catch {
    return "hms";
  }
}

let mode = typeof window === "undefined" ? "hms" : read();
const listeners = new Set();

export function getTimeMode() {
  return mode;
}

export function setTimeMode(next) {
  mode = next === "decimal" ? "decimal" : "hms";
  try {
    window.localStorage.setItem(KEY, mode);
  } catch {
    // almacenamiento bloqueado: la preferencia dura esta visita
  }
  listeners.forEach((fn) => fn());
}

function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

const pad = (n) => String(n).padStart(2, "0");

/** Segundos → "HH:MM:SS" (las horas pueden pasar de 99) o "7.50" según el modo. Null / vacío → "—". */
export function formatSeconds(seconds, as = mode) {
  if (seconds === null || seconds === undefined || seconds === "" || Number.isNaN(Number(seconds))) return "—";
  const value = Number(seconds);
  if (as === "decimal") return (value / 3600).toFixed(2);
  const sign = value < 0 ? "-" : "";
  const total = Math.round(Math.abs(value));
  return `${sign}${pad(Math.floor(total / 3600))}:${pad(Math.floor((total % 3600) / 60))}:${pad(total % 60)}`;
}

export const formatMinutes = (minutes, as = mode) =>
  minutes === null || minutes === undefined || minutes === "" ? "—" : formatSeconds(Number(minutes) * 60, as);

export const formatHours = (hours, as = mode) =>
  hours === null || hours === undefined || hours === "" ? "—" : formatSeconds(Number(hours) * 3600, as);

/** Unidad corta para encabezados: "(HH:MM:SS)" u "(h)". */
export const unitLabel = (as = mode) => (as === "decimal" ? "h" : "HH:MM:SS");

/** Suscribe el componente a la preferencia; devuelve el modo y los formateadores ligados a él. */
export function useTimeFormat() {
  const current = useSyncExternalStore(subscribe, getTimeMode, () => "hms");
  return {
    mode: current,
    setMode: setTimeMode,
    seconds: (s) => formatSeconds(s, current),
    minutes: (m) => formatMinutes(m, current),
    hours: (h) => formatHours(h, current),
    unit: unitLabel(current),
  };
}
