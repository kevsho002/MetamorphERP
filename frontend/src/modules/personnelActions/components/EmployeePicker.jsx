import { useEffect, useId, useRef, useState } from "react";
import { actionsApi } from "../api.js";

const RELATION = { DIRECT: "Directo", INDIRECT: "Indirecto" };

/**
 * Fase 23 — Selector inteligente de colaboradores (typeahead) para elaborar AP. Solo ofrece a quienes están bajo la
 * jerarquía directa o indirecta del usuario (o a toda la organización si su rol lo permite); el servidor valida lo mismo.
 */
export default function EmployeePicker({ value, selected, onChange, includeTerminated = false, error }) {
  const id = useId();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [state, setState] = useState({ loading: false, results: [], total: 0, scope: null, label: "" });
  const [active, setActive] = useState(0);
  const boxRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setState((s) => ({ ...s, loading: true }));
      actionsApi
        .picker({ q: query, terminated: includeTerminated ? 1 : undefined }, { signal: controller.signal })
        .then((d) => {
          setState({ loading: false, results: d.results, total: d.total, scope: d.scope, label: d.scope_label });
          setActive(0);
        })
        .catch((err) => err.name !== "AbortError" && setState((s) => ({ ...s, loading: false, results: [] })));
    }, 220);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query, open, includeTerminated]);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => boxRef.current && !boxRef.current.contains(e.target) && setOpen(false);
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const choose = (row) => {
    onChange(row.employee_code, row);
    setOpen(false);
    setQuery("");
  };
  const onKey = (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(i + 1, state.results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" && open && state.results[active]) {
      e.preventDefault();
      choose(state.results[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  if (value && !open) {
    return (
      <div className="emp-picker" ref={boxRef}>
        <div className="emp-picker__selected">
          <span>
            <strong>{selected?.full_name ?? value}</strong> <span className="muted small">{value}</span>
          </span>
          <button type="button" className="link-button small" onClick={() => { setOpen(true); window.setTimeout(() => inputRef.current?.focus(), 0); }}>
            Cambiar
          </button>
        </div>
        {error && <small className="field__error">{error}</small>}
      </div>
    );
  }

  return (
    <div className="emp-picker" ref={boxRef}>
      <input
        ref={inputRef}
        id={`${id}-input`}
        className="emp-picker__input"
        type="search"
        role="combobox"
        aria-expanded={open}
        aria-controls={`${id}-list`}
        aria-autocomplete="list"
        aria-activedescendant={open && state.results[active] ? `${id}-opt-${active}` : undefined}
        placeholder="Buscar por nombre, ID corporativo o documento…"
        value={query}
        autoComplete="off"
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onKeyDown={onKey}
      />
      {open && (
        <ul className="emp-picker__list" id={`${id}-list`} role="listbox" aria-label="Colaboradores de su jerarquía">
          {state.loading && state.results.length === 0 && <li className="emp-picker__empty">Buscando…</li>}
          {!state.loading && state.results.length === 0 && (
            <li className="emp-picker__empty">
              {state.scope === "hierarchy" && !query ? "No tiene colaboradores bajo su jerarquía." : "Ningún colaborador de su jerarquía coincide."}
            </li>
          )}
          {state.results.map((r, i) => (
            <li key={r.employee_code} id={`${id}-opt-${i}`} role="option" aria-selected={i === active} className="emp-picker__option"
              onMouseDown={(e) => { e.preventDefault(); choose(r); }} onMouseEnter={() => setActive(i)}>
              <span className="emp-picker__name">{r.full_name}</span>
              <span className="emp-picker__tag">{r.relation ? RELATION[r.relation] : r.status !== "ACTIVE" ? r.status_label : r.country}</span>
              <span className="emp-picker__meta">
                {r.employee_code} · {r.cost_center ?? "sin centro de costos"}
                {r.status !== "ACTIVE" ? ` · ${r.status_label}` : ""}
              </span>
            </li>
          ))}
          {state.total > state.results.length && (
            <li className="emp-picker__empty">
              {state.total - state.results.length} más: afine la búsqueda.
            </li>
          )}
          {state.label && <li className="emp-picker__empty small">Alcance: {state.label}.</li>}
        </ul>
      )}
      {error && <small className="field__error">{error}</small>}
    </div>
  );
}
