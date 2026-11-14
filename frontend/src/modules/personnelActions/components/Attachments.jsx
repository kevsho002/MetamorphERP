import { useRef, useState } from "react";
import { formatDateTime } from "../../hcm/lib/format.js";
import { actionsApi } from "../api.js";

/**
 * Fase 24 — Adjuntos (evidencias) de las AP: imágenes, PDF y documentos de Office.
 *
 * - AttachmentQueue   en «Nueva AP»: archivos en cola que se suben al guardar (antes de enviar a aprobación).
 * - AttachmentsPanel  pestaña «Evidencias» del detalle: subir, ver / descargar y retirar (con motivo; nunca se borra).
 * El servidor valida extensión, tamaño y la firma binaria del contenido; aquí solo se filtra lo evidente.
 */
export const ACCEPT = ".png,.jpg,.jpeg,.pdf,.docx,.xlsx,.doc,.xls";
export const CATEGORIES = [
  { value: "EVIDENCE", label: "Evidencia / respaldo" },
  { value: "MEDICAL", label: "Constancia médica" },
  { value: "LETTER", label: "Carta o solicitud" },
  { value: "IDENTITY", label: "Documento de identidad" },
  { value: "OTHER", label: "Otro" },
];
const ALLOWED = new Set(ACCEPT.split(","));
const KIND_ICON = { IMAGE: "IMG", PDF: "PDF", DOCUMENT: "DOC" };

export const sizeLabel = (n) => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
const extOf = (name) => (name.match(/\.[^.]+$/)?.[0] ?? "").toLowerCase();
const kindOf = (name) => {
  const ext = extOf(name);
  return [".png", ".jpg", ".jpeg"].includes(ext) ? "IMAGE" : ext === ".pdf" ? "PDF" : "DOCUMENT";
};

