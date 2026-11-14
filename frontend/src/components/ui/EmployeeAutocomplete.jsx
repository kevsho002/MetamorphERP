import { useEffect, useId, useRef, useState } from "react";
import { api, toQuery } from "../../services/apiClient.js";

/** Búsqueda general de colaboradores (backend: apps/employees/lookup.py). */
export const employeeLookup = (params, options) => api.get(`/hcm/employee-lookup/${toQuery(params)}`, options);

/**
 * Fase 27 — Selección de colaborador con búsqueda interactiva (autocomplete / typeahead).
 *
 * Reemplaza los campos donde se digitaba el ID corporativo a mano: se escribe parte del nombre, apellido, ID o
 * documento y se elige de la lista (flechas + Enter, o clic). Con un valor elegido muestra el nombre y el ID con
 * «Cambiar» y «Quitar». Si solo se conoce el ID (p. ej. viene en la URL), resuelve el nombre en segundo plano.
 *
 * Props: value (ID corporativo), onChange(code, row), scope ("acd" = solo agentes con membresía ACD activa),
 * inputId (para <label htmlFor>), placeholder, includeTerminated, clearable, fetcher (búsqueda alternativa con la misma
 * respuesta {results, total}).
 */
export default function EmployeeAutocomplete({
  value = "",
  onChange,
  scope,
  inputId,
  placeholder = "Buscar por nombre, ID corporativo o documento…",
  includeTerminated = false,
  clearable = true,
  fetcher = employeeLookup,
  ariaLabel = "Colaborador",
  error,
}) {
  const auto = useId();
  const id = inputId || `emp-${auto}`;
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [state, setState] = useState({ loading: false, results: [], total: 0 });
  const [active, setActive] = useState(0);
  const [known, setKnown] = useState(null); // { employee_code, full_name } del valor actual
  const boxRef = useRef(null);
  const inputRef = useRef(null);

  // Nombre del valor recibido sin fila (enlace o recarga de la página).
  useEffect(() => {
    if (!value || known?.employee_code === value) return undefined;
    const controller = new AbortController();
    fetcher({ q: value, scope, terminated: 1, limit: 5 }, { signal: controller.signal })
      .then((d) => setKnown(d.results.find((r) => r.employee_code === value) ?? { employee_code: value, full_name: null }))
      .catch(() => {});
    return () => controller.abort();
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!open) return undefined;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setState((s) => ({ ...s, loading: true }));
      fetcher({ q: query, scope, terminated: includeTerminated ? 1 : undefined }, { signal: controller.signal })
        .then((d) => {
          setState({ loading: false, results: d.results, total: d.total });
          setActive(0);
        })
        .catch((err) => err.name !== "AbortError" && setState({ loading: false, results: [], total: 0 }));
    }, 200);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query, open, scope, includeTerminated, fetcher]);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (boxRef.current && !boxRef.current.contains(e.target)) {
        setOpen(false);
        setEditing(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const choose = (row) => {
    setKnown(row);
    onChange(row.employee_code, row);
    setOpen(false);
    setEditing(false);
    setQuery("");
  };
  const startEditing = () => {
    setEditing(true);
    setOpen(true);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  };
  const onKey = (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(i + 1, state.results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault(); // nunca envía el formulario con un texto a medio escribir
      if (open && state.results[active]) choose(state.results[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
      if (value) setEditing(false);
    }
  };

  if (value && !editing) {
    const name = known?.employee_code === value ? known.full_name : null;
    return (
      <div className="emp-picker" ref={boxRef}>
        <div className="emp-picker__selected">
          <span className="emp-picker__chosen">
            <strong>{name ?? value}</strong> {name && <span className="muted small">{value}</span>}
          </span>
          <span className="emp-picker__actions">
            <button type="button" id={id} className="link-button small" onClick={startEditing} aria-label={`Cambiar ${ariaLabel.toLowerCase()}`}>
              Cambiar
            </button>
            {clearable && (
              <button type="button" className="link-button small" onClick={() => onChange("", null)} aria-label={`Quitar ${ariaLabel.toLowerCase()}`}>
                Quitar
              </button>
            )}
          </span>
        </div>
        {error && <small className="field__error">{error}</small>}
      </div>
    );
  }

  return (
    <div className="emp-picker" ref={boxRef}>
      <input
        ref={inputRef}
        id={id}
        className="emp-picker__input"
        type="search"
        role="combobox"
        aria-label={inputId ? undefined : ariaLabel}
        aria-expanded={open}
        aria-controls={`${id}-list`}
        aria-autocomplete="list"
        aria-activedescendant={open && state.results[active] ? `${id}-opt-${active}` : undefined}
        placeholder={placeholder}
        value={query}
        autoComplete="off"
        spellCheck={false}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onKeyDown={onKey}
      />
      {open && (
        <ul className="emp-picker__list" id={`${id}-list`} role="listbox" aria-label="Colaboradores">
          {state.loading && state.results.length === 0 && <li className="emp-picker__empty">Buscando…</li>}
          {!state.loading && state.results.length === 0 && <li className="emp-picker__empty">Ningún colaborador coincide.</li>}
          {state.results.map((r, i) => (
            <li key={r.employee_code} id={`${id}-opt-${i}`} role="option" aria-selected={i === active} className="emp-picker__option"
              onMouseDown={(e) => { e.preventDefault(); choose(r); }} onMouseEnter={() => setActive(i)}>
              <span className="emp-picker__name">{r.full_name}</span>
              <span className="emp-picker__tag">{r.status !== "ACTIVE" ? r.status_label : r.country}</span>
              <span className="emp-picker__meta">
                {r.employee_code} · {r.cost_center ?? "sin centro de costos"}
              </span>
            </li>
          ))}
          {state.total > state.results.length && (
            <li className="emp-picker__empty">{state.total - state.results.length} más: afine la búsqueda.</li>
          )}
        </ul>
      )}
      {error && <small className="field__error">{error}</small>}
    </div>
  );
}
