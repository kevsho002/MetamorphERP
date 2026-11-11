import { useRoles } from "../hooks/useRoles.js";

/**
 * Bloque del alta de empleado: «¿Desea crear un perfil de usuario Metamorph vinculado a este empleado?».
 * value: { create, role, username }. La cuenta se crea en la MISMA transacción que el empleado.
 */
export default function AccountOptions({ value, onChange, preview, serverErrors = {}, disabled }) {
  const { assignable } = useRoles();
  const set = (patch) => onChange({ ...value, ...patch });
  const usernameError = serverErrors["user_account.username"];
  const roleError = serverErrors["user_account.role"];
  const generalError = serverErrors.user_account;

  return (
    <fieldset className="form-section account-options">
      <legend className="form-section__title">Acceso a Metamorph</legend>
      <label className="checkbox">
        <input
          type="checkbox"
          name="user_account.create"
          checked={value.create}
          onChange={(e) => set({ create: e.target.checked })}
          disabled={disabled}
        />
        <span>
          <strong>¿Desea crear un perfil de usuario Metamorph vinculado a este empleado?</strong>
          <small className="muted">
            La cuenta queda enlazada a su ID corporativo y centro de costos; recibirá una contraseña temporal que deberá
            cambiar en su primer ingreso. Si algo falla, no se crea ni el empleado ni la cuenta.
          </small>
        </span>
      </label>

      {value.create && (
        <div className="form-grid">
          <div className="field">
            <label htmlFor="account-role" className="field__label">
              Rol<span className="field__req">*</span>
            </label>
            <select
              id="account-role"
              name="user_account.role"
              value={value.role}
              onChange={(e) => set({ role: e.target.value })}
              disabled={disabled}
              aria-invalid={Boolean(roleError)}
            >
              {(assignable.length ? assignable : [{ code: "EMPLOYEE", label: "Empleado" }]).map((r) => (
                <option key={r.code} value={r.code}>
                  {r.label}
                </option>
              ))}
            </select>
            {roleError ? (
              <small className="field__error">{roleError}</small>
            ) : (
              <small className="field__hint">Define qué módulos verá. Solo se listan los roles que usted puede otorgar.</small>
            )}
          </div>
          <div className="field">
            <label htmlFor="account-username" className="field__label">
              Usuario
            </label>
            <input
              id="account-username"
              name="user_account.username"
              value={value.username}
              onChange={(e) => set({ username: e.target.value.trim() })}
              placeholder={preview?.username ?? "nombre.apellido"}
              autoComplete="off"
              spellCheck={false}
              maxLength={150}
              disabled={disabled}
              aria-invalid={Boolean(usernameError)}
            />
            {usernameError ? (
              <small className="field__error" role="alert">
                {usernameError}
              </small>
            ) : (
              <small className="field__hint">
                {preview?.username
                  ? `Si lo deja vacío se usará «${preview.username}».`
                  : "Vacío = se genera nombre.apellido (use «Validar sin guardar» para verlo)."}
              </small>
            )}
          </div>
        </div>
      )}
      {generalError && (
        <p className="field__error" role="alert">
          {generalError}
        </p>
      )}
    </fieldset>
  );
}
