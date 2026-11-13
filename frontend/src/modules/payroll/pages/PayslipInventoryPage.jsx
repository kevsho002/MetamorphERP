import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Pagination from "../../../components/ui/Pagination.jsx";
import { formatDate, formatDateTime, formatMoney, todayIso } from "../../hcm/lib/format.js";
import { MONTHS, payrollApi } from "../api.js";

const PAGE_SIZE = 50;
const FILTER_KEYS = ["year", "month", "payroll", "batch", "frequency", "cost_center", "printed", "signature", "archived", "search"];
const BATCH_STATUS = {
  PENDING: { label: "Faltan impresiones", cls: "badge--warn" },
  PRINTED: { label: "Impreso · faltan firmas", cls: "badge--info" },
  SIGNED: { label: "Firmado · por archivar", cls: "badge--info" },
  ARCHIVED: { label: "Archivado", cls: "badge--ok" },
  EMPTY: { label: "Vacío", cls: "badge--muted" },
};

/**
 * Inventario de boletas físicas (Fase 20, exclusivo de RRHH): lotes por periodo (quincena / mes) y departamento, y el
 * estado de cada boleta: impresa o faltante por imprimir, firmada en físico por el colaborador o pendiente de firma, y
 * archivada (con su ubicación). Filtros por quincena, mes, departamento y estados para auditorías internas y legales.
 */
