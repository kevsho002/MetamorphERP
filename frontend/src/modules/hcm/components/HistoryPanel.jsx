import { useEffect, useState } from "react";
import { employeesApi } from "../api.js";
import { formatDateTime } from "../lib/format.js";

/** Registro de auditoría del empleado y de su cuenta vinculada (más reciente primero). */
export default function HistoryPanel({ code, refreshKey }) {
  const [state, setState] = useState({ loading: true, items: [], error: null });

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    employeesApi
      .history(code, { signal: controller.signal })
      .then((data) => setState({ loading: false, items: data.results, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, items: [], error: err.message }));
    return () => controller.abort();
  }, [code, refreshKey]);

  return (
    <section aria-labelledby="history-title">
      <h2 id="history-title" className="section-title">
        Historial (auditoría)
      </h2>
      {state.loading && <p className="muted">Cargando historial…</p>}
      {state.error && <p className="error-box">{state.error}</p>}
      {!state.loading && !state.error && state.items.length === 0 && <p className="muted">Sin eventos registrados.</p>}
      <ol className="timeline">
        {state.items.map((e) => (
          <li key={e.id} className={`timeline__item${e.success ? "" : " timeline__item--failed"}`}>
            <time dateTime={e.occurred_at}>{formatDateTime(e.occurred_at)}</time>
            <div>
              <p className="timeline__summary">{e.summary}</p>
              <p className="muted small">
                {e.category_label} · {e.actor ?? "sistema"}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
