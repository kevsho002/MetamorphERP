import { useEffect, useMemo, useRef, useState } from "react";
import { useClientConfig } from "../../../app/ClientConfigContext.jsx";
import { employeesApi } from "../api.js";
import { todayIso } from "../lib/format.js";

const EXTENSIONS = [".png", ".jpg", ".jpeg"];
const MIME = ["image/png", "image/jpeg"];

/** Validación previa en el navegador (el servidor vuelve a validar por contenido). */
export function checkImageFile(file, maxMb) {
  if (!file) return "Seleccione una imagen.";
  const name = file.name.toLowerCase();
  if (!EXTENSIONS.some((ext) => name.endsWith(ext))) return "Formato no permitido: use PNG, JPG o JPEG.";
  if (file.type && !MIME.includes(file.type)) return `El archivo no parece una imagen PNG/JPEG (${file.type}).`;
  if (file.size > maxMb * 1024 * 1024) {
    return `La imagen pesa ${(file.size / 1048576).toFixed(1)} MB; el máximo es ${maxMb} MB.`;
  }
  if (file.size === 0) return "El archivo está vacío.";
  return null;
}

/**
 * Diálogo para subir la fotografía de perfil o un documento oficial (imagen).
 * mode: "photo" | "document". `documents` = checklist del expediente (para elegir el tipo).
 */
