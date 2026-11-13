import { useState } from "react";
import { useClientConfig } from "../app/ClientConfigContext.jsx";
import { ThemedLogo } from "../components/ui/Brand.jsx";
import { useAuth } from "./AuthContext.jsx";

export default function LoginPage() {
  const { login, notice } = useAuth();
  const { config } = useClientConfig();
  const [form, setForm] = useState({ username: "", password: "" });
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const onChange = (e) => setForm((f) => ({ ...f, [e.target.name]: e.target.value }));

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
    <main className="auth-screen">
      <form className="card auth-card" onSubmit={onSubmit} noValidate>
        <h1 className="page-title auth-brand">
          <ThemedLogo />
          <span className="sr-only">Metamorph ERP</span>
        </h1>
        <p className="muted">Inicie sesión con su usuario corporativo.</p>
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
        <label className="field">
          <span>Usuario</span>
          <input name="username" autoComplete="username" value={form.username} onChange={onChange} required autoFocus />
        </label>
        <label className="field">
          <span>Contraseña</span>
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            value={form.password}
            onChange={onChange}
            required
          />
        </label>
        {error && (
          <p className="error-box" role="alert">
            {error}
          </p>
        )}
        <button type="submit" className="button button--block" disabled={submitting || !form.username || !form.password}>
          {submitting ? "Ingresando…" : "Ingresar"}
        </button>
      </form>
    </main>
  );
}
