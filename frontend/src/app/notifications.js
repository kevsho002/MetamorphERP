import { useEffect, useSyncExternalStore } from "react";
import { api } from "../services/apiClient.js";

/**
 * Fase 22 — Centro de notificaciones operativas. Un solo sondeo compartido por la campana de la barra superior y la
 * página «Notificaciones»: cada `poll_seconds` (30 s), al volver a la pestaña y tras marcar como leídas.
 */
const EMPTY = { loading: true, results: [], unread: 0, total: 0, by_kind: {}, error: null, poll_seconds: 30 };
let state = EMPTY;
let timer = null;
let users = 0;
const listeners = new Set();

function emit(next) {
  state = { ...state, ...next };
  listeners.forEach((fn) => fn());
}

export async function refreshNotifications() {
  try {
    const data = await api.get("/system/notifications/");
    emit({ ...data, loading: false, error: null });
  } catch (err) {
    emit({ loading: false, error: err.message });
  }
}

export async function markNotifications(keys, all = false) {
  const data = await api.post("/system/notifications/", all ? { all: true } : { keys });
  emit({ ...data, loading: false, error: null });
}

const onVisible = () => document.visibilityState === "visible" && refreshNotifications();

function start() {
  users += 1;
  if (users > 1) return;
  refreshNotifications();
  timer = window.setInterval(refreshNotifications, (state.poll_seconds || 30) * 1000);
  document.addEventListener("visibilitychange", onVisible);
}

function stop() {
  users -= 1;
  if (users > 0) return;
  window.clearInterval(timer);
  timer = null;
  document.removeEventListener("visibilitychange", onVisible);
}

function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function useNotifications() {
  useEffect(() => {
    start();
    return stop;
  }, []);
  return useSyncExternalStore(subscribe, () => state, () => state);
}

export const KIND_LABELS = {
  ap: "AP por firmar",
  payroll: "Planillas",
  wfm: "Solicitudes WFM",
  hire: "Altas de empleados",
  noshow: "Ausentismo de hoy",
};

export function timeAgo(iso) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < -3600) return "próximamente";
  if (diff < 60) return "hace un momento";
  if (diff < 3600) return `hace ${Math.floor(diff / 60)} min`;
  if (diff < 86400) return `hace ${Math.floor(diff / 3600)} h`;
  const days = Math.floor(diff / 86400);
  return days === 1 ? "ayer" : `hace ${days} días`;
}