export default function PayslipInventoryPage() {
  const [params, setParams] = useSearchParams();
  const thisYear = Number(todayIso().slice(0, 4));
  const f = Object.fromEntries(FILTER_KEYS.map((k) => [k, params.get(k) ?? ""]));
  if (!params.has("year")) f.year = String(thisYear);
  const page = Number(params.get("page")) || 1;
  const [catalogs, setCatalogs] = useState(null);
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [batches, setBatches] = useState([]);
  const [reload, setReload] = useState(0);
  const [selected, setSelected] = useState(() => new Set());
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [signedOn, setSignedOn] = useState(todayIso());
  const [location, setLocation] = useState("");
  const [revert, setRevert] = useState({ action: "UNSIGN", reason: "" });
  const [search, setSearch] = useState(f.search);

  const setFilter = (changes) => {
    const next = { ...f, ...changes };
    const out = Object.fromEntries(Object.entries(next).filter(([k, v]) => v !== "" && !(k === "year" && v === String(thisYear) && !params.has("year"))));
    setParams(out, { replace: true });
    setSelected(new Set());
  };

  useEffect(() => {
    const controller = new AbortController();
    payrollApi.catalogs({ signal: controller.signal }).then(setCatalogs).catch(() => {});
    return () => controller.abort();
  }, []);

  const query = useMemo(() => {
    const q = Object.fromEntries(Object.entries(f).filter(([, v]) => v !== ""));
    return q;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.toString()]);

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    payrollApi
      .payslips({ ...query, page, page_size: PAGE_SIZE }, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    payrollApi
      .batches({ year: query.year, month: query.month, cost_center: query.cost_center, payroll: query.payroll }, { signal: controller.signal })
      .then((b) => setBatches(b.results))
      .catch(() => {});
    return () => controller.abort();
  }, [query, page, reload]);

  useEffect(() => {
    const t = setTimeout(() => search !== f.search && setFilter({ search }), 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const data = state.data;
  const rows = data?.results ?? [];
  const canManage = data?.can_manage;
  const s = data?.summary;
  const payrollCodes = useMemo(() => [...new Set(batches.map((b) => b.payroll_code))], [batches]);
  const allOnPage = rows.length > 0 && rows.every((r) => selected.has(r.id));
  const toggle = (id) => setSelected((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });
  const toggleAll = () => setSelected((prev) => {
    const next = new Set(prev);
    rows.forEach((r) => (allOnPage ? next.delete(r.id) : next.add(r.id)));
    return next;
  });

  const run = (action, extra = {}) => {
    setBusy(true);
    setNotice(null);
    payrollApi
      .payslipAction({ ids: [...selected], action, ...extra })
      .then((b) => {
        setNotice({ ok: b.changed > 0, text: b.feedback + (b.skipped.length ? ` ${b.skipped.slice(0, 5).join(" · ")}` : "") });
        setSelected(new Set());
        setReload((k) => k + 1);
      })
      .catch((err) => setNotice({ ok: false, text: err.message }))
      .finally(() => setBusy(false));
  };
  const saveLocation = (b, value) => {
    payrollApi.updateBatch(b.id, { archive_location: value }).then((r) => {
      setNotice({ ok: true, text: r.feedback });
      setReload((k) => k + 1);
    }).catch((err) => setNotice({ ok: false, text: err.message }));
  };
  const years = [...new Set([...(catalogs?.years ?? []), thisYear, Number(f.year)])].sort((a, b) => a - b);
  const pctOf = (n) => (s?.total ? Math.round((n / s.total) * 100) : 0);

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Inventario de boletas físicas</h1>
          <p className="muted page-subtitle">
            Control de RRHH por lote (periodo y departamento): impresión, firma del colaborador en físico y archivo. Las boletas se generan al cerrar cada
            planilla y su contenido no cambia.
          </p>
        </div>
      </header>

      <div className="filters pay-filters" role="search">
        <label className="field">
          <span className="field__label">Año</span>
          <select value={f.year} onChange={(e) => setFilter({ year: e.target.value, payroll: "", batch: "" })}>
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Mes</span>
          <select value={f.month} onChange={(e) => setFilter({ month: e.target.value, payroll: "", batch: "" })}>
            <option value="">Todos</option>
            {MONTHS.map((m, i) => (
              <option key={m} value={i + 1}>
                {m}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Quincena / periodo</span>
          <select value={f.payroll} onChange={(e) => setFilter({ payroll: e.target.value, batch: "" })}>
            <option value="">Todos</option>
            {payrollCodes.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Departamento</span>
          <select value={f.cost_center} onChange={(e) => setFilter({ cost_center: e.target.value, batch: "" })}>
            <option value="">Todos</option>
            {(catalogs?.cost_centers ?? []).map((c) => (
              <option key={c.code} value={c.code}>
                {c.code} · {c.name}
              </option>
            ))}
            <option value="NONE">Sin centro de costos</option>
          </select>
        </label>
        <label className="field">
          <span className="field__label">Impresión</span>
          <select value={f.printed} onChange={(e) => setFilter({ printed: e.target.value })}>
            <option value="">Todas</option>
            <option value="PRINTED">Impresas</option>
            <option value="MISSING">Faltantes por imprimir</option>
          </select>
        </label>
        <label className="field">
          <span className="field__label">Firma</span>
          <select value={f.signature} onChange={(e) => setFilter({ signature: e.target.value })}>
            <option value="">Todas</option>
            <option value="SIGNED">Firmadas en físico</option>
            <option value="PENDING">Pendientes de firma</option>
          </select>
        </label>
        <label className="field">
          <span className="field__label">Archivo</span>
          <select value={f.archived} onChange={(e) => setFilter({ archived: e.target.value })}>
            <option value="">Todas</option>
            <option value="ARCHIVED">Archivadas</option>
            <option value="NOT_ARCHIVED">Sin archivar</option>
          </select>
        </label>
        <label className="field filters__search">
          <span className="field__label">Buscar</span>
          <input type="search" placeholder="Folio, ID o nombre" value={search} onChange={(e) => setSearch(e.target.value)} />
        </label>
        {f.batch && (
          <button type="button" className="link-button" onClick={() => setFilter({ batch: "" })}>
            Quitar filtro de lote
          </button>
        )}
      </div>

      {s && (
        <dl className="kpis">
          <div className="kpi">
            <dt>Boletas</dt>
            <dd>{s.total}</dd>
          </div>
          <div className={`kpi ${s.missing_print ? "kpi--warn" : "kpi--ok"}`}>
            <dt>Impresas · faltantes</dt>
            <dd>
              {s.printed} · {s.missing_print}
            </dd>
          </div>
          <div className={`kpi ${s.pending_signature ? "kpi--warn" : "kpi--ok"}`}>
            <dt>Firmadas · pendientes</dt>
            <dd>
              {s.signed} · {s.pending_signature}
            </dd>
          </div>
          <div className="kpi">
            <dt>Archivadas</dt>
            <dd>
              {s.archived} <span className="muted small">({pctOf(s.archived)} %)</span>
            </dd>
          </div>
        </dl>
      )}

      <section aria-label="Lotes por periodo y departamento">
        <h2 className="section-title">Lotes por periodo y departamento</h2>
        <div className="table-wrap">
          <table className="table pay-batches">
            <thead>
              <tr>
                <th scope="col">Lote</th>
                <th scope="col">Periodo</th>
                <th scope="col">Departamento</th>
                <th scope="col">Avance</th>
                <th scope="col">Ubicación de archivo</th>
                <th scope="col">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {batches.map((b) => (
                <tr key={b.id} className={String(b.id) === f.batch ? "is-selected" : ""}>
                  <td className="small pay-batch-code">
                    <strong>{b.code}</strong>
                    <div>
                      <span className={`badge ${BATCH_STATUS[b.status].cls}`}>{BATCH_STATUS[b.status].label}</span>
                    </div>
                  </td>
                  <td className="small pay-nowrap">
                    {b.pay_frequency_label}
                    <div>
                      {formatDate(b.period_start)}–{formatDate(b.period_end)}
                    </div>
                    <div className="muted">pago {formatDate(b.payment_date)}</div>
                  </td>
                  <td className="small">{b.cost_center ? `${b.cost_center} · ${b.cost_center_name}` : b.cost_center_name}</td>
                  <td>
                    <BatchProgress counts={b.counts} />
                  </td>
                  <td>
                    {canManage ? (
                      <input className="pay-location" aria-label={`Ubicación del lote ${b.code}`} defaultValue={b.archive_location} maxLength={150}
                        placeholder="Caja / ampo / estante" onBlur={(e) => e.target.value !== b.archive_location && saveLocation(b, e.target.value)} />
                    ) : (
                      b.archive_location || "—"
                    )}
                  </td>
                  <td>
                    <div className="pay-actions">
                      <button type="button" className="button button--ghost button--sm" onClick={() => setFilter({ batch: String(b.id) })}>
                        Ver boletas
                      </button>
                      <Link className="button button--ghost button--sm" to={`/payroll/payslips/print?batch=${b.id}`}>
                        Imprimir lote
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}
              {batches.length === 0 && (
                <tr>
                  <td colSpan={6} className="empty">
                    No hay lotes con estos filtros. Se generan al cerrar una planilla.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {notice && (
        <div className={`alert ${notice.ok ? "alert--ok" : "alert--error"} flash`} role="status">
          <p className="alert__text">{notice.text}</p>
        </div>
      )}
      {state.error && <p className="error-box">{state.error}</p>}

      <h2 className="section-title">Boletas</h2>
      {canManage && (
        <div className="pay-bulk" aria-label="Acciones sobre las boletas seleccionadas">
          <span className="muted small">{selected.size} seleccionadas</span>
          <Link className={`button button--ghost button--sm${selected.size ? "" : " is-disabled"}`} aria-disabled={!selected.size}
            to={selected.size ? `/payroll/payslips/print?ids=${[...selected].join(",")}` : "#"}>
            Imprimir
          </Link>
          <button type="button" className="button button--sm" disabled={busy || !selected.size} onClick={() => run("PRINT")}>
            Marcar impresas
          </button>
          <span className="pay-bulk__group">
            <input type="date" aria-label="Fecha de firma" value={signedOn} max={todayIso()} onChange={(e) => setSignedOn(e.target.value)} />
            <button type="button" className="button button--sm" disabled={busy || !selected.size} onClick={() => run("SIGN", { signed_on: signedOn })}>
              Registrar firma
            </button>
          </span>
          <span className="pay-bulk__group">
            <input aria-label="Ubicación de archivo" placeholder="Ubicación (opcional)" value={location} maxLength={150} onChange={(e) => setLocation(e.target.value)} />
            <button type="button" className="button button--sm" disabled={busy || !selected.size} onClick={() => run("ARCHIVE", { location })}>
              Archivar
            </button>
          </span>
          <span className="pay-bulk__group">
            <select aria-label="Revertir" value={revert.action} onChange={(e) => setRevert((r) => ({ ...r, action: e.target.value }))}>
              <option value="UNSIGN">Quitar firma</option>
              <option value="UNARCHIVE">Sacar del archivo</option>
              <option value="UNPRINT">Marcar como no impresa</option>
            </select>
            <input aria-label="Motivo de la reversión" placeholder="Motivo" value={revert.reason} maxLength={200}
              onChange={(e) => setRevert((r) => ({ ...r, reason: e.target.value }))} />
            <button type="button" className="button button--ghost button--sm" disabled={busy || !selected.size || !revert.reason.trim()}
              onClick={() => run(revert.action, { reason: revert.reason })}>
              Revertir
            </button>
          </span>
        </div>
      )}

      <div className="table-wrap" aria-busy={state.loading}>
        <table className="table pay-slips">
          <thead>
            <tr>
              {canManage && (
                <th scope="col" className="pay-check">
                  <input type="checkbox" aria-label="Seleccionar la página" checked={allOnPage} onChange={toggleAll} />
                </th>
              )}
              <th scope="col">Folio</th>
              <th scope="col">Colaborador</th>
              <th scope="col">Periodo</th>
              <th scope="col" className="num">
                Líquido
              </th>
              <th scope="col">Impresión</th>
              <th scope="col">Firma</th>
              <th scope="col">Archivo</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className={selected.has(r.id) ? "is-selected" : ""}>
                {canManage && (
                  <td className="pay-check">
                    <input type="checkbox" aria-label={`Seleccionar ${r.folio}`} checked={selected.has(r.id)} onChange={() => toggle(r.id)} />
                  </td>
                )}
                <td className="small pay-folio">
                  <Link to={`/payroll/payslips/print?ids=${r.id}`} title={`Lote ${r.batch}`}>
                    {r.folio}
                  </Link>
                  <div>
                    <a href={payrollApi.payslipPdfUrl(r.id)} download title="Descargar la boleta en PDF">
                      PDF
                    </a>
                  </div>
                </td>
                <td>
                  {r.full_name}
                  <div className="muted small">
                    {r.employee_code} · {r.cost_center ?? "sin centro de costos"}
                  </div>
                </td>
                <td className="small">
                  {formatDate(r.period_start)}–{formatDate(r.period_end)}
                  <div className="muted">{r.pay_frequency_label}</div>
                </td>
                <td className="num">{formatMoney(r.net_pay, r.currency)}</td>
                <td className="small">
                  {r.printed ? (
                    <>
                      <span className="badge badge--ok">Impresa</span>
                      <div className="muted">
                        {formatDateTime(r.printed_at)}
                        {r.print_count > 1 ? ` · ${r.print_count} impresiones` : ""}
                      </div>
                    </>
                  ) : (
                    <span className="badge badge--warn">Faltante</span>
                  )}
                </td>
                <td className="small">
                  {r.signed ? (
                    <>
                      <span className="badge badge--ok">Firmada</span>
                      <div className="muted">{formatDate(r.signed_on)}</div>
                    </>
                  ) : (
                    <span className="badge badge--muted">Pendiente</span>
                  )}
                </td>
                <td className="small">
                  {r.archived ? (
                    <>
                      <span className="badge badge--ok">Archivada</span>
                      <div className="muted">{r.archive_location || formatDateTime(r.archived_at)}</div>
                    </>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
              </tr>
            ))}
            {!state.loading && rows.length === 0 && (
              <tr>
                <td colSpan={canManage ? 8 : 7} className="empty">
                  No hay boletas con estos filtros.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {data && (
        <Pagination page={page} pageSize={PAGE_SIZE} count={data.count}
          onPage={(p) => setParams((prev) => { const n = new URLSearchParams(prev); n.set("page", String(p)); return n; }, { replace: true })} />
      )}
    </section>
  );
}

function BatchProgress({ counts }) {
  const t = counts.total || 1;
  const bar = (n, cls, label) => (
    <div className="pay-progress" title={`${label}: ${n} de ${counts.total}`}>
      <span className="pay-progress__label">{label}</span>
      <span className="pay-progress__track">
        <span className={`pay-progress__fill ${cls}`} style={{ width: `${(n / t) * 100}%` }} />
      </span>
      <span className="pay-progress__n">
        {n}/{counts.total}
      </span>
    </div>
  );
  return (
    <div className="pay-progress-group">
      {bar(counts.printed, "is-print", "Impresas")}
      {bar(counts.signed, "is-sign", "Firmadas")}
      {bar(counts.archived, "is-archive", "Archivadas")}
    </div>
  );
}