export default function ImageUploadDialog({ mode, employeeCode, documents = [], initialType, onClose, onUploaded }) {
  const { config } = useClientConfig();
  const maxMb = config.max_document_mb ?? 5;
  const uploadable = useMemo(() => documents.filter((d) => d.viewable), [documents]);
  const [type, setType] = useState(initialType ?? uploadable[0]?.code ?? "");
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [dims, setDims] = useState(null);
  const [issueDate, setIssueDate] = useState("");
  const [expiryDate, setExpiryDate] = useState("");
  const [errors, setErrors] = useState({});
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef(null);
  const dialogRef = useRef(null);
  const selected = uploadable.find((d) => d.code === type);
  const isPhoto = mode === "photo";

  useEffect(() => {
    dialogRef.current?.querySelector("select, button, input")?.focus();
    const onKey = (e) => e.key === "Escape" && !busy && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);

  useEffect(() => () => preview && URL.revokeObjectURL(preview), [preview]);

  const pick = (candidate) => {
    const problem = checkImageFile(candidate, maxMb);
    setErrors(problem ? { file: problem } : {});
    setDims(null);
    if (problem) {
      setFile(null);
      setPreview(null);
      return;
    }
    setFile(candidate);
    setPreview(URL.createObjectURL(candidate));
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    if (busy) return;
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) pick(dropped);
  };

  const validate = () => {
    const errs = {};
    const fileProblem = checkImageFile(file, maxMb);
    if (fileProblem) errs.file = fileProblem;
    if (!isPhoto) {
      if (!type) errs.document_type = "Seleccione el tipo de documento.";
      if (issueDate && issueDate > todayIso()) errs.issue_date = "La fecha de emisión no puede ser futura.";
      if (selected?.requires_expiry && !expiryDate) errs.expiry_date = "Este documento requiere fecha de vencimiento.";
      if (issueDate && expiryDate && expiryDate < issueDate) errs.expiry_date = "El vencimiento es anterior a la emisión.";
    }
    return errs;
  };

  async function submit(e) {
    e.preventDefault();
    const errs = validate();
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      const result = isPhoto
        ? await employeesApi.uploadPhoto(employeeCode, file)
        : await employeesApi.uploadDocument(employeeCode, { file, documentType: type, issueDate, expiryDate });
      onUploaded(result);
    } catch (err) {
      const fieldErrors = {};
      (err.body?.errors ?? []).forEach((x) => {
        fieldErrors[x.field || "_general"] = x.message;
      });
      if (!Object.keys(fieldErrors).length) fieldErrors._general = err.message;
      setErrors(fieldErrors);
    } finally {
      setBusy(false);
    }
  }

  const title = isPhoto ? "Fotografía de perfil" : selected?.current ? `Nueva versión: ${selected.label}` : "Agregar documento";

  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <form
        ref={dialogRef}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="upload-title"
        onSubmit={submit}
        noValidate
      >
        <h2 id="upload-title" className="section-title">
          {title}
        </h2>
        <p className="muted small">
          {isPhoto
            ? "PNG, JPG o JPEG. Se ajusta a 800 px y se eliminan los metadatos (ubicación, cámara)."
            : "Imagen PNG, JPG o JPEG del documento. Se guarda el original con su huella SHA-256; las versiones anteriores quedan en el historial."}{" "}
          Máximo {maxMb} MB.
        </p>

        {!isPhoto && (
          <div className="form-grid">
            <div className="field">
              <label htmlFor="upload-type" className="field__label">
                Tipo de documento<span className="field__req">*</span>
              </label>
              <select
                id="upload-type"
                value={type}
                onChange={(e) => setType(e.target.value)}
                disabled={busy || Boolean(initialType)}
                aria-invalid={Boolean(errors.document_type)}
              >
                <option value="">— Seleccione —</option>
                {uploadable.map((d) => (
                  <option key={d.code} value={d.code}>
                    {d.label}
                    {d.required ? " (obligatorio)" : ""}
                  </option>
                ))}
              </select>
              {errors.document_type ? (
                <small className="field__error">{errors.document_type}</small>
              ) : (
                selected?.help && <small className="field__hint">{selected.help}</small>
              )}
            </div>
            <div className="field">
              <label htmlFor="upload-issue" className="field__label">
                Fecha de emisión
              </label>
              <input
                id="upload-issue"
                type="date"
                value={issueDate}
                max={todayIso()}
                onChange={(e) => setIssueDate(e.target.value)}
                disabled={busy}
                aria-invalid={Boolean(errors.issue_date)}
              />
              {errors.issue_date && <small className="field__error">{errors.issue_date}</small>}
            </div>
            <div className="field">
              <label htmlFor="upload-expiry" className="field__label">
                Fecha de vencimiento{selected?.requires_expiry && <span className="field__req">*</span>}
              </label>
              <input
                id="upload-expiry"
                type="date"
                value={expiryDate}
                onChange={(e) => setExpiryDate(e.target.value)}
                disabled={busy}
                aria-invalid={Boolean(errors.expiry_date)}
              />
              {errors.expiry_date ? (
                <small className="field__error">{errors.expiry_date}</small>
              ) : (
                <small className="field__hint">{selected?.requires_expiry ? "Obligatoria para este documento." : "Opcional."}</small>
              )}
            </div>
          </div>
        )}

        <div
          className={`dropzone upload-zone${dragging ? " dropzone--active" : ""}${file ? " dropzone--filled" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          {preview ? (
            <figure className="upload-preview">
              <img
                src={preview}
                alt="Vista previa"
                className={isPhoto ? "upload-preview__photo" : undefined}
                onLoad={(e) => setDims({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
              />
              <figcaption className="muted small">
                {file.name} · {(file.size / 1024).toFixed(0)} KB{dims ? ` · ${dims.w}×${dims.h} px` : ""}
              </figcaption>
            </figure>
          ) : (
            <p>
              <span className="dropzone__icon" aria-hidden="true">
                🖼
              </span>
              Arrastre la imagen aquí o
            </p>
          )}
          <button type="button" className="button button--ghost button--sm" onClick={() => inputRef.current?.click()} disabled={busy}>
            {file ? "Elegir otra imagen" : "Elegir imagen"}
          </button>
          <input
            ref={inputRef}
            type="file"
            accept=".png,.jpg,.jpeg,image/png,image/jpeg"
            hidden
            onChange={(e) => {
              pick(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </div>
        {errors.file && (
          <p className="field__error" role="alert">
            {errors.file}
          </p>
        )}
        {errors._general && (
          <p className="alert alert--error" role="alert">
            {errors._general}
          </p>
        )}

        <footer className="form-actions">
          <button type="button" className="button button--ghost" onClick={onClose} disabled={busy}>
            Cancelar
          </button>
          <button type="submit" className="button" disabled={busy || !file}>
            {busy ? "Subiendo…" : "Guardar en el expediente"}
          </button>
        </footer>
      </form>
    </div>
  );
}
