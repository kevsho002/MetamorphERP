import { useState } from "react";
import { useAuth } from "./AuthContext.jsx";

/** Pantalla obligatoria tras un alta o reseteo administrativo (must_change_password). */
export default function ChangePasswordPage() {
  const { user, changePassword, logout } = useAuth();
  const [form, setForm] = useState({ current: "", next: "", confirm: "" });
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const onChange = (e) => setForm((f) => ({ ...f, [e.target.name]: e.target.value }));
  const mismatch = Boolean(form.confirm) && form.next !== form.confirm;

  async function onSubmit(e) {
    e.preventDefault();
    if (mismatch) return;
    setSubmitting(true);
    setError(null);
    try {
      await changePassword(form.current, form.next);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-screen">
      <form className="card auth-card" onSubmit={onSubmit} noValidate>
        <h1 className="page-title">Cambie su contraseña</h1>
        <p className="muted">
          {user?.display_name}, su contraseña fue asignada por un administrador. Defina una nueva para continuar
          (mínimo 12 caracteres; no puede ser solo numérica ni una contraseña común).
        </p>
        <label className="field">
          <span>Contraseña actual (temporal)</span>
          <input name="current" type="password" autoComplete="current-password" value={form.current} onChange={onChange} />
        </label>
        <label className="field">
          <span>Nueva contraseña</span>
          <input name="next" type="password" autoComplete="new-password" minLength={12} value={form.next} onChange={onChange} />
        </label>
        <label className="field">
          <span>Confirmar nueva contraseña</span>
          <input name="confirm" type="password" autoComplete="new-password" value={form.confirm} onChange={onChange} />
        </label>
        {mismatch && <p className="error-box">Las contraseñas no coinciden.</p>}
        {error && (
          <p className="error-box" role="alert">
            {error}
          </p>
        )}
        <button
          type="submit"
          className="button button--block"
          disabled={submitting || !form.current || !form.next || mismatch}
        >
          {submitting ? "Guardando…" : "Guardar y continuar"}
        </button>
        <button type="button" className="button button--ghost button--block" onClick={logout}>
          Cerrar sesión
        </button>
      </form>
    </main>
  );
}
