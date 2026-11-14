import { useState } from "react";
import { useClientConfig } from "../app/ClientConfigContext.jsx";
import AuthShell from "./AuthShell.jsx";
import { useAuth } from "./AuthContext.jsx";

/** Fase 26 — Inicio de sesión rediseñado (panel de marca + formulario con campos de línea inferior). */
export default function LoginPage() {
  const { login, notice } = useAuth();
  const { config } = useClientConfig();
  const [form, setForm] = useState({ username: "", password: "" });
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);

  const onChange = (e) => setForm((f) => ({ ...f, [e.target.name]: e.target.value }));
  const onKey = (e) => setCapsLock(Boolean(e.getModifierState?.("CapsLock")));

  async function onSubmit(e) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(form.username.trim(), form.password);
    } catch (err) {
      setError(err.status === 429 ? "Demasiados intentos. Espere un minuto e intente de nuevo." : err.message);
      setForm((f) => ({ ...f, password: "" }));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthShell>
      <form className="auth-form" onSubmit={onSubmit} noValidate>
        <header className="auth-form__head">
          <h1 className="auth-form__title">¡Bienvenido de nuevo!</h1>
          <p className="auth-form__sub">Inicie sesión con su usuario corporativo para continuar.</p>
        </header>
        {config.maintenance_mode && (
          <p className="alert alert--warn" role="status">
            {config.maintenance_message || "El sistema está en mantenimiento."} Solo los administradores pueden ingresar.
          </p>
        )}
        {notice && !error && (
          <p className="alert alert--warn" role="status">
            {notice}
          </p>
        )}
        <label className="line-field">
          <span className="line-field__label">Usuario</span>
          <input name="username" autoComplete="username" value={form.username} onChange={onChange} placeholder="nombre.apellido"
            required autoFocus spellCheck={false} autoCapitalize="none" />
        </label>
        <label className="line-field">
          <span className="line-field__label">Contraseña</span>
          <span className="line-field__row">
            <input name="password" type={showPassword ? "text" : "password"} autoComplete="current-password" value={form.password}
              onChange={onChange} onKeyUp={onKey} onKeyDown={onKey} placeholder="••••••••••••" required />
            <button type="button" className="line-field__toggle" onClick={() => setShowPassword((v) => !v)}
              aria-label={showPassword ? "Ocultar contraseña" : "Mostrar contraseña"} aria-pressed={showPassword}>
              {showPassword ? "Ocultar" : "Mostrar"}
            </button>
          </span>
        </label>
        {capsLock && <p className="auth-form__caps" role="status">Bloq Mayús está activado.</p>}
        {error && (
          <p className="error-box" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="auth-form__submit" disabled={submitting || !form.username || !form.password}>
          {submitting ? "Ingresando…" : "Ingresar"}
        </button>
        <p className="auth-form__help">
          ¿Olvidó su contraseña? <strong>Contacte a Recursos Humanos.</strong>
        </p>
      </form>
    </AuthShell>
  );
}
