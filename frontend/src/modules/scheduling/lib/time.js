/** Utilidades de tiempo del módulo de horarios (los minutos se muestran como H:MM). */

export const DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
export const DAY_LABELS = { mon: "Lunes", tue: "Martes", wed: "Miércoles", thu: "Jueves", fri: "Viernes", sat: "Sábado", sun: "Domingo" };

/** 450 -> "7:30"; -15 -> "-0:15". */
export function fmtMinutes(value) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Math.round(Number(value));
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  return `${sign}${Math.floor(abs / 60)}:${String(abs % 60).padStart(2, "0")}`;
}

/** "2026-10-05T22:00" -> "05/10 22:00" */
export function fmtStamp(value) {
  if (!value) return "—";
  const [d, t] = String(value).split("T");
  const [, m, day] = d.split("-");
  return `${day}/${m}${t ? ` ${t.slice(0, 5)}` : ""}`;
}

export function toMinutes(hhmm) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(hhmm ?? "");
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
}

/** Duración bruta de la jornada (cruza la medianoche si fin <= inicio). */
export function grossMinutes(start, end) {
  const s = toMinutes(start);
  const e = toMinutes(end);
  if (s === null || e === null || s === e) return null;
  return e > s ? e - s : e + 1440 - s;
}

export function addDays(iso, days) {
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d + days));
  return date.toISOString().slice(0, 10);
}

/** Lunes de la semana de una fecha ISO. */
export function mondayOf(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  const weekday = (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
  return addDays(iso, -weekday);
}

export const FLAG_CLASS = {
  OK: "badge--ok",
  SHORT: "badge--warn",
  OVER: "badge--info",
  ABSENT: "badge--error",
  UNSCHEDULED: "badge--warn",
  PENDING: "badge--muted",
  REST: "badge--muted",
};
