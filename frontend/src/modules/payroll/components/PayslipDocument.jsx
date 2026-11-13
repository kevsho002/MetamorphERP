import { currencySymbol } from "../../../app/currency.js";
import { DocLogo } from "../../../components/ui/Brand.jsx";
import { formatDate, formatMoney } from "../../hcm/lib/format.js";
import { formatHours, useTimeFormat } from "../../../app/timeFormat.js";
import { LINE_GROUPS, num, pct } from "../api.js";

const SOURCE = { SALARY: "Salario", WEB_TIMER: "Web Timer", ADHERENCE: "WFM / adherencia", AP: "AP", LAW: "Ley" };

function qty(line) {
  if (line.quantity === null || line.quantity === undefined) return "";
  if (line.unit === "horas") return `${formatHours(line.quantity)} h`; // Fase 21: HH:MM:SS u horas decimales
  return `${num(line.quantity, 2)} ${line.unit ?? ""}`.trim();
}

function rate(line) {
  if (line.rate === null || line.rate === undefined) return "";
  return line.kind === "LEGAL" || line.kind === "EMPLOYER" ? pct(line.rate) : num(line.rate, 4);
}

/**
 * Boleta de pago (Fase 20). `content` es el contenido CONGELADO al cierre (o la vista previa de una planilla calculada):
 * colaborador, periodo, líneas por grupo (devengado con los descuentos de tiempo, retenciones de ley, descuentos
 * autorizados, aportes patronales e insumos de tiempo) y totales. Incluye el espacio de firma del colaborador.
 */
export default function PayslipDocument({ content, hash, preview = false, preliminary = false, pdfHref = null }) {
  useTimeFormat();
  if (!content) return null;
  const { employee, period, totals, currency } = content;
  const lines = content.lines ?? [];
  return (
    <article className={`payslip${preliminary ? " payslip--preliminary" : ""}`} aria-label={`Boleta ${content.folio ?? ""}`}>
      <header className="payslip__head">
        <div>
          <DocLogo className="payslip__logo" />
          <h2 className="payslip__title">
            Boleta de pago{preliminary ? " PRELIMINAR" : preview ? " (vista previa)" : ""}
          </h2>
          {preliminary && (
            <p className="payslip__disclaimer">
              Vista previa del cálculo en curso: NO es el monto final. Si algo no coincide, reporte una excepción antes del cierre.
            </p>
          )}
          <p className="muted small">
            {period.frequency_label} · {formatDate(period.start)} al {formatDate(period.end)} · pago {formatDate(period.payment_date)}
          </p>
        </div>
        <dl className="payslip__meta">
          <div>
            <dt>Folio</dt>
            <dd>{content.folio ?? "Se asigna al cerrar"}</dd>
          </div>
          <div>
            <dt>Planilla</dt>
            <dd>{content.payroll_code}</dd>
          </div>
          {pdfHref && (
            <div className="payslip__pdf">
              <a className="button button--sm" href={pdfHref} download>
                Descargar PDF
              </a>
            </div>
          )}
        </dl>
      </header>

      <dl className="payslip__who">
        <div>
          <dt>Colaborador</dt>
          <dd>
            {employee.name} <span className="muted">({employee.code})</span>
          </dd>
        </div>
        <div>
          <dt>Documento</dt>
          <dd>{employee.national_id ?? "—"}</dd>
        </div>
        <div>
          <dt>Departamento</dt>
          <dd>{employee.cost_center_name ?? employee.cost_center ?? "—"}</dd>
        </div>
        <div>
          <dt>Salario base mensual</dt>
          <dd>{formatMoney(content.base_salary, currency)}</dd>
        </div>
        <div>
          <dt>Días pagados (equivalentes)</dt>
          <dd>{num(content.paid_days)}</dd>
        </div>
        <div>
          <dt>Asistencia (cortes)</dt>
          <dd>{(period.attendance_windows ?? []).map((w) => `${formatDate(w.start)}–${formatDate(w.end)}`).join(", ") || "—"}</dd>
        </div>
      </dl>

      {LINE_GROUPS.map((g) => {
        const rows = lines.filter((l) => g.kinds.includes(l.kind));
        if (!rows.length) return null;
        return (
          <table key={g.title} className="payslip__table">
            <caption>{g.title}</caption>
            <colgroup>
              <col className="payslip__c-concept" />
              <col className="payslip__c-qty" />
              <col className="payslip__c-rate" />
              <col className="payslip__c-source" />
              <col className="payslip__c-amount" />
            </colgroup>
            <thead>
              <tr>
                <th scope="col">Concepto</th>
                <th scope="col">Cantidad</th>
                <th scope="col">Valor / tasa</th>
                <th scope="col">Origen</th>
                <th scope="col" className="num">
                  {g.kinds[0] === "INFO" ? "" : `Monto (${currencySymbol(currency)})`}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((l, i) => (
                <tr key={`${l.code}-${i}`} className={Number(l.amount) < 0 ? "is-negative" : ""}>
                  <td>
                    {l.label}
                    {l.notes && <div className="payslip__note">{l.notes}</div>}
                  </td>
                  <td>{qty(l)}</td>
                  <td>{rate(l)}</td>
                  <td className="small">{l.folio_ap ? `AP ${l.folio_ap}` : SOURCE[l.source] ?? l.source ?? ""}</td>
                  <td className="num">{l.kind === "INFO" ? "" : num(l.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        );
      })}

      <dl className="payslip__totals">
        <div>
          <dt>Total devengado</dt>
          <dd>{formatMoney(totals.gross, currency)}</dd>
        </div>
        <div>
          <dt>Total descuentos</dt>
          <dd>{formatMoney(totals.deductions, currency)}</dd>
        </div>
        <div className="payslip__net">
          <dt>Líquido a recibir</dt>
          <dd>{formatMoney(totals.net, currency)}</dd>
        </div>
      </dl>

      <footer className="payslip__sign">
        <div>
          <span className="payslip__line" />
          <span className="small">Firma del colaborador</span>
        </div>
        <div>
          <span className="payslip__line" />
          <span className="small">Fecha de recibido</span>
        </div>
      </footer>
      {hash && <p className="payslip__hash">Sello SHA-256: {hash}</p>}
    </article>
  );
}

/** Convierte el desglose de una planilla calculada (API) al formato de la boleta, para la vista previa. */
export function previewContent(b) {
  const run = b.run;
  return {
    folio: b.payslip?.folio,
    payroll_code: run.code,
    currency: run.currency,
    employee: { code: b.employee.code, name: b.employee.name, national_id: b.employee.national_id, cost_center: b.employee.cost_center,
      cost_center_name: b.employee.cost_center_name },
    period: { frequency_label: run.pay_frequency_label, start: run.period_start, end: run.period_end, payment_date: run.payment_date,
      attendance_windows: run.windows },
    base_salary: b.detail.base_salary,
    paid_days: b.detail.paid_days,
    lines: b.lines,
    totals: { gross: b.detail.gross_pay, deductions: b.detail.total_deductions, net: b.detail.net_pay },
  };
}
