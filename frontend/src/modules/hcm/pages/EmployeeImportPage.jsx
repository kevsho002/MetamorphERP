import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { employeesApi } from "../api.js";
import FileDropzone from "../components/FileDropzone.jsx";
import ImportReport from "../components/ImportReport.jsx";
import { formatDate, todayIso } from "../lib/format.js";

const ATOMICITY = [
  {
    value: "COUNTRY",
    label: "Todo o nada por país (recomendado)",
    help: "Si una fila de un país tiene errores, no se crea ningún empleado de ese país; los demás países sí se procesan.",
  },
  {
    value: "ROW",
    label: "Fila por fila",
    help: "Se crean todas las filas válidas y se reportan las que tienen errores.",
  },
];

/** Plantilla vigente hoy por país (para descargar el CSV de ejemplo). */
function useCurrentTemplates() {
  const [templates, setTemplates] = useState([]);
  useEffect(() => {
    const controller = new AbortController();
    employeesApi
      .templates({ active: 1, page_size: 100 }, { signal: controller.signal })
      .then((data) => {
        const list = data.results ?? data;
        const today = todayIso();
        const byCountry = {};
        list
          .filter((t) => t.effective_date <= today)
          .forEach((t) => {
            if (!byCountry[t.country] || byCountry[t.country].effective_date < t.effective_date) byCountry[t.country] = t;
          });
        setTemplates(Object.values(byCountry).sort((a, b) => a.country.localeCompare(b.country)));
      })
      .catch(() => {});
    return () => controller.abort();
  }, []);
  return templates;
}

/**
 * Carga masiva de empleados: 1) subir archivo, 2) validar (vista previa, no guarda),
 * 3) revisar el reporte por fila, 4) aplicar la carga.
 */
