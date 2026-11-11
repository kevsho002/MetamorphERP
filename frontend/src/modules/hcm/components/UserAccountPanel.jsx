import { useState } from "react";
import { useAuth } from "../../../auth/AuthContext.jsx";
import { usersApi } from "../../../services/usersApi.js";
import { employeesApi } from "../api.js";
import { useRoles } from "../hooks/useRoles.js";
import { formatDateTime } from "../lib/format.js";
import AccountSearch from "./AccountSearch.jsx";
import TemporaryPassword from "./TemporaryPassword.jsx";

/**
 * Cuenta Metamorph vinculada al empleado (FK por ID corporativo): crearla si no existe (o, Fase 7,
 * vincular una cuenta existente sin empleado),
 * cambiar rol, resetear contraseña y activar/desactivar. Toda la gestión de cuentas
 * ocurre aquí (no en /admin/), con las reglas RBAC del backend.
 */
export default function UserAccountPanel({ employee, onChanged }) {
  const { user: me, hasPermission } = useAuth();
  const { assignable } = useRoles();
  const account = employee.user_account;
  const [form, setForm] = useState({ role: "EMPLOYEE", username: "" });
  const [linkUser, setLinkUser] = useState(null); // Fase 7: cuenta existente elegida para vincular
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [message, setMessage] = useState(null);
  const [secret, setSecret] = useState(null); // {username, password}
  const isSelf = account && me?.id === account.id;
  const canManageThis = account && assignable.some((r) => r.code === account.role) && !isSelf;
  const retired = employee.employment_status === "TERMINATED";

  const run = async (label, fn) => {
    setBusy(label);
    setError(null);
    setMessage(null);
    try {
      await fn();
    } catch (err) {
      setError(err.body?.errors?.map((e) => e.message).join(" ") || err.message);
    } finally {
      setBusy(null);
    }
  };

  const create = () =>
    run("create", async () => {
      const body = await employeesApi.createUserAccount(employee.employee_code, {
        role: form.role,
        username: form.username || undefined,
      });
      setSecret({ username: body.user_account.username, password: body.user_account.temporary_password });
      setMessage([body.feedback, ...(body.warnings ?? []).map((w) => w.message)].join(" "));
      onChanged();
    });

  const link = () =>
    run("link", async () => {
      const body = await employeesApi.linkUserAccount(employee.employee_code, linkUser.id);
      setLinkUser(null);
      setMessage([body.feedback, ...(body.warnings ?? []).map((w) => w.message)].join(" "));
      onChanged();
    });

  const resetPassword = () => {
    if (!window.confirm(`¿Generar una contraseña temporal nueva para «${account.username}»? Se cerrarán sus sesiones abiertas.`)) return;
    run("reset", async () => {
      const body = await usersApi.resetPassword(account.id);
      setSecret({ username: body.username, password: body.temporary_password });
      setMessage("Contraseña reseteada. El usuario deberá cambiarla al ingresar.");
      onChanged();
    });
  };

  const changeRole = (role) =>
    run("role", async () => {
      await usersApi.assignRole(account.id, role);
      setMessage("Rol actualizado.");
      onChanged();
    });

  const toggleActive = () => {
    const verb = account.is_active ? "desactivar" : "reactivar";
    if (!window.confirm(`¿Desea ${verb} la cuenta «${account.username}»?`)) return;
    run("active", async () => {
      await (account.is_active ? usersApi.deactivate(account.id) : usersApi.activate(account.id));
      setMessage(`Cuenta ${account.is_active ? "desactivada; sus sesiones se cerraron" : "reactivada"}.`);
      onChanged();
    });
  };

  return (
    <section aria-labelledby="account-title">
      <h2 id="account-title" className="section-title">
        Cuenta Metamorph
      </h2>
      {secret && <TemporaryPassword username={secret.username} password={secret.password} onDismiss={() => setSecret(null)} />}
      {message && <p className="alert alert--ok">{message}</p>}
      {error && (
        <p className="alert alert--error" role="alert">
          {error}
        </p>
      )}

      {account ? (
        <>
          <dl className="detail-grid">
            <div className="detail-item">
              <dt>Usuario</dt>
              <dd>
                <code>{account.username}</code>
              </dd>
            </div>
            <div className="detail-item">
              <dt>Rol</dt>
              <dd>
                {canManageThis && hasPermission("users.assign_role") ? (
                  <select value={account.role} onChange={(e) => changeRole(e.target.value)} disabled={Boolean(busy)} aria-label="Rol">
                    {assignable.map((r) => (
                      <option key={r.code} value={r.code}>
                        {r.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  account.role_label
                )}
              </dd>
            </div>
            <div className="detail-item">
              <dt>Estado</dt>
              <dd>
                <span className={`badge badge--${account.is_active ? "ok" : "muted"}`}>{account.is_active ? "Activa" : "Desactivada"}</span>
                {account.must_change_password && <span className="tag tag--warn">Cambio de contraseña pendiente</span>}
              </dd>
            </div>
            <div className="detail-item">
              <dt>Correo</dt>
              <dd>{account.email ?? <span className="muted">—</span>}</dd>
            </div>
            <div className="detail-item">
              <dt>Último ingreso</dt>
              <dd>{account.last_login ? formatDateTime(account.last_login) : <span className="muted">Nunca</span>}</dd>
            </div>
          </dl>
          {isSelf && <p className="muted small">Es su propia cuenta: los cambios de rol o estado los hace otro administrador.</p>}
          {account && !canManageThis && !isSelf && (
            <p className="muted small">Su rol no administra cuentas con el rol {account.role_label}.</p>
          )}
          {canManageThis && (
            <div className="actions">
              {hasPermission("users.reset_password") && (
                <button type="button" className="button button--ghost button--sm" onClick={resetPassword} disabled={Boolean(busy)}>
                  {busy === "reset" ? "Generando…" : "Resetear contraseña"}
                </button>
              )}
              {hasPermission("users.deactivate") && (
                <button
                  type="button"
                  className={`button button--sm ${account.is_active ? "button--danger" : "button--success"}`}
                  onClick={toggleActive}
                  disabled={Boolean(busy)}
                >
                  {account.is_active ? "Desactivar cuenta" : "Reactivar cuenta"}
                </button>
              )}
            </div>
          )}
        </>
      ) : employee.has_user_account ? (
        <p className="muted">El empleado tiene una cuenta vinculada (su rol no permite ver el detalle).</p>
      ) : retired ? (
        <p className="muted">El empleado está terminado: no se le crea ni vincula acceso.</p>
      ) : !hasPermission("users.create") && !hasPermission("users.update") ? (
        <p className="muted">El empleado no tiene cuenta de usuario.</p>
      ) : (
        <>
        {hasPermission("users.create") && (
        <div className="form-section">
          <p>
            El empleado no tiene cuenta. ¿Desea crear un perfil de usuario Metamorph vinculado a <code>{employee.employee_code}</code>?
          </p>
          <div className="form-grid">
            <div className="field">
              <label htmlFor="new-account-role" className="field__label">
                Rol
              </label>
              <select id="new-account-role" value={form.role} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}>
                {assignable.map((r) => (
                  <option key={r.code} value={r.code}>
                    {r.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="new-account-username" className="field__label">
                Usuario (opcional)
              </label>
              <input
                id="new-account-username"
                value={form.username}
                onChange={(e) => setForm((f) => ({ ...f, username: e.target.value.trim() }))}
                placeholder="nombre.apellido"
                autoComplete="off"
                spellCheck={false}
              />
              <small className="field__hint">Vacío = se genera a partir del nombre.</small>
            </div>
          </div>
          <button type="button" className="button" onClick={create} disabled={Boolean(busy)}>
            {busy === "create" ? "Creando…" : "Crear cuenta vinculada"}
          </button>
        </div>
        )}
        {hasPermission("users.update") && (
          <div className="form-section">
            <p>
              ¿Ya tiene una cuenta Metamorph? Vincúlela a <code>{employee.employee_code}</code>: conserva su usuario, contraseña y
              rol, y toma el centro de costos del empleado.
            </p>
            <div className="form-grid">
              <AccountSearch id="link-account-search" value={linkUser} onChange={setLinkUser} disabled={Boolean(busy)} />
            </div>
            <button type="button" className="button button--ghost" onClick={link} disabled={Boolean(busy) || !linkUser}>
              {busy === "link" ? "Vinculando…" : "Vincular cuenta existente"}
            </button>
          </div>
        )}
        </>
      )}
    </section>
  );
}