function DropZone({ onFiles, disabled, maxMb }) {
  const input = useRef(null);
  const [over, setOver] = useState(false);
  const pick = (list) => onFiles([...(list ?? [])]);
  return (
    <div
      className={`attach-drop${over ? " is-over" : ""}${disabled ? " is-disabled" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        if (!disabled) pick(e.dataTransfer.files);
      }}
    >
      <input ref={input} type="file" accept={ACCEPT} multiple hidden onChange={(e) => {
        pick(e.target.files);
        e.target.value = "";
      }} />
      <span>
        Arrastre aquí sus archivos o{" "}
        <button type="button" className="link-button" disabled={disabled} onClick={() => input.current?.click()}>
          selecciónelos
        </button>
      </span>
      <small className="muted">Imágenes (PNG, JPG), PDF o documentos de Office (DOCX, XLSX, DOC, XLS){maxMb ? ` · máx. ${maxMb} MB por archivo` : ""}.</small>
    </div>
  );
}

/** Cola de adjuntos del formulario de creación (se suben después de crear la AP). */
export function AttachmentQueue({ files, onChange, disabled }) {
  const [rejected, setRejected] = useState([]);
  const add = (list) => {
    const ok = list.filter((f) => ALLOWED.has(extOf(f.name)) && f.size > 0);
    setRejected(list.filter((f) => !ok.includes(f)).map((f) => f.name));
    onChange([...files, ...ok.map((file) => ({ id: `${file.name}-${file.size}-${file.lastModified}-${Math.random()}`, file, category: "EVIDENCE", description: "" }))]);
  };
  const update = (id, patch) => onChange(files.map((f) => (f.id === id ? { ...f, ...patch } : f)));
  return (
    <div className="attach-queue">
      <DropZone onFiles={add} disabled={disabled} />
      {rejected.length > 0 && <p className="field__error">Formato no permitido: {rejected.join(", ")}.</p>}
      {files.length > 0 && (
        <ul className="attach-list">
          {files.map((f) => (
            <li key={f.id} className="attach-item">
              <span className={`attach-kind attach-kind--${kindOf(f.file.name).toLowerCase()}`}>{KIND_ICON[kindOf(f.file.name)]}</span>
              <span className="attach-item__main">
                <strong className="attach-item__name">{f.file.name}</strong>
                <span className="muted small">{sizeLabel(f.file.size)}</span>
              </span>
              <select aria-label="Categoría" value={f.category} disabled={disabled} onChange={(e) => update(f.id, { category: e.target.value })}>
                {CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
              <input aria-label="Descripción" placeholder="Descripción (opcional)" maxLength={300} value={f.description} disabled={disabled}
                onChange={(e) => update(f.id, { description: e.target.value })} />
              <button type="button" className="link-button small" disabled={disabled} onClick={() => onChange(files.filter((x) => x.id !== f.id))}>
                Quitar
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Sube la cola a una AP ya creada; devuelve los errores por archivo. */
export async function uploadQueue(folio, files) {
  const errors = [];
  for (const f of files) {
    try {
      await actionsApi.uploadAttachment(folio, f);
    } catch (err) {
      errors.push(`${f.file.name}: ${err.message}`);
    }
  }
  return errors;
}

/** Pestaña «Evidencias» del detalle de la AP. */
export function AttachmentsPanel({ action, onUpdated }) {
  const rules = action.attachment_rules ?? {};
  const [queue, setQueue] = useState([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const [removing, setRemoving] = useState(null);
  const [reason, setReason] = useState("");
  const [showRemoved, setShowRemoved] = useState(false);
  const rows = action.attachments.filter((a) => showRemoved || !a.removed);
  const removedCount = action.attachments.filter((a) => a.removed).length;

  const upload = async () => {
    setBusy(true);
    setNotice(null);
    let last = null;
    const errors = [];
    for (const f of queue) {
      try {
        last = await actionsApi.uploadAttachment(action.folio, f);
      } catch (err) {
        errors.push(`${f.file.name}: ${err.message}`);
      }
    }
    if (last) onUpdated(last.action);
    setQueue([]);
    setBusy(false);
    setNotice(errors.length ? { ok: false, text: errors.join(" · ") } : { ok: true, text: `${queue.length} archivo(s) adjuntado(s).` });
  };

  const remove = async (att) => {
    setBusy(true);
    try {
      const body = await actionsApi.removeAttachment(att.id, reason);
      onUpdated(body.action);
      setNotice({ ok: true, text: body.feedback });
      setRemoving(null);
      setReason("");
    } catch (err) {
      setNotice({ ok: false, text: err.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="attach-panel">
      {notice && (
        <div className={`alert ${notice.ok ? "alert--ok" : "alert--error"}`} role="status">
          <p className="alert__text">{notice.text}</p>
        </div>
      )}
      {action.can_attach ? (
        <div className="attach-upload">
          <AttachmentQueue files={queue} onChange={setQueue} disabled={busy} />
          {queue.length > 0 && (
            <div className="form-actions form-actions--start">
              <button type="button" className="button" disabled={busy} onClick={upload}>
                {busy ? "Adjuntando…" : `Adjuntar ${queue.length} archivo(s)`}
              </button>
            </div>
          )}
          <p className="muted small">
            Máx. {rules.max_files ?? 15} adjuntos vigentes de hasta {rules.max_mb ?? 10} MB. Se guardan en almacenamiento privado con su huella
            SHA-256; una vez resuelta o anulada la AP, sus evidencias quedan congeladas.
          </p>
        </div>
      ) : (
        <p className="muted small">
          {["DRAFT", "PENDING"].includes(action.status)
            ? "Solo quien elabora este tipo de AP o quien firma el paso en curso puede adjuntar evidencias."
            : "La AP está resuelta o anulada: sus evidencias quedan congeladas (solo lectura)."}
        </p>
      )}

      {removedCount > 0 && (
        <label className="checkbox">
          <input type="checkbox" checked={showRemoved} onChange={(e) => setShowRemoved(e.target.checked)} /> Mostrar retirados ({removedCount})
        </label>
      )}
      {rows.length === 0 ? (
        <p className="empty">Sin evidencias adjuntas.</p>
      ) : (
        <ul className="attach-grid">
          {rows.map((a) => (
            <li key={a.id} className={`attach-card${a.removed ? " is-removed" : ""}`}>
              <a className="attach-card__thumb" href={a.url} target="_blank" rel="noreferrer" title="Abrir">
                {a.kind === "IMAGE" ? (
                  <img src={a.url} alt={a.original_name} loading="lazy" />
                ) : (
                  <span className={`attach-kind attach-kind--lg attach-kind--${a.kind.toLowerCase()}`}>{KIND_ICON[a.kind]}</span>
                )}
              </a>
              <div className="attach-card__body">
                <a className="attach-item__name" href={a.url} target="_blank" rel="noreferrer">
                  {a.original_name}
                </a>
                <div className="attach-card__meta">
                  <span className="badge badge--info">{a.category_label}</span>
                  <span className="muted small">{a.size_label}</span>
                  {a.removed && <span className="badge badge--error">Retirado</span>}
                </div>
                {a.description && <p className="small">{a.description}</p>}
                <p className="muted small">
                  {a.uploaded_by} · {formatDateTime(a.uploaded_at)} · {a.status_at_upload === "PENDING" ? "en aprobación" : "en borrador"}
                </p>
                <p className="muted small">
                  <code title={a.sha256}>SHA-256 {a.sha256.slice(0, 16)}…</code>
                </p>
                {a.removed && (
                  <p className="small">
                    Retirado por {a.removed_by} · {formatDateTime(a.removed_at)}: «{a.removed_reason}»
                  </p>
                )}
                <div className="attach-card__actions">
                  <a className="link-button small" href={`${a.url}?download=1`}>
                    Descargar
                  </a>
                  {a.can_remove && removing !== a.id && (
                    <button type="button" className="link-button small" onClick={() => setRemoving(a.id)}>
                      Retirar
                    </button>
                  )}
                </div>
                {removing === a.id && (
                  <div className="attach-card__remove">
                    <input aria-label="Motivo del retiro" placeholder="Motivo del retiro" maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} />
                    <button type="button" className="button button--danger button--sm" disabled={busy || !reason.trim()} onClick={() => remove(a)}>
                      Retirar
                    </button>
                    <button type="button" className="button button--ghost button--sm" onClick={() => setRemoving(null)}>
                      Cancelar
                    </button>
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
