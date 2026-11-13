import { useEffect, useRef, useState } from "react";
import { formatDate } from "../../hcm/lib/format.js";

/**
 * Fase 23 — Alta / edición de un feriado desde el calendario (perfiles con payroll.manage). Un feriado que ya generó
 * Holiday Segments no cambia de fecha ni se elimina (SQL 50097): se desactiva.
 */
export default function HolidayEditor({ holiday, date, kinds, canManage, busy, onSave, onDelete, onClose }) {
  const isNew = !holiday;
  const [form, setForm] = useState(() => ({
    date: holiday?.date ?? date ?? "",
    name: holiday?.name ?? "",
    kind: holiday?.kind ?? "NATIONAL",
    premium_percent: holiday ? String(Number(holiday.premium_percent)) : "100",
    legal_reference: holiday?.legal_reference ?? "",
    is_active: holiday?.is_active ?? true,
  }));
  const ref = useRef(null);
  const locked = !isNew && holiday.segments > 0;
  const set = (patch) => setForm((f) => ({ ...f, ...patch }));

  useEffect(() => {
    ref.current?.querySelector("input[name=name]")?.focus();
    const onKey = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="holcal__editor" role="dialog" aria-modal="true" aria-label={isNew ? "Nuevo feriado" : `Feriado ${holiday.name}`}
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form ref={ref} onSubmit={(e) => { e.preventDefault(); onSave(form); }}>
        <h2 className="section-title" style={{ marginTop: 0 }}>
          {isNew ? `Nuevo feriado · ${formatDate(form.date)}` : canManage ? "Editar feriado" : "Feriado"}
        </h2>
        <div className="form-grid">
          <label className="field">
            <span className="field__label">Fecha</span>
            <input type="date" name="date" required value={form.date} disabled={!canManage || locked} onChange={(e) => set({ date: e.target.value })} />
          </label>
          <label className="field">
            <span className="field__label">Tipo</span>
            <select value={form.kind} disabled={!canManage} onChange={(e) => set({ kind: e.target.value })}>
              {kinds.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="field">
          <span className="field__label">Nombre</span>
          <input name="name" required maxLength={120} value={form.name} disabled={!canManage} onChange={(e) => set({ name: e.target.value })} />
        </label>
        <div className="form-grid">
          <label className="field">
            <span className="field__label">Recargo si se labora (%)</span>
            <input type="number" min="0" max="300" step="0.01" value={form.premium_percent} disabled={!canManage}
              onChange={(e) => set({ premium_percent: e.target.value })} />
          </label>
          <label className="checkbox" style={{ alignSelf: "end" }}>
            <input type="checkbox" checked={form.is_active} disabled={!canManage} onChange={(e) => set({ is_active: e.target.checked })} /> Activo
          </label>
        </div>
        <label className="field">
          <span className="field__label">Referencia legal</span>
          <input maxLength={200} value={form.legal_reference} disabled={!canManage} onChange={(e) => set({ legal_reference: e.target.value })} />
        </label>
        {locked && (
          <p className="muted small">
            Ya generó {holiday.segments} Holiday Segment(s): la fecha no cambia ni se elimina; puede desactivarlo o ajustar sus datos.
          </p>
        )}
        <div className="form-actions">
          {canManage && !isNew && !locked && (
            <button type="button" className="button button--danger button--sm" disabled={busy}
              onClick={() => window.confirm(`¿Eliminar el feriado «${holiday.name}»?`) && onDelete(holiday)}>
              Eliminar
            </button>
          )}
          <button type="button" className="button button--ghost button--sm" onClick={onClose}>
            {canManage ? "Cancelar" : "Cerrar"}
          </button>
          {canManage && (
            <button type="submit" className="button button--sm" disabled={busy}>
              {busy ? "Guardando…" : isNew ? "Agregar feriado" : "Guardar cambios"}
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
