import { formatDate } from "../../hcm/lib/format.js";

/**
 * Fase 21 — Alerta FORMAL de recontratación: el colaborador no fue recomendado en su última terminación. Muestra su
 * historial y antecedentes; el generalista autorizado debe reconocerla expresamente para continuar con el reingreso.
 */
export default function RehireAlert({ alert, acknowledged, onAcknowledge, readOnly = false }) {
  if (!alert) return null;
  return (
    <div className="alert alert--error rehire-alert" role="alert">
      <p className="alert__text">
        <strong>Alerta formal de recontratación.</strong> {alert.message}
      </p>
      {alert.details?.length > 0 && (
        <ul className="msg-list">
          {alert.details.map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>
      )}
      {alert.history?.length > 0 && (
        <div className="table-wrap">
          <table className="table table--compact">
            <caption className="muted small">Historial laboral</caption>
            <thead>
              <tr>
                <th scope="col">Evento</th>
                <th scope="col">Desde</th>
                <th scope="col">Hasta</th>
                <th scope="col">AP</th>
                <th scope="col">Detalle</th>
              </tr>
            </thead>
            <tbody>
              {alert.history.map((h) => (
                <tr key={h.id}>
                  <td>{h.kind_label}</td>
                  <td>{formatDate(h.start_date)}</td>
                  <td>{h.end_date ? formatDate(h.end_date) : "—"}</td>
                  <td>{h.folio ?? "—"}</td>
                  <td>
                    {h.kind === "TERMINATION"
                      ? `${h.termination_reason_label || "—"} · ${h.rehire_eligible === false ? "NO recomendable" : "Recomendable"}${h.hr_notes ? ` · ${h.hr_notes}` : ""}`
                      : h.days
                        ? `${h.days} día(s)`
                        : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!readOnly && (
        <label className="checkbox">
          <input type="checkbox" checked={acknowledged} onChange={(e) => onAcknowledge(e.target.checked)} />
          <span>He revisado el historial y los antecedentes y, como generalista autorizado, continúo con el reingreso bajo mi responsabilidad.</span>
        </label>
      )}
    </div>
  );
}