export default function EmployeeImportPage() {
  const templates = useCurrentTemplates();
  const [file, setFile] = useState(null);
  const [atomicity, setAtomicity] = useState("COUNTRY");
  const [dryRun, setDryRun] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [report, setReport] = useState(null);
  // Vista previa vigente: solo se puede "aplicar" el mismo archivo con las mismas opciones.
  const [preview, setPreview] = useState(null);
  const reportRef = useRef(null);

  const previewMatches = useMemo(
    () => Boolean(preview && file && preview.file === file && preview.atomicity === atomicity),
    [preview, file, atomicity],
  );

  useEffect(() => {
    if (report) reportRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [report]);

  async function run(isDryRun) {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const batch = await employeesApi.importFile(file, { dryRun: isDryRun, atomicity });
      setReport(batch);
      if (isDryRun) setPreview({ file, atomicity, batch });
      else {
        setPreview(null);
        if (batch.created_rows > 0) setFile(null); // evita aplicar dos veces el mismo archivo
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const onSubmit = (e) => {
    e.preventDefault();
    run(dryRun);
  };

  // En la vista previa, VALID = se crearía al aplicar (las válidas bloqueadas por su país quedan NOT_APPLIED).
  const previewBatch = preview?.batch;
  const willCreate = previewBatch ? previewBatch.rows.filter((r) => r.status === "VALID").length : 0;
  const canApply = previewMatches && willCreate > 0;

  const applyPreview = () => {
    const b = previewBatch;
    const skipped = b.total_rows - willCreate;
    const message =
      skipped > 0
        ? `Se crearán ${willCreate} empleado(s). ${skipped} fila(s) con errores o bloqueadas por su país NO se crearán. ¿Desea continuar?`
        : `Se crearán ${willCreate} empleado(s) con su ID corporativo y expediente digital. ¿Desea continuar?`;
    if (window.confirm(message)) run(false);
  };

  return (
    <div className="stack">
      <section className="card card--wide">
        <nav className="breadcrumb" aria-label="Ruta">
          <Link to="/hcm/employees">Empleados</Link>
          <span aria-hidden="true">/</span>
          <span>Carga masiva</span>
        </nav>
        <header className="card__header">
          <div>
            <h1 className="page-title">Carga masiva de empleados</h1>
            <p className="muted page-subtitle">
              Suba un archivo, revise la vista previa y aplique la carga cuando todo esté correcto.
            </p>
          </div>
          <Link className="button button--ghost" to="/hcm/employees/imports">
            Historial de cargas
          </Link>
        </header>

        <ol className="steps" aria-label="Pasos">
          <li className={file ? "steps__item steps__item--done" : "steps__item steps__item--current"}>Archivo</li>
          <li className={previewMatches ? "steps__item steps__item--done" : file ? "steps__item steps__item--current" : "steps__item"}>
            Vista previa
          </li>
          <li className={report && !report.dry_run ? "steps__item steps__item--done" : previewMatches ? "steps__item steps__item--current" : "steps__item"}>
            Aplicar
          </li>
        </ol>

        <form className="import-form" onSubmit={onSubmit}>
          <div className="import-form__main">
            <FileDropzone file={file} onFile={setFile} disabled={busy} />

            <fieldset className="form-section">
              <legend className="form-section__title">Atomicidad</legend>
              {ATOMICITY.map((opt) => (
                <label key={opt.value} className="radio">
                  <input
                    type="radio"
                    name="atomicity"
                    value={opt.value}
                    checked={atomicity === opt.value}
                    onChange={() => setAtomicity(opt.value)}
                    disabled={busy}
                  />
                  <span>
                    <strong>{opt.label}</strong>
                    <small className="muted">{opt.help}</small>
                  </span>
                </label>
              ))}
            </fieldset>

            <label className="checkbox">
              <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} disabled={busy} />
              <span>
                <strong>Solo validar (vista previa)</strong>
                <small className="muted">
                  Revisa todas las reglas —incluidas las de la base de datos— y no guarda nada. Recomendado antes de aplicar.
                </small>
              </span>
            </label>

            {error && (
              <p className="alert alert--error" role="alert">
                {error}
              </p>
            )}

            <div className="form-actions form-actions--start">
              <button type="submit" className={`button${dryRun ? "" : " button--danger"}`} disabled={!file || busy}>
                {busy ? "Procesando…" : dryRun ? "Validar archivo" : "Cargar y aplicar ahora"}
              </button>
              {canApply && (
                <button type="button" className="button button--success" onClick={applyPreview} disabled={busy}>
                  Aplicar carga ({willCreate} empleado{willCreate === 1 ? "" : "s"})
                </button>
              )}
            </div>
            {preview && !previewMatches && file && (
              <p className="muted small">Cambió el archivo o la atomicidad: vuelva a validar antes de aplicar.</p>
            )}
          </div>

          <aside className="import-form__aside">
            <h2 className="section-title">Plantillas de archivo</h2>
            <p className="muted small">
              Descargue el CSV de ejemplo del país: trae los encabezados exactos de su plantilla vigente. Puede mezclar
              varios países en un mismo archivo (columna <code>country</code>).
            </p>
            <ul className="template-links">
              {templates.map((t) => (
                <li key={t.id}>
                  <a href={employeesApi.templateCsvUrl(t.id)} download>
                    {t.country_name} ({t.country})
                  </a>
                  <span className="muted small"> · desde {formatDate(t.effective_date)}</span>
                </li>
              ))}
              {templates.length === 0 && <li className="muted small">No hay plantillas activas.</li>}
            </ul>
            <h2 className="section-title">Consejos</h2>
            <ul className="tips muted small">
              <li>Deje vacía la columna del ID corporativo: el sistema lo genera.</li>
              <li>
                Columna <code>schedule</code> (obligatoria): horario de la Primera AP de asignación de horario, p. ej.{" "}
                <code>L-V 08:00-17:00 60; S 08:00-12:00</code> (días L M X J V S D, entrada-salida y minutos de almuerzo). Cada
                alta crea su AP fundacional con fecha efectiva = fecha de ingreso.
              </li>
              <li>En Excel, dé formato de texto a documentos con ceros a la izquierda.</li>
              <li>Fechas en AAAA-MM-DD o DD/MM/AAAA.</li>
              <li>Encabezados en español o inglés (p. ej. «pais» o «country»).</li>
            </ul>
          </aside>
        </form>
      </section>

      {report && (
        <section className="card card--wide" ref={reportRef}>
          {report.dry_run && (
            <p className="badge badge--info report__mode">Vista previa — no se guardó ningún empleado</p>
          )}
          <ImportReport key={report.id} batch={report} />
          {report.dry_run && canApply && (
            <div className="form-actions form-actions--start">
              <button type="button" className="button button--success" onClick={applyPreview} disabled={busy}>
                Aplicar esta carga ({willCreate} empleado{willCreate === 1 ? "" : "s"})
              </button>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
