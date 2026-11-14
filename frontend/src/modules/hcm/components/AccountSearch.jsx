import { useEffect, useState } from "react";
import { employeesApi } from "../api.js";
import FieldHint from "../../../components/ui/FieldHint.jsx";

/**
 * Buscador de cuentas Metamorph EXISTENTES sin empleado vinculado (Fase 7).
 * Solo lista las cuentas cuyo rol puede administrar el usuario actual (lo filtra el backend).
 * value: cuenta seleccionada {id, username, role_label, ...} | null.
 */
export default function AccountSearch({ value, onChange, error, disabled, id = "account-search" }) {
  const [search, setSearch] = useState("");
  const [state, setState] = useState({ loading: false, results: [], error: null });

  useEffect(() => {
    if (value) return undefined;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setState((s) => ({ ...s, loading: true, error: null }));
      employeesApi
        .accountCandidates(search.trim(), { signal: controller.signal })
        .then((body) => setState({ loading: false, results: body.results ?? [], error: null }))
        .catch((err) => err.name !== "AbortError" && setState({ loading: false, results: [], error: err.message }));
    }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [search, value]);

  if (value) {
    return (
      <div className="account-pick">
        <p>
          <strong>{value.username}</strong> · {value.role_label}
          {value.full_name ? ` · ${value.full_name}` : ""}
          {!value.is_active && <span className="badge badge--muted">Desactivada</span>}
        </p>
        <button type="button" className="button button--ghost button--sm" onClick={() => onChange(null)} disabled={disabled}>
          Cambiar cuenta
        </button>
        {error && (
          <small className="field__error" role="alert">
            {error}
          </small>
        )}
      </div>
    );
  }

  return (
    <div className="field account-search">
      <label htmlFor={id} className="field__label">
        Buscar cuenta existente<span className="field__req">*</span>
      </label>
      <input
        id={id}
        type="search"
        name="user_account.user_id"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Usuario, nombre o correo"
        autoComplete="off"
        disabled={disabled}
        aria-invalid={Boolean(error)}
      />
      {error ? (
        <small className="field__error" role="alert">
          {error}
        </small>
      ) : (
        <FieldHint>Solo cuentas sin empleado vinculado y con un rol que usted puede administrar.</FieldHint>
      )}
      {state.error && <p className="field__error">No se pudo buscar: {state.error}</p>}
      <ul className="account-search__results" aria-busy={state.loading}>
        {state.results.map((u) => (
          <li key={u.id}>
            <button type="button" className="account-search__item" onClick={() => onChange(u)} disabled={disabled}>
              <strong>{u.username}</strong>
              <span className="muted small">
                {u.role_label}
                {u.full_name ? ` · ${u.full_name}` : ""}
                {u.email ? ` · ${u.email}` : ""}
                {!u.is_active ? " · desactivada" : ""}
              </span>
            </button>
          </li>
        ))}
        {!state.loading && state.results.length === 0 && <li className="muted small">No hay cuentas disponibles con ese criterio.</li>}
      </ul>
    </div>
  );
}
