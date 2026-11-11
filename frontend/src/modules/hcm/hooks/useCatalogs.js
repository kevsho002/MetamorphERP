import { useEffect, useMemo, useState } from "react";
import { employeesApi } from "../api.js";

// Caché por sesión de pestaña: los catálogos cambian poco y se usan en todas las pantallas.
let cache = null;
let inflight = null;

function load() {
  if (cache) return Promise.resolve(cache);
  if (!inflight) {
    inflight = employeesApi
      .catalogs()
      .then((data) => {
        cache = data;
        return data;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

/** Países, centros de costos y opciones de campos base (GET /hcm/catalogs/). */
export function useCatalogs() {
  const [state, setState] = useState({ data: cache, loading: !cache, error: null });

  useEffect(() => {
    if (cache) return undefined;
    let alive = true;
    load()
      .then((data) => alive && setState({ data, loading: false, error: null }))
      .catch((err) => alive && setState({ data: null, loading: false, error: err.message }));
    return () => {
      alive = false;
    };
  }, []);

  const helpers = useMemo(() => {
    const data = state.data;
    const countries = data?.countries ?? [];
    const costCenters = data?.cost_centers ?? [];
    const label = (list, value) => list?.find((o) => o.value === value)?.label ?? value;
    return {
      countries,
      activeCountries: countries.filter((c) => c.is_active),
      country: (code) => countries.find((c) => c.code === code),
      costCentersFor: (code, { includeInactive = false } = {}) =>
        costCenters.filter((cc) => (!code || cc.country === code) && (includeInactive || cc.is_active)),
      statusLabel: (value) => label(data?.employment_statuses, value),
      genderLabel: (value) => label(data?.genders, value),
      payFrequencyLabel: (value) => label(data?.pay_frequencies, value),
      optionsFor: (key) =>
        ({ gender: data?.genders, pay_frequency: data?.pay_frequencies, employment_status: data?.employment_statuses })[key],
    };
  }, [state.data]);

  return { ...state, ...helpers };
}
