import { useCallback, useEffect, useState } from "react";
import { schedulingApi } from "../api.js";

let cache = null;

/** Turnos activos, reglas de nocturnidad, ciclos de pago y opciones (se recargan con `reload` tras editar turnos). */
export function useSchedulingCatalogs() {
  const [state, setState] = useState({ loading: !cache, data: cache, error: null });
  const [key, setKey] = useState(0);

  useEffect(() => {
    if (cache && key === 0) return undefined;
    const controller = new AbortController();
    schedulingApi
      .catalogs({ signal: controller.signal })
      .then((data) => {
        cache = data;
        setState({ loading: false, data, error: null });
      })
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: cache, error: err.message }));
    return () => controller.abort();
  }, [key]);

  const reload = useCallback(() => setKey((k) => k + 1), []);
  const data = state.data ?? { shifts: [], night_rules: [], pay_cycles: [], sources: [], lunch_allocations: [], countries: [], flags: [] };
  return { ...state, ...data, reload };
}
