import { useAuth } from "../../../auth/AuthContext.jsx";
import { useRoles } from "../hooks/useRoles.js";
import AccountSearch from "./AccountSearch.jsx";
import FieldHint from "../../../components/ui/FieldHint.jsx";

/**
 * Bloque del alta de empleado: «¿Desea crear un perfil de usuario Metamorph vinculado a este empleado?».
 * value: { create, mode: "create" | "link", role, username, user }.
 *  - create: cuenta NUEVA con contraseña temporal (requiere users.create).
 *  - link (Fase 7): vincula una cuenta EXISTENTE sin empleado (requiere users.update); conserva su contraseña y rol.
 * En ambos casos todo ocurre en la MISMA transacción que el alta del empleado.
 */
export default function AccountOptions({ value, onChange, preview, serverErrors = {}, disabled }) {
  const { hasPermission } = useAuth();
  const { assignable } = useRoles();
  const canCreate = hasPermission("users.create");
  const canLink = hasPermission("users.update");
  const set = (patch) => onChange({ ...value, ...patch });
  const mode = value.mode === "link" && canLink ? "link" : canCreate ? "create" : "link";
  const usernameError = serverErrors["user_account.username"];
  const roleError = serverErrors["user_account.role"];
  const userError = serverErrors["user_account.user_id"];
  const generalError = serverErrors.user_account;

  return (
    <fieldset className="form-section account-options">
      <legend className="form-section__title">Acceso a Metamorph</legend>
      <label className="checkbox">
        <input
          type="checkbox"
          name="user_account.create"
          checked={value.create}
          onChange={(e) => set({ create: e.target.checked, mode })}
          disabled={disabled}
        />
        <span>
          <strong>¿Desea crear un perfil de usuario Metamorph vinculado a este empleado?</strong>
          <small className="muted">
            Puede crear una cuenta nueva o vincular una cuenta que ya existe en el sistema. La cuenta queda enlazada a su
            ID corporativo y centro de costos. Si algo falla, no se registra ni el empleado ni el vínculo.
          </small>
        </span>
      </label>

      {value.create && canCreate && canLink && (
        <div className="segmented" role="radiogroup" aria-label="Tipo de vínculo">
          <label className={`segmented__item${mode === "create" ? " segmented__item--active" : ""}`}>
            <input type="radio" name="user_account.mode" value="create" checked={mode === "create"} onChange={() => set({ mode: "create" })} disabled={disabled} />
            Crear una cuenta nueva
          </label>
          <label className={`segmented__item${mode === "link" ? " segmented__item--active" : ""}`}>
            <input type="radio" name="user_account.mode" value="link" checked={mode === "link"} onChange={() => set({ mode: "link" })} disabled={disabled} />
            Vincular una cuenta existente
          </label>
        </div>
      )}

      {value.create && mode === "link" && (
        <div className="form-grid">
          <AccountSearch value={value.user} onChange={(user) => set({ user, mode: "link" })} error={userError} disabled={disabled} />
        </div>
      )}

      {value.create && mode === "create" && (
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
              <FieldHint>Define qué módulos verá. Solo se listan los roles que usted puede otorgar.</FieldHint>
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
              <FieldHint>
                {preview?.username && !preview.linked
                  ? `Si lo deja vacío se usará «${preview.username}».`
                  : "Vacío = se genera nombre.apellido (use «Validar sin guardar» para verlo)."}
              </FieldHint>
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

/** Cuerpo `user_account` para la API según la opción elegida (o null si no se pidió cuenta). */
export function accountPayload(value, { canCreate, canLink }) {
  if (!value.create) return null;
  const mode = value.mode === "link" && canLink ? "link" : canCreate ? "create" : "link";
  if (mode === "link") return { mode: "link", user_id: value.user?.id ?? null };
  return { create: true, role: value.role, username: value.username };
}
