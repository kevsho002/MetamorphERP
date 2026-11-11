import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { todayIso } from "../../hcm/lib/format.js";
import { addMinutes, adhApi, hhmm, wallMs } from "../api.js";
import Timeline from "../components/Timeline.jsx";

const pad = (n) => String(n).padStart(2, "0");
const isoAt = (ms) => {
  const d = new Date(ms);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}:00:00`;
};

/**
 * Planificador de segmentos (WFM). El CONTENEDOR es el turno que asignó la AP de horario; dentro de él WFM inserta
 * segmentos preconfigurados (Break, Almuerzo, Capacitación, Coaching, Back Office…). Lo que no cubre ningún segmento
 * es de la actividad predeterminada (Producción).
 */
export default function SegmentPlannerPage() {
  const [params, setParams] = useSearchParams();
  const filters = useMemo(
    () => ({ date: params.get("date") ?? todayIso(), group: params.get("group") ?? "", employee: params.get("employee") ?? "" }),
    [params],
  );
  const [catalogs, setCatalogs] = useState(null);
  const [state, setState] = useState({ loading: false, data: null, error: null });
  const [reloadKey, setReloadKey] = useState(0);
  const [notice, setNotice] = useState(null);
  const [selected, setSelected] = useState(null); // segmento en edición
  const [picked, setPicked] = useState(new Set()); // agentes elegidos para programar

  useEffect(() => {
    const controller = new AbortController();
    adhApi
      .catalogs({ signal: controller.signal })
      .then((data) => {
        setCatalogs(data);
        if (!params.get("group") && !params.get("employee") && data.groups[0]) {
          setParams((p) => ({ ...Object.fromEntries(p), group: data.groups[0].code }), { replace: true });
        }
      })
      .catch((err) => err.name !== "AbortError" && setState((s) => ({ ...s, error: err.message })));
    return () => controller.abort();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!filters.group && !filters.employee) return undefined;
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    adhApi
      .planner(filters, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => err.name !== "AbortError" && setState({ loading: false, data: null, error: err.message }));
    return () => controller.abort();
  }, [filters, reloadKey]);

  const update = (changes) => {
    const next = { ...filters, ...changes };
    setParams(Object.fromEntries(Object.entries(next).filter(([, v]) => v)), { replace: true });
    setSelected(null);
    setPicked(new Set());
  };

  const done = useCallback((body) => {
    setNotice({ ok: true, text: body.feedback, skipped: body.skipped });
    setSelected(null);
    setReloadKey((k) => k + 1);
  }, []);
  const fail = useCallback((err) => setNotice({ ok: false, text: err.message }), []);

  const data = state.data;
  const rows = useMemo(() => data?.rows ?? [], [data]);
  const canManage = Boolean(data?.can_manage ?? catalogs?.can_manage);
  const activities = catalogs?.activities ?? [];

  // Ventana común a todas las filas: de la primera entrada a la última salida, redondeada a horas (mín. 06–20 h).
  const range = useMemo(() => {
    const base = wallMs(`${filters.date}T00:00:00`);
    let lo = base + 6 * 3_600_000;
    let hi = base + 20 * 3_600_000;
    rows.forEach((r) => r.containers.forEach((c) => { lo = Math.min(lo, wallMs(c.start)); hi = Math.max(hi, wallMs(c.end)); }));
    lo = Math.floor(lo / 3_600_000) * 3_600_000 - 3_600_000;
    hi = Math.ceil(hi / 3_600_000) * 3_600_000 + 3_600_000;
    return { start: isoAt(lo), end: isoAt(hi) };
  }, [rows, filters.date]);

  const toggle = (code) =>
    setPicked((s) => {
      const next = new Set(s);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Planificador de segmentos</h1>
          <p className="muted page-subtitle">
            El contenedor de cada agente es su turno vigente (AP de horario). Inserte segmentos de actividad dentro del turno; el resto del contenedor es{" "}
            {activities.find((a) => a.is_default)?.name ?? "la actividad predeterminada"}.
          </p>
        </div>
      </header>

      <div className="filters" role="search">
        <label className="field">
          <span className="field__label">Fecha del turno</span>
          <input type="date" value={filters.date} onChange={(e) => e.target.value && update({ date: e.target.value })} />
        </label>
        <label className="field">
          <span className="field__label">Grupo de agentes</span>
          <select value={filters.group} onChange={(e) => update({ group: e.target.value, employee: "" })}>
            <option value="">—</option>
            {(catalogs?.groups ?? []).map((g) => (
              <option key={g.code} value={g.code}>
                {g.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Agente (ID)</span>
          <input type="search" defaultValue={filters.employee} placeholder="SV-2026-000001-7"
            onKeyDown={(e) => e.key === "Enter" && update({ employee: e.currentTarget.value.trim().toUpperCase(), group: "" })} />
        </label>
      </div>

      {notice && (
        <div className={`alert ${notice.ok ? "alert--ok" : "alert--error"} flash`} role="status">
          <p className="alert__text">{notice.text}</p>
          {notice.skipped?.length > 0 && (
            <details>
              <summary>{notice.skipped.length} omitidos</summary>
              <ul className="msg-list msg-list--warn">
                {notice.skipped.map((s) => (
                  <li key={`${s.employee_code}-${s.date}`}>
                    {s.employee_code} · {s.date}: {s.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
      {state.error && <p className="error-box">{state.error}</p>}

      {activities.length > 0 && (
        <ul className="adh-legend" aria-label="Actividades">
          {activities.filter((a) => a.is_active).map((a) => (
            <li key={a.code}>
              <span className="adh-swatch" style={{ background: a.color }} aria-hidden="true" />
              {a.name}
              {!a.is_paid && <span className="muted small"> (no pagado)</span>}
            </li>
          ))}
        </ul>
      )}

      {canManage && rows.length > 0 && activities.length > 0 && (
        <NewSegment
          activities={activities.filter((a) => a.is_active)}
          date={filters.date}
          employees={rows.filter((r) => picked.has(r.employee_code))}
          onDone={done}
          onError={fail}
        />
      )}

      {state.loading && <p className="muted">Cargando…</p>}
      {!state.loading && data && rows.length === 0 && <p className="empty">No hay agentes con esos filtros.</p>}

      <div className="planner">
        {rows.map((r) => (
          <article key={r.employee_code} className="planner__row">
            <div className="planner__who">
              {canManage && (
                <input type="checkbox" checked={picked.has(r.employee_code)} onChange={() => toggle(r.employee_code)}
                  aria-label={`Elegir a ${r.full_name}`} disabled={r.containers.length === 0} />
              )}
              <div>
                <strong>{r.full_name}</strong>
                <span className="muted small">
                  {r.employee_code}
                  {r.containers.map((c) => ` · ${hhmm(c.start)}–${hhmm(c.end)}`).join("")}
                </span>
              </div>
            </div>
            <Timeline
              start={range.start}
              end={range.end}
              lanes={[
                {
                  key: "plan",
                  blocks: [
                    ...r.containers.map((c, i) => ({ key: `c${i}`, start: c.start, end: c.end, color: "transparent", label: "", variant: "container",
                      title: `Contenedor ${c.label}: ${hhmm(c.start)}–${hhmm(c.end)}` })),
                    ...r.plan.map((b, i) => ({
                      key: `p${i}`, start: b.start, end: b.end, color: b.color, label: b.source === "SEGMENT" ? b.activity_name : "",
                      variant: b.source === "SEGMENT" ? "segment" : "fill",
                      title: `${b.activity_name} · ${hhmm(b.start)}–${hhmm(b.end)} (${b.minutes} min)${b.source === "CONTAINER" ? " · actividad predeterminada" : ""}`,
                      selected: selected?.id === b.segment_id && b.source === "SEGMENT",
                      onClick: canManage && b.source === "SEGMENT" ? () => setSelected(r.segments.find((s) => s.id === b.segment_id)) : undefined,
                    })),
                  ],
                },
              ]}
            />
            {r.warnings.length > 0 && (
              <ul className="msg-list msg-list--warn planner__warnings">
                {r.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}
            {selected && r.segments.some((s) => s.id === selected.id) && (
              <EditSegment key={selected.id} segment={selected} activities={activities} onDone={done} onError={fail} onCancel={() => setSelected(null)} />
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

function NewSegment({ activities, date, employees, onDone, onError }) {
  const first = activities.find((a) => !a.is_default) ?? activities[0];
  const [form, setForm] = useState({ activity: first?.code ?? "", start: "10:00", end: addMinutes("10:00", first?.default_minutes ?? 15), date_to: "", notes: "" });
  const [busy, setBusy] = useState(false);
  const setActivity = (code) => {
    const a = activities.find((x) => x.code === code);
    setForm((f) => ({ ...f, activity: code, end: a?.default_minutes ? addMinutes(f.start, a.default_minutes) : f.end }));
  };
  const setStart = (start) => {
    const a = activities.find((x) => x.code === form.activity);
    setForm((f) => ({ ...f, start, end: a?.default_minutes ? addMinutes(start, a.default_minutes) : f.end }));
  };
  const submit = (e) => {
    e.preventDefault();
    if (employees.length === 0) return;
    setBusy(true);
    const payload = { activity: form.activity, start: form.start, end: form.end, notes: form.notes };
    const single = employees.length === 1 && (!form.date_to || form.date_to === date);
    const call = single
      ? adhApi.createSegment({ ...payload, employee_code: employees[0].employee_code, shift_date: date })
      : adhApi.bulkSegments({ ...payload, employee_codes: employees.map((x) => x.employee_code), date_from: date, date_to: form.date_to || date });
    call.then(onDone).catch(onError).finally(() => setBusy(false));
  };
  return (
    <form className="form-section adh-new" onSubmit={submit}>
      <h2 className="form-section__title">Programar segmento</h2>
      <p className="form-section__desc">
        {employees.length === 0
          ? "Marque uno o varios agentes en la lista."
          : `Para ${employees.length} agente(s): ${employees.map((x) => x.full_name).join(", ")}.`}
      </p>
      <div className="adh-new__grid">
        <label className="field">
          <span className="field__label">Actividad</span>
          <select value={form.activity} onChange={(e) => setActivity(e.target.value)}>
            {activities.map((a) => (
              <option key={a.code} value={a.code}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field__label">Inicio</span>
          <input type="time" required value={form.start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label className="field">
          <span className="field__label">Fin</span>
          <input type="time" required value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} />
        </label>
        <label className="field">
          <span className="field__label">Repetir hasta (opcional)</span>
          <input type="date" min={date} value={form.date_to} onChange={(e) => setForm({ ...form, date_to: e.target.value })} />
        </label>
        <label className="field">
          <span className="field__label">Notas</span>
          <input maxLength={200} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        </label>
      </div>
      <div className="form-actions form-actions--start">
        <button type="submit" className="button button--sm" disabled={busy || employees.length === 0}>
          {busy ? "Programando…" : "Programar"}
        </button>
        <span className="muted small">Los días sin turno se omiten; un segmento fuera del turno o traslapado se rechaza con su motivo.</span>
      </div>
    </form>
  );
}

function EditSegment({ segment, activities, onDone, onError, onCancel }) {
  const [form, setForm] = useState({ activity: segment.activity, start: hhmm(segment.start), end: hhmm(segment.end), notes: segment.notes ?? "" });
  const [busy, setBusy] = useState(false);
  const save = (e) => {
    e.preventDefault();
    setBusy(true);
    adhApi.updateSegment(segment.id, form).then(onDone).catch(onError).finally(() => setBusy(false));
  };
  const remove = () => {
    if (!window.confirm(`¿Eliminar ${segment.activity_name} ${hhmm(segment.start)}–${hhmm(segment.end)}?`)) return;
    setBusy(true);
    adhApi.deleteSegment(segment.id).then(onDone).catch(onError).finally(() => setBusy(false));
  };
  return (
    <form className="adh-edit" onSubmit={save}>
      <select value={form.activity} onChange={(e) => setForm({ ...form, activity: e.target.value })} aria-label="Actividad">
        {activities.filter((a) => a.is_active || a.code === segment.activity).map((a) => (
          <option key={a.code} value={a.code}>
            {a.name}
          </option>
        ))}
      </select>
      <input type="time" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} aria-label="Inicio" />
      <input type="time" value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} aria-label="Fin" />
      <input value={form.notes} maxLength={200} placeholder="Notas" onChange={(e) => setForm({ ...form, notes: e.target.value })} aria-label="Notas" />
      <button type="submit" className="button button--sm" disabled={busy}>Guardar</button>
      <button type="button" className="button button--sm button--danger" disabled={busy} onClick={remove}>Eliminar</button>
      <button type="button" className="link-button" onClick={onCancel}>Cerrar</button>
    </form>
  );
}
