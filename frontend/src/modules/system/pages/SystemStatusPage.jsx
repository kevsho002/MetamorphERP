import { useCallback, useEffect, useState } from "react";
import { api } from "../../../services/apiClient.js";

const LABELS = { ok: "Operativa", degraded: "Esquema incompleto", error: "Sin conexión" };

export default function SystemStatusPage() {
  const [state, setState] = useState({ loading: true, api: null, db: null, error: null });

  const check = useCallback(async (signal) => {
    setState((s) => ({ ...s, loading: true, error: null }));
    const [apiRes, dbRes] = await Promise.allSettled([
      api.get("/health", { signal }),
      api.get("/health/db", { signal }),
    ]);
    if (signal?.aborted) return;
    setState({
      loading: false,
      api: apiRes.status === "fulfilled" ? apiRes.value : null,
      // /health/db responde 503 con cuerpo JSON útil cuando la BD falla
      db: dbRes.status === "fulfilled" ? dbRes.value : dbRes.reason?.body ?? null,
      error: apiRes.status === "rejected" ? apiRes.reason?.message : null,
    });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    check(controller.signal);
    return () => controller.abort();
  }, [check]);

  const db = state.db;

  return (
    <section className="card">
      <div className="card__header">
        <h1 className="page-title">Estado del sistema</h1>
        <button type="button" className="button" onClick={() => check()} disabled={state.loading}>
          {state.loading ? "Verificando…" : "Volver a verificar"}
        </button>
      </div>

      {state.error && <p className="badge badge--error">API inaccesible: {state.error}</p>}

      <dl className="status-grid">
        <div className="status-item">
          <dt>API (FastAPI)</dt>
          <dd>
            <span className={`badge ${state.api ? "badge--ok" : "badge--error"}`}>
              {state.api ? `Operativa · ${state.api.environment}` : state.loading ? "…" : "Sin respuesta"}
            </span>
          </dd>
        </div>
        <div className="status-item">
          <dt>Base de datos (SQL Server)</dt>
          <dd>
            <span className={`badge badge--${db?.status === "ok" ? "ok" : db ? "error" : "info"}`}>
              {db ? LABELS[db.status] ?? db.status : state.loading ? "…" : "Desconocido"}
            </span>
          </dd>
        </div>
        {db?.database && (
          <>
            <div className="status-item">
              <dt>Base / versión</dt>
              <dd>
                {db.database} · v{db.server_version}
              </dd>
            </div>
            <div className="status-item">
              <dt>Latencia</dt>
              <dd>{db.latency_ms} ms</dd>
            </div>
          </>
        )}
        {db && (
          <div className="status-item">
            <dt>Tablas del modelo</dt>
            <dd>
              {db.expected_tables - (db.missing_tables?.length ?? 0)} / {db.expected_tables}
            </dd>
          </div>
        )}
      </dl>

      {db?.missing_tables?.length > 0 && (
        <p className="muted">
          Faltan: <code>{db.missing_tables.join(", ")}</code> — ejecute <code>database/deploy.ps1</code>.
        </p>
      )}
      {db?.error && <pre className="error-box">{db.error}</pre>}
    </section>
  );
}
