import { useState } from "react";
import { employeesApi } from "../api.js";
import { formatDate, formatDateTime } from "../lib/format.js";

const STATUS_TONE = { OK: "ok", EXPIRING: "warn", EXPIRED: "error", MISSING: "error", NOT_PROVIDED: "muted" };

function sizeLabel(bytes) {
  if (!bytes) return "";
  return bytes > 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`;
}

/** Barra de avance de documentos obligatorios. */
export function Completeness({ ok, total, percent, compact = false }) {
  const tone = percent >= 100 ? "ok" : percent >= 50 ? "warn" : "error";
  return (
    <div className={`progress${compact ? " progress--compact" : ""}`} title={`${ok} de ${total} documentos obligatorios vigentes`}>
      <div className="progress__track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
        <span className={`progress__bar progress__bar--${tone}`} style={{ width: `${percent}%` }} />
      </div>
      <span className="progress__label">
        {total ? `${ok}/${total} obligatorios` : "Sin obligatorios"}
      </span>
    </div>
  );
}

/**
 * Checklist de documentos del expediente según la plantilla del país:
 * estado, vista previa, versiones y carga de nuevas versiones.
 */
export default function DocumentsPanel({ code, documents, canUpload, onUpload, onView }) {
  const [history, setHistory] = useState({}); // código -> {loading, items, error}
  const [revealed, setRevealed] = useState(() => new Set()); // documentos sensibles mostrados a pedido

  const toggleHistory = async (type) => {
    if (history[type]) {
      setHistory(({ [type]: _omit, ...rest }) => rest);
      return;
    }
    setHistory((h) => ({ ...h, [type]: { loading: true, items: [] } }));
    try {
      const data = await employeesApi.documents(code, type);
      setHistory((h) => ({ ...h, [type]: { loading: false, items: data.results } }));
    } catch (err) {
      setHistory((h) => ({ ...h, [type]: { loading: false, items: [], error: err.message } }));
    }
  };

  const items = documents.items;
  return (
    <section aria-labelledby="docs-title">
      <header className="docs-header">
        <h2 id="docs-title" className="section-title">
          Documentos del expediente
        </h2>
        <Completeness ok={documents.required_ok} total={documents.required_total} percent={documents.percent} />
        {canUpload && (
          <button type="button" className="button button--sm" onClick={() => onUpload(null)}>
            Agregar documento
          </button>
        )}
      </header>
      <p className="muted small">
        Los documentos exigidos dependen de la plantilla del país vigente. Solo se aceptan imágenes PNG, JPG o JPEG; cada
        carga crea una versión nueva y conserva las anteriores.
      </p>

      <ul className="doc-grid">
        {items.map((doc) => {
          const current = doc.current;
          const sensitiveHidden = doc.is_sensitive && !revealed.has(doc.code);
          const versionInfo = history[doc.code];
          return (
            <li key={doc.code} className={`doc-card doc-card--${doc.status.toLowerCase()}`}>
              <div className="doc-card__thumb">
                {current && doc.viewable && !sensitiveHidden ? (
                  <button type="button" className="doc-card__preview" onClick={() => onView(doc.code)} title="Abrir en el visor">
                    <img src={current.content_url} alt={`Vista previa: ${doc.label}`} loading="lazy" />
                  </button>
                ) : current && doc.viewable ? (
                  <button
                    type="button"
                    className="doc-card__placeholder"
                    onClick={() => setRevealed((r) => new Set(r).add(doc.code))}
                    title="Documento sensible: la consulta queda registrada en la auditoría"
                  >
                    <span aria-hidden="true">🔒</span>
                    Mostrar
                  </button>
                ) : current ? (
                  <span className="doc-card__placeholder doc-card__placeholder--locked">
                    <span aria-hidden="true">🔒</span>
                    Restringido
                  </span>
                ) : (
                  <span className="doc-card__placeholder">
                    <span aria-hidden="true">📄</span>
                    Sin archivo
                  </span>
                )}
              </div>
              <div className="doc-card__body">
                <p className="doc-card__title">
                  {doc.label}
                  {doc.required && <span className="tag">Obligatorio</span>}
                  {doc.is_sensitive && <span className="tag tag--warn">Sensible</span>}
                </p>
                <span className={`badge badge--${STATUS_TONE[doc.status] ?? "info"}`}>{doc.status_label}</span>
                {current && (
                  <dl className="doc-card__meta">
                    <div>
                      <dt>Versión</dt>
                      <dd>
                        {current.version} de {doc.versions}
                      </dd>
                    </div>
                    {current.expiry_date && (
                      <div>
                        <dt>Vence</dt>
                        <dd>{formatDate(current.expiry_date)}</dd>
                      </div>
                    )}
                    {current.issue_date && (
                      <div>
                        <dt>Emitido</dt>
                        <dd>{formatDate(current.issue_date)}</dd>
                      </div>
                    )}
                    <div>
                      <dt>Cargado</dt>
                      <dd>
                        {formatDateTime(current.uploaded_at)} · {current.uploaded_by || "—"}
                      </dd>
                    </div>
                    {doc.viewable && current.width && (
                      <div>
                        <dt>Imagen</dt>
                        <dd>
                          {current.width}×{current.height} px · {sizeLabel(current.size_bytes)}
                        </dd>
                      </div>
                    )}
                  </dl>
                )}
                {doc.help && <p className="muted small">{doc.help}</p>}
                <div className="doc-card__actions">
                  {canUpload && doc.viewable && (
                    <button type="button" className="button button--ghost button--sm" onClick={() => onUpload(doc.code)}>
                      {current ? "Nueva versión" : "Subir"}
                    </button>
                  )}
                  {doc.versions > 1 && (
                    <button type="button" className="link-button" aria-expanded={Boolean(versionInfo)} onClick={() => toggleHistory(doc.code)}>
                      {versionInfo ? "Ocultar historial" : `Historial (${doc.versions})`}
                    </button>
                  )}
                </div>
                {versionInfo && (
                  <div className="doc-history">
                    {versionInfo.loading && <p className="muted small">Cargando versiones…</p>}
                    {versionInfo.error && <p className="field__error">{versionInfo.error}</p>}
                    <ol>
                      {versionInfo.items.map((v) => (
                        <li key={v.id}>
                          <span>
                            v{v.version} · {formatDateTime(v.uploaded_at)} · {v.uploaded_by || "—"}
                            {v.is_current && <span className="tag">Vigente</span>}
                          </span>
                          {v.viewable && (
                            <span className="doc-history__links">
                              <button type="button" className="link-button" onClick={() => onView(doc.code, v)}>
                                Ver
                              </button>
                              <a href={employeesApi.contentUrl(v.content_url, { download: true })} download>
                                Descargar
                              </a>
                            </span>
                          )}
                        </li>
                      ))}
                    </ol>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {items.length === 0 && <p className="muted">No hay tipos de documento configurados para este país.</p>}
    </section>
  );
}
