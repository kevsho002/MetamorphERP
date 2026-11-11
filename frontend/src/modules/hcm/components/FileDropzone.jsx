import { useRef, useState } from "react";

export const ACCEPTED = [".csv", ".xlsx", ".json"];
export const MAX_BYTES = 5 * 1024 * 1024; // mismo límite que el backend (parsers.MAX_FILE_BYTES)

/** Revisión previa en el navegador (el backend vuelve a validar todo). */
export function checkFile(file) {
  const name = file.name.toLowerCase();
  if (name.endsWith(".xls")) return "Los archivos .xls (Excel 97-2003) no se admiten: guárdelo como .xlsx o .csv.";
  if (!ACCEPTED.some((ext) => name.endsWith(ext))) return `Formato no admitido. Use ${ACCEPTED.join(", ")}.`;
  if (file.size === 0) return "El archivo está vacío.";
  if (file.size > MAX_BYTES) return `El archivo pesa ${(file.size / 1048576).toFixed(1)} MB; el máximo es 5 MB.`;
  return null;
}

const formatSize = (bytes) => (bytes < 1024 ? `${bytes} B` : bytes < 1048576 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1048576).toFixed(1)} MB`);

/** Zona para arrastrar y soltar (o seleccionar) un archivo CSV, Excel o JSON. */
export default function FileDropzone({ file, onFile, disabled }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState(null);

  const pick = (candidate) => {
    if (!candidate) return;
    const problem = checkFile(candidate);
    setError(problem);
    onFile(problem ? null : candidate);
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    if (disabled) return;
    const files = e.dataTransfer.files;
    if (files.length > 1) {
      setError("Suelte un solo archivo por carga.");
      return;
    }
    pick(files[0]);
  };

  return (
    <div>
      <div
        className={`dropzone${dragging ? " dropzone--active" : ""}${file ? " dropzone--filled" : ""}${disabled ? " dropzone--disabled" : ""}`}
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled}
        aria-describedby="dropzone-help"
        onClick={() => !disabled && inputRef.current?.click()}
        onKeyDown={(e) => {
          if (!disabled && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <span className="dropzone__icon" aria-hidden="true">
          ⬆
        </span>
        {file ? (
          <p>
            <strong>{file.name}</strong> <span className="muted">({formatSize(file.size)})</span>
            <br />
            <span className="muted small">Haga clic o suelte otro archivo para reemplazarlo.</span>
          </p>
        ) : (
          <p>
            <strong>Arrastre aquí su archivo</strong> o haga clic para seleccionarlo
          </p>
        )}
        <p id="dropzone-help" className="muted small">
          CSV, Excel (.xlsx) o JSON · máximo 5 MB / 5000 filas · una fila por empleado
        </p>
        <input
          ref={inputRef}
          type="file"
          hidden
          accept={`${ACCEPTED.join(",")},text/csv,application/json,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`}
          onChange={(e) => {
            pick(e.target.files?.[0]);
            e.target.value = ""; // permite volver a elegir el mismo archivo tras corregirlo
          }}
        />
      </div>
      {error && (
        <p className="field__error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
