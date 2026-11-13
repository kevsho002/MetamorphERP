import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { formatDateTime } from "../../hcm/lib/format.js";
import { api } from "../../../services/apiClient.js";
import ErdDiagram from "../components/ErdDiagram.jsx";

const kb = (n) => (n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(2)} GB` : n >= 1024 ? `${(n / 1024).toFixed(1)} MB` : `${n} KB`);
const int = (n) => Number(n ?? 0).toLocaleString("es-SV");
const SYSTEM_MODULES = new Set(["Sistema", "Usuarios y seguridad"]);
const SORTS = {
  rows: (a, b) => b.rows - a.rows,
  size: (a, b) => b.reserved_kb - a.reserved_kb,
  name: (a, b) => a.name.localeCompare(b.name),
  module: (a, b) => a.module.localeCompare(b.module) || a.name.localeCompare(b.name),
};

/**
 * Fase 22 — Sistema › Datos y modelo ER (Administrador): uso de datos por tabla (filas, espacio de datos e índices,
 * columnas, relaciones y triggers; procedimiento dbo.usp_SystemTableStats) y el modelo entidad-relación interactivo.
 */
export default function DataModelPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "erd" ? "erd" : "stats";
  const [stats, setStats] = useState({ loading: true, data: null, error: null });
  const [erd, setErd] = useState({ loading: false, data: null, error: null });
  const [sort, setSort] = useState("rows");
  const [module, setModule] = useState("");
  const [search, setSearch] = useState("");
  const [hideEmpty, setHideEmpty] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [hideSystem, setHideSystem] = useState(true);
  const [focus, setFocus] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    api.get("/system/data/stats/", { signal: controller.signal })
      .then((data) => setStats({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setStats({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (tab !== "erd" || erd.data || erd.loading) return undefined;
    const controller = new AbortController();
    setErd({ loading: true, data: null, error: null });
    api.get("/system/data/erd/", { signal: controller.signal })
      .then((data) => setErd({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setErd({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const data = stats.data;
  const colors = useMemo(() => Object.fromEntries((erd.data?.modules ?? data?.modules ?? []).map((m) => [m.module, m.color])), [erd.data, data]);
  const maxRows = Math.max(1, ...(data?.tables ?? []).map((t) => t.rows));
  const rows = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (data?.tables ?? [])
      .filter((t) => (!module || t.module === module) && (!hideEmpty || t.rows > 0) && (!term || `${t.name} ${t.label}`.toLowerCase().includes(term)))
      .sort(SORTS[sort]);
  }, [data, module, hideEmpty, search, sort]);

  const erdTables = useMemo(
    () => (erd.data?.tables ?? []).filter((t) => (!module || t.module === module) && !(hideSystem && SYSTEM_MODULES.has(t.module))),
    [erd.data, module, hideSystem],
  );
  const focused = focus ? erd.data?.tables.find((t) => t.name === focus) : null;
  const focusedRels = focused ? erd.data.relations.filter((r) => r.from === focus || r.to === focus) : [];

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Datos y modelo entidad-relación</h1>
          <p className="muted page-subtitle">
            Estado y uso de los datos generados por cada tabla del sistema y el modelo entidad-relación de SQL Server (tablas de Django y SQL-first).
          </p>
        </div>
        <div className="pay-actions" role="tablist">
          <button type="button" role="tab" aria-selected={tab === "stats"} className={`button button--sm${tab === "stats" ? "" : " button--ghost"}`}
            onClick={() => setParams({}, { replace: true })}>
            Uso de datos
          </button>
          <button type="button" role="tab" aria-selected={tab === "erd"} className={`button button--sm${tab === "erd" ? "" : " button--ghost"}`}
            onClick={() => setParams({ tab: "erd" }, { replace: true })}>
            Modelo ER
          </button>
        </div>
      </header>
      {stats.error && <p className="error-box">{stats.error}</p>}
      {data && (
        <>
          <dl className="kpis data-kpis">
            <div className="kpi">
              <dt>Base de datos</dt>
              <dd>{data.totals.database}</dd>
            </div>
            <div className="kpi">
              <dt>Tablas</dt>
              <dd>{int(data.totals.tables)}</dd>
            </div>
            <div className="kpi">
              <dt>Filas totales</dt>
              <dd>{int(data.totals.rows)}</dd>
            </div>
            <div className="kpi">
              <dt>Espacio de tablas</dt>
              <dd>{kb(data.totals.reserved_kb)}</dd>
            </div>
            <div className="kpi">
              <dt>Archivos de la BD</dt>
              <dd>{kb(data.totals.database_kb)}</dd>
            </div>
            <div className="kpi kpi--warn">
              <dt>Tablas vacías</dt>
              <dd>{int(data.totals.empty_tables)}</dd>
            </div>
            <div className="kpi">
              <dt>Vistas · SP · triggers</dt>
              <dd>
                {data.totals.views} · {data.totals.procedures} · {data.totals.triggers}
              </dd>
            </div>
          </dl>
          <div className="data-bar" aria-label="Espacio por módulo">
            {data.modules.map((m) => (
              <span key={m.module} title={`${m.module}: ${kb(m.reserved_kb)}`} style={{ width: `${(m.reserved_kb / Math.max(1, data.totals.reserved_kb)) * 100}%`, background: m.color }} />
            ))}
          </div>
          <p className="data-legend">
            {data.modules.map((m) => (
              <button key={m.module} type="button" className="link-button" onClick={() => setModule(module === m.module ? "" : m.module)}
                style={{ fontWeight: module === m.module ? 700 : 400 }}>
                <i style={{ background: m.color }} />
                {m.module} · {m.tables} tablas · {int(m.rows)} filas
              </button>
            ))}
          </p>
          <div className="erd__toolbar">
            <label className="field">
              <span className="field__label">Módulo</span>
              <select value={module} onChange={(e) => setModule(e.target.value)}>
                <option value="">Todos</option>
                {data.modules.map((m) => (
                  <option key={m.module} value={m.module}>
                    {m.module}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field__label">Buscar tabla o columna</span>
              <input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="pay_, Employee…" />
            </label>
            {tab === "stats" ? (
              <>
                <label className="field">
                  <span className="field__label">Ordenar por</span>
                  <select value={sort} onChange={(e) => setSort(e.target.value)}>
                    <option value="rows">Filas</option>
                    <option value="size">Espacio</option>
                    <option value="module">Módulo</option>
                    <option value="name">Nombre</option>
                  </select>
                </label>
                <label className="checkbox">
                  <input type="checkbox" checked={hideEmpty} onChange={(e) => setHideEmpty(e.target.checked)} /> Ocultar tablas vacías
                </label>
              </>
            ) : (
              <>
                <label className="checkbox">
                  <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> Todas las columnas
                </label>
                <label className="checkbox">
                  <input type="checkbox" checked={hideSystem} onChange={(e) => setHideSystem(e.target.checked)} /> Ocultar tablas técnicas (Django, seguridad)
                </label>
              </>
            )}
          </div>
        </>
      )}

      {tab === "stats" && data && (
        <div className="table-wrap">
          <table className="table table--compact">
            <thead>
              <tr>
                <th scope="col">Tabla</th>
                <th scope="col">Módulo</th>
                <th scope="col" className="num">
                  Filas
                </th>
                <th scope="col" className="num">
                  Datos
                </th>
                <th scope="col" className="num">
                  Índices
                </th>
                <th scope="col" className="num">
                  Reservado
                </th>
                <th scope="col" className="num">
                  Columnas
                </th>
                <th scope="col" className="num" title="Llaves foráneas salientes / entrantes">
                  FK ↗ / ↙
                </th>
                <th scope="col" className="num">
                  Triggers
                </th>
                <th scope="col">Modificada</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.name} className={t.rows === 0 ? "is-muted" : ""}>
                  <td>
                    <code>{t.name}</code>
                    <div className="muted small">
                      {t.label || t.source}
                      {t.app ? ` · app ${t.app}` : ""}
                    </div>
                  </td>
                  <td className="small">
                    <span className="data-legend" style={{ margin: 0 }}>
                      <i style={{ background: colors[t.module] }} />
                    </span>
                    {t.module}
                  </td>
                  <td className="num pay-nowrap">
                    <span className="data-usage" aria-hidden="true">
                      <span style={{ width: `${Math.max(t.rows ? 3 : 0, (Math.log10(t.rows + 1) / Math.log10(maxRows + 1)) * 100)}%` }} />
                    </span>
                    {int(t.rows)}
                  </td>
                  <td className="num">{kb(t.data_kb)}</td>
                  <td className="num">{kb(t.index_kb)}</td>
                  <td className="num">{kb(t.reserved_kb)}</td>
                  <td className="num">{t.columns}</td>
                  <td className="num">
                    {t.fk_out} / {t.fk_in}
                  </td>
                  <td className="num">{t.triggers || "—"}</td>
                  <td className="small pay-nowrap">{formatDateTime(t.modified)}</td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={10} className="empty">
                    Ninguna tabla coincide con el filtro.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {tab === "erd" && (
        <>
          {erd.loading && <p className="muted">Cargando el modelo…</p>}
          {erd.error && <p className="error-box">{erd.error}</p>}
          {erd.data && (
            <>
              <p className="muted small">
                {erdTables.length} tablas · arrastre el fondo para desplazarse, la rueda para acercar, arrastre una tabla para moverla y haga clic en ella
                para resaltar sus relaciones. PK = llave primaria · FK = llave foránea · * = obligatorio.
              </p>
              <ErdDiagram tables={erdTables} relations={erd.data.relations} colors={colors} focus={focus} onFocus={setFocus} showAll={showAll} search={search} />
              {focused && (
                <div className="erd-detail">
                  <h2 className="section-title">
                    <code>{focused.name}</code> · {focused.module} · {int(focused.rows)} filas
                  </h2>
                  <div className="table-wrap">
                    <table className="table table--compact">
                      <thead>
                        <tr>
                          <th scope="col">Columna</th>
                          <th scope="col">Tipo</th>
                          <th scope="col">Llave</th>
                          <th scope="col">Nulos</th>
                        </tr>
                      </thead>
                      <tbody>
                        {focused.columns.map((c) => (
                          <tr key={c.name}>
                            <td>
                              <code>{c.name}</code>
                            </td>
                            <td className="small">
                              {c.type}
                              {c.computed ? " (calculada)" : ""}
                            </td>
                            <td className="small">{[c.pk && "PK", c.fk && "FK"].filter(Boolean).join(" · ") || "—"}</td>
                            <td className="small">{c.nullable ? "Sí" : "No"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <h3 className="section-title">Relaciones ({focusedRels.length})</h3>
                  <ul className="small">
                    {focusedRels.map((r) => (
                      <li key={r.name}>
                        <button type="button" className="link-button" onClick={() => setFocus(r.from === focus ? r.to : r.from)}>
                          {r.from}
                        </button>
                        .{r.columns.map((c) => c[0]).join(", ")} → {r.to}.{r.columns.map((c) => c[1]).join(", ")}{" "}
                        <span className="muted">
                          ({r.name}
                          {r.on_delete !== "NO_ACTION" ? ` · ON DELETE ${r.on_delete}` : ""})
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
