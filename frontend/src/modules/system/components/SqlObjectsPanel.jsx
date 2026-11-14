import { useEffect, useMemo, useState } from "react";
import { api } from "../../../services/apiClient.js";
import { formatDateTime } from "../../hcm/lib/format.js";

const STATUS_TONE = { OK: "ok", DISABLED: "warn", BROKEN: "error" };
const PLURAL = { VIEW: "Vistas", PROCEDURE: "Procedimientos almacenados", FUNCTION: "Funciones", TRIGGER: "Triggers" };

/**
 * Fase 25 — Catálogo de objetos programables de SQL Server: vistas, procedimientos almacenados, funciones y triggers
 * con su esquema, estado (activo, deshabilitado o con referencias sin resolver), propósito (MS_Description), tabla y
 * eventos de cada trigger y, si el servidor lo permite, sus ejecuciones desde el último reinicio.
 */
export default function SqlObjectsPanel({ colors }) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [type, setType] = useState("");
  const [schema, setSchema] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    api
      .get("/system/data/objects/", { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, []);

  const d = state.data;
  const rows = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (d?.results ?? []).filter(
      (o) => (!type || o.type === type) && (!schema || o.schema === schema) && (!status || o.status === status)
        && (!term || `${o.name} ${o.parent ?? ""} ${o.purpose}`.toLowerCase().includes(term)),
    );
  }, [d, type, schema, status, search]);

  if (state.loading) return <p className="muted">Cargando el catálogo de objetos…</p>;
  if (state.error) return <p className="error-box">{state.error}</p>;

  return (
    <div className="sqlobj">
      <dl className="kpis">
        {d.types.map((t) => (
          <div key={t.value} className="kpi">
            <dt>{PLURAL[t.value] ?? t.label}</dt>
            <dd>{d.counts[t.value] ?? 0}</dd>
          </div>
        ))}
        <div className={`kpi ${d.problems ? "kpi--warn" : "kpi--ok"}`}>
          <dt>Con observaciones</dt>
          <dd>{d.problems}</dd>
        </div>
      </dl>
      <details className="sqlobj__schemas">
        <summary>Esquemas por módulo ({d.schemas.length})</summary>
        <ul>
          {d.schemas.map((s) => (
            <li key={s.schema}>
              <code>{s.schema}</code> — {s.description} {d.by_schema[s.schema] ? <span className="muted">· {d.by_schema[s.schema]} objeto(s)</span> : null}
            </li>
          ))}
          <li>
            <code>dbo</code> — solo tablas internas del framework de Django (auth_*, django_*) y diagramas de SSMS.
          </li>
        </ul>
      </details>
      <div className="erd__toolbar">
        <label className="field">
          <span className="field__label">Tipo</span>
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">Todos</option>
            {d.types.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label} ({d.counts[t.value] ?? 0})
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Esquema</span>
          <select value={schema} onChange={(e) => setSchema(e.target.value)}>
            <option value="">Todos</option>
            {Object.entries(d.by_schema).map(([k, n]) => (
              <option key={k} value={k}>
                {k} ({n})
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Estado</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Todos</option>
            <option value="OK">Activos</option>
            <option value="DISABLED">Deshabilitados</option>
            <option value="BROKEN">Referencias sin resolver</option>
          </select>
        </label>
        <label className="field">
          <span className="field__label">Buscar</span>
          <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="vw_Pay, TR_pa_, propósito…" />
        </label>
      </div>
      <div className="table-wrap">
        <table className="table table--compact sqlobj__table">
          <thead>
            <tr>
              <th scope="col">Estado</th>
              <th scope="col">Objeto</th>
              <th scope="col">Tipo</th>
              <th scope="col">Propósito</th>
              <th scope="col" className="num" title="Ejecuciones desde el último reinicio de SQL Server">
                Uso
              </th>
              <th scope="col">Modificado</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((o) => (
              <tr key={o.name}>
                <td>
                  <span className={`badge badge--${STATUS_TONE[o.status]}`}>{o.status_label}</span>
                </td>
                <td>
                  <code>{o.name}</code>
                  <div className="muted small">
                    <span className="data-legend" style={{ margin: 0 }}>
                      <i style={{ background: colors[o.module] }} />
                    </span>
                    {o.module}
                    {o.parent ? ` · tabla ${o.parent}` : ""}
                  </div>
                </td>
                <td className="small">
                  {o.type_label}
                  {o.type === "TRIGGER" && o.events && (
                    <div className="muted">
                      {o.timing} {o.events}
                    </div>
                  )}
                </td>
                <td className="small sqlobj__purpose">{o.purpose || <span className="muted">Sin descripción</span>}</td>
                <td className="num small">
                  {o.executions ?? "—"}
                  {o.last_execution && <div className="muted">{formatDateTime(o.last_execution)}</div>}
                </td>
                <td className="small pay-nowrap">{formatDateTime(o.modified)}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} className="empty">
                  Ningún objeto coincide con el filtro.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {!d.usage_available && (
        <p className="muted small">El uso (ejecuciones) requiere el permiso VIEW SERVER STATE en SQL Server; sin él se muestra «—».</p>
      )}
    </div>
  );
}
