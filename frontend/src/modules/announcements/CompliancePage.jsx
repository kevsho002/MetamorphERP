import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { formatDate, formatDateTime } from "../hcm/lib/format.js";
import { newsApi } from "./api.js";

const STATUS_TONE = { ACKNOWLEDGED: "ok", LATE: "warn", PENDING: "info", OVERDUE: "error" };
const ROLE_LABELS = { ADMIN: "Administrador", HR: "RRHH", WFM: "WFM", EMPLOYEE: "Empleado" };

function Bar({ pct }) {
  const n = Number(pct);
  return (
    <span className={`news-compliance__bar news-compliance__bar--inline${n >= 100 ? " is-full" : n < 50 ? " is-low" : ""}`} aria-hidden="true">
      <span style={{ width: `${n}%` }} />
    </span>
  );
}

/** Fase 25 — Reportes de cumplimiento del acuse de recibo: resumen de todos los comunicados o detalle por usuario. */
export default function CompliancePage() {
  const { id } = useParams();
  return id ? <ComplianceDetail id={id} /> : <ComplianceSummary />;
}

function ComplianceSummary() {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  useEffect(() => {
    const controller = new AbortController();
    newsApi
      .complianceSummary({ signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, []);
  const rows = state.data?.results ?? [];
  const audience = rows.reduce((s, r) => s + r.audience, 0);
  const acked = rows.reduce((s, r) => s + r.acknowledged, 0);
  return (
    <section className="card card--wide">
      <p className="small">
        <Link to="/announcements">← Periódico virtual</Link>
      </p>
      <h1 className="page-title">Cumplimiento de acuses de recibo</h1>
      <p className="muted page-subtitle">
        Comunicados con acuse obligatorio (seguridad, cambios organizacionales y los que se marcaron así). Se guarda una foto automática diaria y otra al
        vencer cada plazo.
      </p>
      {state.error && <p className="error-box">{state.error}</p>}
      {state.loading && <p className="muted">Cargando…</p>}
      {state.data && (
        <>
          <dl className="kpis">
            <div className="kpi">
              <dt>Comunicados con acuse</dt>
              <dd>{rows.length}</dd>
            </div>
            <div className="kpi kpi--ok">
              <dt>Cumplimiento global</dt>
              <dd>{audience ? ((acked * 100) / audience).toFixed(1) : "100.0"} %</dd>
            </div>
            <div className="kpi kpi--warn">
              <dt>Acuses pendientes</dt>
              <dd>{rows.reduce((s, r) => s + r.pending, 0)}</dd>
            </div>
            <div className="kpi">
              <dt>Vencidos</dt>
              <dd>{rows.reduce((s, r) => s + r.overdue, 0)}</dd>
            </div>
          </dl>
          <div className="table-wrap">
            <table className="table table--compact">
              <thead>
                <tr>
                  <th scope="col">Comunicado</th>
                  <th scope="col">Publicado</th>
                  <th scope="col">Plazo</th>
                  <th scope="col" className="num">Audiencia</th>
                  <th scope="col" className="num">Confirmados</th>
                  <th scope="col" className="num">Pendientes</th>
                  <th scope="col">Cumplimiento</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <Link to={`/announcements/${r.id}/compliance`}>{r.title}</Link>
                      <div className="muted small">
                        {r.category_label} · {r.status_label}
                      </div>
                    </td>
                    <td className="small pay-nowrap">{formatDate(r.published_at)}</td>
                    <td className="small pay-nowrap">
                      {r.due_date ? formatDate(r.due_date) : "—"}
                      {r.is_overdue && r.pending > 0 && <span className="badge badge--error news-badge-gap">Vencido</span>}
                    </td>
                    <td className="num">{r.audience}</td>
                    <td className="num">{r.acknowledged}</td>
                    <td className="num">{r.pending}</td>
                    <td className="pay-nowrap">
                      <Bar pct={r.compliance_pct} /> {r.compliance_pct} %
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={7} className="empty">
                      Aún no hay comunicados publicados con acuse de recibo.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

function ComplianceDetail({ id }) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [filter, setFilter] = useState("");
  const [search, setSearch] = useState("");
  const [reload, setReload] = useState(0);
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    newsApi
      .compliance(id, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [id, reload]);

  const d = state.data;
  const rows = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (d?.rows ?? []).filter((r) => (!filter || r.status === filter || (filter === "DONE" && r.acknowledged_at) || (filter === "OPEN" && !r.acknowledged_at))
      && (!term || `${r.username} ${r.name} ${r.employee_code ?? ""} ${r.cost_center ?? ""}`.toLowerCase().includes(term)));
  }, [d, filter, search]);

  const snapshot = async () => {
    try {
      const body = await newsApi.snapshot(id);
      setNotice({ ok: true, text: body.feedback });
      setReload((k) => k + 1);
    } catch (err) {
      setNotice({ ok: false, text: err.message });
    }
  };

  return (
    <section className="card card--wide">
      <p className="small">
        <Link to="/announcements/compliance">← Cumplimiento de acuses</Link>
      </p>
      {state.error && <p className="error-box">{state.error}</p>}
      {state.loading && <p className="muted">Cargando…</p>}
      {d && (
        <>
          <div className="card__header">
            <div>
              <h1 className="page-title">{d.announcement.title}</h1>
              <p className="muted page-subtitle">
                {d.announcement.category_label} · publicado {formatDateTime(d.announcement.published_at)} · plazo {d.due_date ? formatDate(d.due_date) : "—"}{" "}
                · <Link to={`/announcements/${id}`}>ver comunicado</Link>
              </p>
            </div>
            <div className="pay-actions">
              <button type="button" className="button button--ghost button--sm" onClick={snapshot}>
                Guardar foto del cumplimiento
              </button>
              <a className="button button--sm" href={newsApi.complianceCsvUrl(id)} download>
                Descargar CSV
              </a>
            </div>
          </div>
          {notice && (
            <div className={`alert ${notice.ok ? "alert--ok" : "alert--error"}`} role="status">
              <p className="alert__text">{notice.text}</p>
            </div>
          )}
          <dl className="kpis">
            <div className="kpi kpi--ok">
              <dt>Cumplimiento</dt>
              <dd>{d.compliance_pct} %</dd>
            </div>
            <div className="kpi">
              <dt>Audiencia</dt>
              <dd>{d.audience}</dd>
            </div>
            <div className="kpi">
              <dt>Confirmados</dt>
              <dd>
                {d.acknowledged}
                {d.late ? <span className="kpi__hint muted small">{d.late} fuera de plazo</span> : null}
              </dd>
            </div>
            <div className="kpi kpi--warn">
              <dt>{d.is_overdue ? "Vencidos" : "Pendientes"}</dt>
              <dd>{d.pending}</dd>
            </div>
          </dl>
          <div className="news__filters">
            <input type="search" className="news__search" aria-label="Buscar usuario" placeholder="Usuario, nombre, ID o centro de costos" value={search}
              onChange={(e) => setSearch(e.target.value)} />
            <select aria-label="Estado" value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="">Todos los estados</option>
              <option value="DONE">Confirmados</option>
              <option value="OPEN">Sin confirmar</option>
              {Object.entries(d.status_labels).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </div>
          <div className="table-wrap">
            <table className="table table--compact">
              <thead>
                <tr>
                  <th scope="col">Usuario</th>
                  <th scope="col">Rol</th>
                  <th scope="col">Centro de costos</th>
                  <th scope="col">Estado</th>
                  <th scope="col">Confirmado</th>
                  <th scope="col">IP</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.user_id}>
                    <td>
                      <strong>{r.username}</strong>
                      <div className="muted small">
                        {r.name || "—"}
                        {r.employee_code ? ` · ${r.employee_code}` : ""}
                      </div>
                    </td>
                    <td className="small">{ROLE_LABELS[r.role] ?? r.role}</td>
                    <td className="small">{r.cost_center || "—"}</td>
                    <td>
                      <span className={`badge badge--${STATUS_TONE[r.status]}`}>{d.status_labels[r.status]}</span>
                      {r.hash_ok === false && <div className="small field__error">Confirmó otra versión del contenido</div>}
                    </td>
                    <td className="small pay-nowrap">{r.acknowledged_at ? formatDateTime(r.acknowledged_at) : "—"}</td>
                    <td className="small">{r.ip || "—"}</td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={6} className="empty">
                      Nadie coincide con el filtro.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <h2 className="section-title">Historial de reportes ({d.snapshots.length})</h2>
          {d.snapshots.length === 0 ? (
            <p className="empty">Aún no hay fotos: se guardan a diario, al vencer el plazo, al archivar o manualmente.</p>
          ) : (
            <div className="table-wrap">
              <table className="table table--compact">
                <thead>
                  <tr>
                    <th scope="col">Fecha</th>
                    <th scope="col">Origen</th>
                    <th scope="col" className="num">Audiencia</th>
                    <th scope="col" className="num">Confirmados</th>
                    <th scope="col" className="num">Pendientes</th>
                    <th scope="col">Cumplimiento</th>
                  </tr>
                </thead>
                <tbody>
                  {d.snapshots.map((s, i) => (
                    <tr key={i}>
                      <td className="small pay-nowrap">{formatDateTime(s.taken_at)}</td>
                      <td className="small">{s.trigger_label}</td>
                      <td className="num">{s.audience}</td>
                      <td className="num">{s.acknowledged}</td>
                      <td className="num">{s.pending}</td>
                      <td className="pay-nowrap">
                        <Bar pct={s.compliance_pct} /> {s.compliance_pct} %
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </section>
  );
}
