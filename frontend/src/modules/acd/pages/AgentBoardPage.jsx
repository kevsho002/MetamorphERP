import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { acdApi, fmtDuration, fmtTime } from "../api.js";

const REFRESH_MS = 15_000;

/** Tablero en vivo: estado actual de cada agente, tiempo en el estado y alertas de auxiliares excedidos. */
export default function AgentBoardPage() {
  const [params, setParams] = useSearchParams();
  const filters = useMemo(
    () => ({ group: params.get("group") ?? "", status: params.get("status") ?? "", search: params.get("search") ?? "" }),
    [params],
  );
  const [catalogs, setCatalogs] = useState(null);
  const [state, setState] = useState({ loading: true, data: null, error: null, at: 0 });
  const [now, setNow] = useState(() => Date.now());
  const [reloadKey, setReloadKey] = useState(0);
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    acdApi.catalogs({ signal: controller.signal }).then(setCatalogs).catch(() => {});
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const load = () =>
      acdApi
        .agents(filters, { signal: controller.signal })
        .then((data) => setState({ loading: false, data, error: null, at: Date.now() }))
        .catch((err) => err.name !== "AbortError" && setState((s) => ({ ...s, loading: false, error: err.message })));
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [filters, reloadKey]);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const update = (changes) => {
    const next = { ...filters, ...changes };
    setParams(Object.fromEntries(Object.entries(next).filter(([, v]) => v)), { replace: true });
  };

  const forceLogout = async (row) => {
    const reason = window.prompt(`Cerrar la sesión ACD de ${row.full_name}. Motivo (opcional):`, "");
    if (reason === null) return;
    try {
      const body = await acdApi.forceLogout(row.employee_code, reason);
      setNotice({ ok: true, text: body.feedback });
      setReloadKey((k) => k + 1);
    } catch (err) {
      setNotice({ ok: false, text: err.message });
    }
  };

  const data = state.data;
  const sinceLoad = state.at ? now - state.at : 0;

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Agentes en vivo</h1>
          <p className="muted page-subtitle">Se actualiza cada {REFRESH_MS / 1000} s. El tiempo en estado lo calcula el servidor.</p>
        </div>
      </header>
      <div className="filters" role="search">
        <label className="field">
          <span className="field__label">Grupo</span>
          <select value={filters.group} onChange={(e) => update({ group: e.target.value })}>
            <option value="">Todos</option>
            {(catalogs?.groups ?? []).map((g) => (
              <option key={g.code} value={g.code}>
                {g.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Estado</span>
          <select value={filters.status} onChange={(e) => update({ status: e.target.value })}>
            <option value="">Todos</option>
            {(catalogs?.primary_statuses ?? []).map((s) => (
              <option key={s.code} value={s.code}>
                {s.label}
              </option>
            ))}
          </select>
        </label>
        <label className="field filters__search">
          <span className="field__label">Buscar</span>
          <input type="search" defaultValue={filters.search} placeholder="ID o nombre" onKeyDown={(e) => e.key === "Enter" && update({ search: e.currentTarget.value.trim() })} />
        </label>
      </div>
      {notice && (
        <div className={`alert ${notice.ok ? "alert--ok" : "alert--error"} flash`} role="status">
          <p className="alert__text">{notice.text}</p>
        </div>
      )}
      {state.error && <p className="error-box">{state.error}</p>}
      {data && (
        <>
          <dl className="kpis">
            {Object.entries(data.by_status).map(([label, n]) => (
              <div className="kpi" key={label}>
                <dt>{label}</dt>
                <dd>{n}</dd>
              </div>
            ))}
          </dl>
          {data.results.length === 0 ? (
            <p className="empty">No hay agentes asignados a grupos con estos filtros. Asígnelos en «Grupos y auxiliares».</p>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Agente</th>
                    <th scope="col">Grupo</th>
                    <th scope="col">Estado</th>
                    <th scope="col">Auxiliar</th>
                    <th scope="col">Tiempo en estado</th>
                    <th scope="col">Sesión</th>
                    <th scope="col">
                      <span className="sr-only">Acciones</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.results.map((r) => {
                    const c = r.current;
                    const ms = c ? c.duration_ms + (c.is_open ? sinceLoad : 0) : 0;
                    const over = c?.max_minutes && c.is_open && ms > c.max_minutes * 60_000;
                    return (
                      <tr key={r.employee_code} className={over ? "row--warn" : undefined}>
                        <th scope="row">
                          {r.full_name}
                          <div className="muted small">
                            <code>{r.employee_code}</code>
                          </div>
                        </th>
                        <td>
                          {r.group_name}
                          <div className="muted small">{r.division}</div>
                        </td>
                        <td>
                          <span className="acd-pill" style={{ "--status-color": c?.color ?? "#94a3b8" }}>
                            {c ? c.primary_label : "Offline"}
                          </span>
                        </td>
                        <td>{c?.secondary_status || "—"}</td>
                        <td>
                          {fmtDuration(ms)}
                          {over && <span className="badge badge--error shift-grid__badge">excede {c.max_minutes} min</span>}
                        </td>
                        <td>{r.logged_in ? `desde ${fmtTime(r.login_at)}` : "—"}</td>
                        <td>
                          {data.can_manage && r.logged_in && (
                            <button type="button" className="link-button" onClick={() => forceLogout(r)}>
                              Cerrar sesión
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
