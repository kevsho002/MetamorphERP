import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { employeesApi } from "../api.js";
import ImportReport from "../components/ImportReport.jsx";

/** Reporte de un lote ya procesado (/hcm/employees/imports/:id). */
export default function ImportBatchPage() {
  const { id } = useParams();
  const [state, setState] = useState({ loading: true, batch: null, error: null });

  useEffect(() => {
    const controller = new AbortController();
    setState({ loading: true, batch: null, error: null });
    employeesApi
      .importBatch(id, {}, { signal: controller.signal })
      .then((batch) => setState({ loading: false, batch, error: null }))
      .catch((err) => {
        if (err.name === "AbortError") return;
        setState({ loading: false, batch: null, error: err.status === 404 ? "El lote no existe." : err.message });
      });
    return () => controller.abort();
  }, [id]);

  return (
    <section className="card card--wide">
      <nav className="breadcrumb" aria-label="Ruta">
        <Link to="/hcm/employees">Empleados</Link>
        <span aria-hidden="true">/</span>
        <Link to="/hcm/employees/imports">Historial de cargas</Link>
        <span aria-hidden="true">/</span>
        <span>Lote #{id}</span>
      </nav>
      {state.loading && <p className="muted">Cargando reporte…</p>}
      {state.error && <p className="error-box">{state.error}</p>}
      {state.batch && (
        <>
          {state.batch.dry_run && <p className="badge badge--info report__mode">Vista previa — no se guardó ningún empleado</p>}
          <ImportReport batch={state.batch} showPermalink={false} />
        </>
      )}
    </section>
  );
}
