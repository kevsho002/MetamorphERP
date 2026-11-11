import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { formatDateTime } from "../lib/format.js";
import { MessageList } from "./Feedback.jsx";
import StatusBadge from "./StatusBadge.jsx";

const FILTERS = [
  { id: "all", label: "Todas" },
  { id: "ok", label: "Exitosas" },
  { id: "warnings", label: "Con advertencias" },
  { id: "errors", label: "Con errores" },
  { id: "not_applied", label: "No aplicadas" },
];

const matches = (row, filter) => {
  switch (filter) {
    case "ok":
      return row.status === "CREATED" || row.status === "VALID";
    case "warnings":
      return row.warnings?.length > 0;
    case "errors":
      return row.status === "ERROR";
    case "not_applied":
      return row.status === "NOT_APPLIED";
    default:
      return true;
  }
};

function csvCell(value) {
  const text = String(value ?? "");
  return /[",\n;]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** Descarga el reporte por fila como CSV (para compartir o corregir el archivo original). */
function downloadReport(batch) {
  const header = ["fila", "estado", "pais", "id_corporativo", "retroalimentacion", "errores", "advertencias"];
  const lines = batch.rows.map((r) =>
    [
      r.row_number,
      r.status,
      r.country ?? "",
      r.employee_code ?? "",
      r.feedback,
      (r.errors ?? []).map((e) => `${e.field ?? ""}: ${e.message}`).join(" | "),
      (r.warnings ?? []).map((e) => `${e.field ?? ""}: ${e.message}`).join(" | "),
    ]
      .map(csvCell)
      .join(","),
  );
  const BOM = String.fromCharCode(0xfeff); // Excel reconoce UTF-8 (tildes, ñ)
  const blob = new Blob([BOM, [header.join(","), ...lines].join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: `reporte_lote_${batch.id}.csv` });
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/**
 * Reporte de una carga masiva: resumen en lenguaje natural, indicadores,
 * observaciones del archivo y el detalle fila por fila (filtrable).
 */
export default function ImportReport({ batch, showPermalink = true }) {
  const [filter, setFilter] = useState(() => (batch.error_rows > 0 ? "errors" : "all"));
  const [expanded, setExpanded] = useState(() => new Set());
  const rows = useMemo(() => batch.rows ?? [], [batch.rows]);
  const counts = useMemo(
    () => Object.fromEntries(FILTERS.map((f) => [f.id, rows.filter((r) => matches(r, f.id)).length])),
    [rows],
  );
  const visible = rows.filter((r) => matches(r, filter));
  const okLabel = batch.dry_run ? "Válidas" : "Creadas";
  const okCount = batch.dry_run ? rows.filter((r) => r.status === "VALID").length : batch.created_rows;
  const toggle = (n) =>
    setExpanded((s) => {
      const next = new Set(s);
      if (next.has(n)) next.delete(n);
      else next.add(n);
      return next;
    });

  return (
    <section className="report" aria-labelledby="report-title">
      <header className="report__header">
        <div>
          <h2 id="report-title" className="section-title">
            Lote #{batch.id} · {batch.file_name} <StatusBadge type="batch" value={batch.status} />
          </h2>
          <p className="muted small">
            {batch.source_format} · {batch.atomicity === "COUNTRY" ? "Todo o nada por país" : "Fila por fila"} ·{" "}
            {formatDateTime(batch.finished_at)} · {batch.created_by ?? "—"}
          </p>
        </div>
        <div className="actions">
          <button type="button" className="button button--ghost button--sm" onClick={() => downloadReport(batch)}>
            Descargar reporte (CSV)
          </button>
          {showPermalink && (
            <Link className="button button--ghost button--sm" to={`/hcm/employees/imports/${batch.id}`}>
              Abrir en el historial
            </Link>
          )}
        </div>
      </header>

      <div className={`alert alert--${batch.error_rows ? (batch.created_rows || batch.dry_run ? "warn" : "error") : "ok"}`}>
        <p className="alert__text">{batch.summary}</p>
      </div>

      <dl className="kpis">
        <div className="kpi">
          <dt>Filas</dt>
          <dd>{batch.total_rows}</dd>
        </div>
        <div className="kpi kpi--ok">
          <dt>{okLabel}</dt>
          <dd>{okCount}</dd>
        </div>
        <div className="kpi kpi--warn">
          <dt>Con advertencias</dt>
          <dd>{batch.warning_rows}</dd>
        </div>
        <div className="kpi kpi--error">
          <dt>Con errores</dt>
          <dd>{batch.error_rows}</dd>
        </div>
        <div className="kpi kpi--muted">
          <dt>No aplicadas</dt>
          <dd>{batch.skipped_rows}</dd>
        </div>
      </dl>

      {batch.notes?.length > 0 && (
        <div className="msg-list msg-list--info">
          <p className="msg-list__title">Observaciones del archivo</p>
          <ul>
            {batch.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="tabs" role="tablist" aria-label="Filtrar filas">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            role="tab"
            aria-selected={filter === f.id}
            className={`tab${filter === f.id ? " tab--active" : ""}`}
            onClick={() => setFilter(f.id)}
            disabled={counts[f.id] === 0 && f.id !== "all"}
          >
            {f.label} <span className="tab__count">{counts[f.id]}</span>
          </button>
        ))}
      </div>

      <ol className="row-list">
        {visible.map((row) => {
          const open = expanded.has(row.row_number);
          return (
            <li key={row.row_number} className={`row-card row-card--${row.status.toLowerCase()}`}>
              <div className="row-card__head">
                <span className="row-card__num">Fila {row.row_number}</span>
                <StatusBadge type="row" value={row.status} />
                {row.country && <span className="tag">{row.country}</span>}
                {row.employee_code && (
                  <Link to={`/hcm/employees/${row.employee_code}`}>
                    <code>{row.employee_code}</code>
                  </Link>
                )}
                {row.warnings?.length > 0 && row.status !== "ERROR" && <span className="tag tag--warn">Advertencias</span>}
              </div>
              <p className="row-card__feedback">{row.feedback}</p>
              <MessageList messages={row.errors} kind="error" />
              <MessageList messages={row.warnings} kind="warn" />
              {row.raw_data && Object.keys(row.raw_data).length > 0 && (
                <>
                  <button type="button" className="link-button" aria-expanded={open} onClick={() => toggle(row.row_number)}>
                    {open ? "Ocultar datos recibidos" : "Ver datos recibidos"}
                  </button>
                  {open && (
                    <dl className="raw-data">
                      {Object.entries(row.raw_data).map(([k, v]) => (
                        <div key={k}>
                          <dt>{k}</dt>
                          <dd>{v === null || v === "" ? <span className="muted">(vacío)</span> : String(v)}</dd>
                        </div>
                      ))}
                    </dl>
                  )}
                </>
              )}
            </li>
          );
        })}
      </ol>
      {visible.length === 0 && <p className="muted">No hay filas en esta categoría.</p>}
    </section>
  );
}
