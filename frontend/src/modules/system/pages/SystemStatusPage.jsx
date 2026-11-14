import { useCallback, useEffect, useState } from "react";
import { useAuth } from "../../../auth/AuthContext.jsx";
import { api } from "../../../services/apiClient.js";
import { formatDateTime } from "../../hcm/lib/format.js";

const LABELS = { ok: "Operativa", degraded: "Esquema incompleto", error: "Sin conexión" };
const REFRESH_MS = 15000;
const ROLE_LABELS = { ADMIN: "Administrador", HR: "RRHH", WFM: "WFM", EMPLOYEE: "Empleado" };

const idle = (s) => (s < 60 ? `${s} s` : s < 3600 ? `${Math.floor(s / 60)} min` : `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`);

/**
 * Estado del sistema: API y SQL Server para todos; para el Administrador (Fase 25) el control de sesiones en tiempo
 * real (se actualiza cada 15 s) y el recuento de usuarios: activos, bloqueados, inactivos y con cambio de contraseña
 * pendiente. Los atributos de cada cuenta se gestionan en el panel de Django (Usuarios).
 */
export default function SystemStatusPage() {
  const { hasPermission } = useAuth();
  const isAdmin = hasPermission("system.status");
  const [state, setState] = useState({ loading: true, api: null, db: null, error: null });
  const [ov, setOv] = useState({ data: null, error: null, notice: null });
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(null);

  const check = useCallback(async (signal) => {
    setState((s) => ({ ...s, loading: true, error: null }));
    const [apiRes, dbRes] = await Promise.allSettled([api.get("/health", { signal }), api.get("/health/db", { signal })]);
    if (signal?.aborted) return;
    setState({
      loading: false,
      api: apiRes.status === "fulfilled" ? apiRes.value : null,
      // /health/db responde 503 con cuerpo JSON útil cuando la BD falla
      db: dbRes.status === "fulfilled" ? dbRes.value : (dbRes.reason?.body ?? null),
      error: apiRes.status === "rejected" ? apiRes.reason?.message : null,
    });
  }, []);

  const loadOverview = useCallback(
    (signal) =>
      api
        .get("/system/overview/", { signal })
        .then((data) => setOv((o) => ({ ...o, data, error: null })))
        .catch((err) => err.name !== "AbortError" && setOv((o) => ({ ...o, error: err.message }))),
    [],
  );

  useEffect(() => {
    const controller = new AbortController();
    check(controller.signal);
    return () => controller.abort();
  }, [check]);

  useEffect(() => {
    if (!isAdmin) return undefined;
    const controller = new AbortController();
    loadOverview(controller.signal);
    const timer = setInterval(() => document.visibilityState === "visible" && loadOverview(controller.signal), REFRESH_MS);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [isAdmin, loadOverview]);

  const closeSession = async (row) => {
    setBusy(row.id);
    try {
      const body = await api.post(`/system/sessions/${row.id}/close/`);
      setOv({ data: body, error: null, notice: { ok: true, text: body.feedback } });
    } catch (err) {
      setOv((o) => ({ ...o, notice: { ok: false, text: err.message } }));
    } finally {
      setBusy(null);
    }
  };

  const db = state.db;
  const data = ov.data;
  const term = search.trim().toLowerCase();
  const rows = (data?.sessions.rows ?? []).filter((r) => !term || `${r.username} ${r.name} ${r.ip ?? ""}`.toLowerCase().includes(term));

  return (
    <section className="card card--wide">
      <div className="card__header">
        <h1 className="page-title">Estado del sistema</h1>
        <button
          type="button"
          className="button"
          onClick={() => {
            check();
            if (isAdmin) loadOverview();
          }}
          disabled={state.loading}
        >
          {state.loading ? "Verificando…" : "Volver a verificar"}
        </button>
      </div>

      {state.error && <p className="badge badge--error">API inaccesible: {state.error}</p>}

      <dl className="status-grid">
        <div className="status-item">
          <dt>API (Django REST)</dt>
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
              {db ? (LABELS[db.status] ?? db.status) : state.loading ? "…" : "Desconocido"}
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
              {db.expected_tables - (db.missing_count ?? db.missing_tables?.length ?? 0)} / {db.expected_tables}
            </dd>
          </div>
        )}
      </dl>

      {db?.missing_tables?.length > 0 && (
        <p className="muted">
          Faltan: <code>{db.missing_tables.join(", ")}</code> — ejecute <code>database/deploy.ps1</code> y <code>python manage.py migrate</code>.
        </p>
      )}
      {db?.error && <pre className="error-box">{db.error}</pre>}

      {isAdmin && (
        <div className="sys-ov">
          {ov.error && <p className="error-box">{ov.error}</p>}
          {ov.notice && (
            <div className={`alert ${ov.notice.ok ? "alert--ok" : "alert--error"}`} role="status">
              <p className="alert__text">{ov.notice.text}</p>
            </div>
          )}
          {data && (
            <>
              <div className="sys-ov__head">
                <h2 className="section-title">Usuarios y sesiones</h2>
                <span className="muted small">
                  <span className="sys-live" aria-hidden="true" /> En vivo · actualizado {formatDateTime(data.generated_at)}
                </span>
              </div>
              <dl className="kpis">
                <Kpi label="Sesiones activas" value={data.sessions.active} tone="ok" hint={`${data.users.connected} usuario(s) conectados`} />
                <Kpi label="Usuarios totales" value={data.users.total} hint={`${data.users.superusers} superusuario(s)`} />
                <Kpi label="Activos" value={data.users.active} tone="ok" />
                <Kpi label="Bloqueados" value={data.users.locked} tone={data.users.locked ? "warn" : ""} />
                <Kpi label="Inactivos" value={data.users.inactive} />
                <Kpi label="Cambio de contraseña pendiente" value={data.users.must_change_password} tone={data.users.must_change_password ? "warn" : ""} />
                <Kpi label="Intentos fallidos (24 h)" value={data.sessions.failed_logins_24h} hint={`${data.sessions.locks_24h} bloqueo(s)`} />
                <Kpi label="Ingresos hoy" value={data.sessions.started_today} hint={`${data.sessions.ended_today} cierres`} />
              </dl>
              <p className="muted small sys-ov__policy">
                Política: inactividad {data.policy.idle_timeout_minutes} min · duración máx. {data.policy.max_session_hours} h · {data.policy.max_sessions_per_user || "sin límite de"} sesión(es)
                por usuario · bloqueo tras {data.policy.max_failed_logins || "—"} intentos fallidos
                {data.policy.maintenance_mode ? " · MODO MANTENIMIENTO" : ""}. Por rol activo:{" "}
                {data.users.by_role.map((r) => `${r.label} ${r.count}`).join(" · ")}.
              </p>
              <div className="sys-ov__links">
                <a className="button button--ghost button--sm" href={data.admin_urls.users}>
                  Gestionar usuarios (panel)
                </a>
                <a className="button button--ghost button--sm" href={data.admin_urls.sessions}>
                  Sesiones (panel)
                </a>
                <a className="button button--ghost button--sm" href={data.admin_urls.settings}>
                  Parámetros de sesión
                </a>
              </div>

              <div className="sys-ov__toolbar">
                <h3 className="section-title">Sesiones activas ({rows.length})</h3>
                <input type="search" aria-label="Buscar sesión" placeholder="Usuario, nombre o IP" value={search} onChange={(e) => setSearch(e.target.value)} />
              </div>
              <div className="table-wrap">
                <table className="table table--compact sys-sessions">
                  <thead>
                    <tr>
                      <th scope="col">Usuario</th>
                      <th scope="col">Rol</th>
                      <th scope="col">IP · navegador</th>
                      <th scope="col">Inicio</th>
                      <th scope="col">Última actividad</th>
                      <th scope="col">Inactivo</th>
                      <th scope="col" />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.id}>
                        <td data-label="Usuario">
                          <strong>{r.username}</strong>
                          {r.current && <span className="badge badge--info sys-you">Usted</span>}
                          <div className="muted small">{r.name || "—"}</div>
                        </td>
                        <td data-label="Rol" className="small">
                          {ROLE_LABELS[r.role] ?? r.role}
                        </td>
                        <td data-label="IP" className="small">
                          {r.ip || "—"}
                          <div className="muted">{r.agent}</div>
                        </td>
                        <td data-label="Inicio" className="small pay-nowrap">
                          {formatDateTime(r.started_at)}
                        </td>
                        <td data-label="Actividad" className="small pay-nowrap">
                          {formatDateTime(r.last_activity)}
                        </td>
                        <td data-label="Inactivo" className="small">
                          <span className={r.idle_warning ? "badge badge--warn" : ""}>{idle(r.idle_seconds)}</span>
                        </td>
                        <td className="pay-nowrap">
                          {!r.current && (
                            <button type="button" className="button button--ghost button--sm" disabled={busy === r.id} onClick={() => closeSession(r)}>
                              {busy === r.id ? "Cerrando…" : "Cerrar sesión"}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                    {rows.length === 0 && (
                      <tr>
                        <td colSpan={7} className="empty">
                          Sin sesiones activas que coincidan.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              <div className="sys-ov__cols">
                <div>
                  <h3 className="section-title">Cuentas bloqueadas ({data.locked.length})</h3>
                  {data.locked.length === 0 ? (
                    <p className="empty">Ninguna cuenta bloqueada.</p>
                  ) : (
                    <ul className="sys-list">
                      {data.locked.map((u) => (
                        <li key={u.id}>
                          <a href={`${data.admin_urls.users}${u.id}/change/`}>
                            <strong>{u.username}</strong>
                          </a>{" "}
                          <span className="muted small">
                            {u.name} · desde {formatDateTime(u.locked_at)} · {u.reason}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div>
                  <h3 className="section-title">Cambio de contraseña pendiente ({data.pending_password.length})</h3>
                  {data.pending_password.length === 0 ? (
                    <p className="empty">Nadie tiene el cambio pendiente.</p>
                  ) : (
                    <ul className="sys-list">
                      {data.pending_password.map((u) => (
                        <li key={u.id}>
                          <a href={`${data.admin_urls.users}${u.id}/change/`}>
                            <strong>{u.username}</strong>
                          </a>{" "}
                          <span className="muted small">
                            {u.name} · último ingreso {u.last_login ? formatDateTime(u.last_login) : "nunca"}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}

function Kpi({ label, value, tone = "", hint }) {
  return (
    <div className={`kpi${tone ? ` kpi--${tone}` : ""}`}>
      <dt>{label}</dt>
      <dd>
        {Number(value ?? 0).toLocaleString("es-SV")}
        {hint && <span className="kpi__hint muted small">{hint}</span>}
      </dd>
    </div>
  );
}
