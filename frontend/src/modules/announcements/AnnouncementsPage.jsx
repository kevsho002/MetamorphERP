import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext.jsx";
import { useClientConfig } from "../../app/ClientConfigContext.jsx";
import { ThemedLogo } from "../../components/ui/Brand.jsx";
import { formatDate } from "../hcm/lib/format.js";
import { CATEGORY_TONE, newsApi } from "./api.js";

const SCOPES = [
  { value: "published", label: "Publicados" },
  { value: "draft", label: "Borradores" },
  { value: "archived", label: "Archivados" },
];

/**
 * Fase 25 — Periódico virtual (pantalla de bienvenida: logotipo de la barra e inicio).
 *
 * Comunicados reales por categoría (noticias, blog, formularios, RRHH, planillas, cultura, operaciones, seguridad y
 * cambios organizacionales), con fijados, búsqueda y la audiencia de cada uno. Los comunicados críticos exigen ACUSE DE
 * RECIBO: aparecen primero mientras estén pendientes. Quien tiene announcements.manage publica y gestiona; quien tiene
 * announcements.compliance consulta los reportes de cumplimiento.
 */
export default function AnnouncementsPage() {
  const { user } = useAuth();
  const { config } = useClientConfig();
  const [params, setParams] = useSearchParams();
  const category = params.get("category") ?? "";
  const scope = params.get("scope") ?? "published";
  const pendingOnly = params.get("pending") === "1";
  const [q, setQ] = useState(params.get("q") ?? "");
  const [term, setTerm] = useState(q);
  const [state, setState] = useState({ loading: true, data: null, error: null });

  useEffect(() => {
    const t = setTimeout(() => setTerm(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true }));
    newsApi
      .list({ category, scope, q: term, pending: pendingOnly ? 1 : "" }, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [category, scope, term, pendingOnly]);

  const set = (patch) => {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    setParams(next, { replace: true });
  };

  const live = config.announcement?.trim();
  const tone = { info: "info", warning: "warn", danger: "error" }[config.announcement_level] ?? "info";
  const data = state.data;
  const rows = data?.results ?? [];
  const ordered = [...rows].sort((a, b) => Number(b.ack_pending) - Number(a.ack_pending));
  const name = user?.first_name || user?.display_name || user?.username;

  return (
    <section className="card card--wide news">
      <header className="news__hero">
        <span className="news__logo">
          <ThemedLogo />
        </span>
        <div className="news__hero-text">
          <h1 className="page-title">Periódico virtual</h1>
          <p className="muted page-subtitle">{name ? `Hola, ${name}. ` : ""}Comunicados oficiales, políticas y novedades de la organización.</p>
        </div>
        <div className="news__hero-actions">
          {data?.can_report && (
            <Link className="button button--ghost button--sm" to="/announcements/compliance">
              Cumplimiento de acuses
            </Link>
          )}
          {data?.can_manage && (
            <Link className="button button--sm" to="/announcements/new">
              Publicar comunicado
            </Link>
          )}
        </div>
      </header>

      {live && (
        <article className={`news__live announcement announcement--${tone}`}>
          <strong>Aviso vigente</strong>
          <span>{live}</span>
        </article>
      )}

      {data?.pending_count > 0 && !pendingOnly && (
        <div className="alert alert--warn news__pending" role="status">
          <p className="alert__text">
            Tiene <strong>{data.pending_count}</strong> comunicado(s) que requieren su acuse de recibo.{" "}
            <button type="button" className="link-button" onClick={() => set({ pending: "1", scope: "" })}>
              Ver pendientes
            </button>
          </p>
        </div>
      )}

      <div className="news__filters">
        <input type="search" className="news__search" placeholder="Buscar comunicado…" value={q} onChange={(e) => setQ(e.target.value)}
          aria-label="Buscar comunicado" />
        <label className="news__select">
          <span className="sr-only">Categoría</span>
          <select value={category} onChange={(e) => set({ category: e.target.value })} aria-label="Categoría">
            <option value="">Todas las categorías</option>
            {(data?.categories ?? []).map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
                {c.critical ? " (acuse obligatorio)" : ""}
              </option>
            ))}
          </select>
        </label>
        {data?.can_manage && (
          <div className="news__chips" role="group" aria-label="Estado">
            {SCOPES.map((s) => (
              <button key={s.value} type="button" className={`button button--sm${scope === s.value && !pendingOnly ? "" : " button--ghost"}`}
                onClick={() => set({ scope: s.value === "published" ? "" : s.value, pending: "" })}>
                {s.label}
              </button>
            ))}
          </div>
        )}
        {pendingOnly && (
          <button type="button" className="button button--ghost button--sm" onClick={() => set({ pending: "" })}>
            Ver todos
          </button>
        )}
      </div>

      {state.error && <p className="error-box">{state.error}</p>}
      {state.loading && !data && <p className="muted">Cargando comunicados…</p>}
      {data && ordered.length === 0 && (
        <p className="empty">{pendingOnly ? "No tiene acuses de recibo pendientes. ¡Al día!" : "No hay comunicados con ese filtro."}</p>
      )}
      <div className="news__grid">
        {ordered.map((a) => (
          <article key={a.id} className={`news__card${a.pinned ? " news__card--pinned" : ""}${a.ack_pending ? " news__card--ack" : ""}`}>
            <div className="news__meta">
              <span className={`badge badge--${CATEGORY_TONE[a.category] ?? "info"}`}>{a.category_label}</span>
              {a.pinned && <span className="badge badge--warn">Destacado</span>}
              {a.status !== "PUBLISHED" && <span className="badge badge--muted">{a.status_label}</span>}
              {a.requires_ack && (a.my_ack ? (
                <span className="badge badge--ok">Acuse confirmado</span>
              ) : a.ack_pending ? (
                <span className={`badge ${a.ack_overdue ? "badge--error" : "badge--warn"}`}>
                  {a.ack_overdue ? "Acuse vencido" : "Acuse pendiente"}
                  {a.ack_due_date ? ` · ${formatDate(a.ack_due_date)}` : ""}
                </span>
              ) : (
                <span className="badge badge--info">Acuse obligatorio</span>
              ))}
              <span className="muted small">{a.published_at ? formatDate(a.published_at) : "Sin publicar"}</span>
            </div>
            <h2 className="news__title">
              <Link to={`/announcements/${a.id}`}>{a.title}</Link>
            </h2>
            <p className="news__body">{a.excerpt}</p>
            <footer className="news__footer">
              <span className="muted small">{a.author}</span>
              <span className="news__footer-links">
                {a.link_url && (
                  <a href={a.link_url} target="_blank" rel="noopener noreferrer" className="small">
                    {a.link_label || "Abrir enlace"} ↗
                  </a>
                )}
                <Link to={`/announcements/${a.id}`} className="small">
                  {a.ack_pending ? "Leer y confirmar →" : "Leer →"}
                </Link>
              </span>
            </footer>
          </article>
        ))}
      </div>
    </section>
  );
}
