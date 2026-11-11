import { useEffect, useState } from "react";
import { employeesApi } from "../api.js";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Plantilla vigente para (país, fecha de ingreso). Se vuelve a consultar cuando
 * cambia cualquiera de los dos: una fecha anterior a un cambio normativo puede
 * exigir otra versión de la plantilla.
 */
export function useApplicableTemplate(country, date, { delay = 300 } = {}) {
  const [state, setState] = useState({ template: null, loading: false, error: null });

  useEffect(() => {
    if (!country || !ISO_DATE.test(date ?? "")) {
      setState({ template: null, loading: false, error: null });
      return undefined;
    }
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    const timer = setTimeout(() => {
      employeesApi
        .applicableTemplate(country, date, { signal: controller.signal })
        .then((template) => setState({ template, loading: false, error: null }))
        .catch((err) => {
          if (err.name === "AbortError") return;
          setState({ template: null, loading: false, error: err.message });
        });
    }, delay);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [country, date, delay]);

  return state;
}
