import { RouterProvider } from "react-router-dom";
import { ClientConfigProvider, useClientConfig } from "./app/ClientConfigContext.jsx";
import { router } from "./app/router.jsx";
import { AuthProvider, useAuth } from "./auth/AuthContext.jsx";
import ChangePasswordPage from "./auth/ChangePasswordPage.jsx";
import LoginPage from "./auth/LoginPage.jsx";

/** Mantenimiento programado: solo los administradores siguen operando. */
function MaintenanceScreen() {
  const { config } = useClientConfig();
  const { user, logout } = useAuth();
  return (
    <main className="auth-screen">
      <section className="card auth-card" role="alert">
        <h1 className="page-title">Sistema en mantenimiento</h1>
        <p>{config.maintenance_message || "Metamorph ERP está en mantenimiento. Intente más tarde."}</p>
        <p className="muted small">Sesión de {user?.display_name}. Puede cerrar sesión y volver más tarde.</p>
        <button type="button" className="button button--block" onClick={() => logout()}>
          Cerrar sesión
        </button>
      </section>
    </main>
  );
}

function AuthGate() {
  const { status, user, isAdmin } = useAuth();
  const { config } = useClientConfig();
  if (status === "loading") return <main className="auth-screen muted">Cargando…</main>;
  if (status === "anonymous") return <LoginPage />;
  if (config.maintenance_mode && !isAdmin) return <MaintenanceScreen />;
  if (user?.must_change_password) return <ChangePasswordPage />;
  return <RouterProvider router={router} />;
}

export default function App() {
  return (
    <ClientConfigProvider>
      <AuthProvider>
        <AuthGate />
      </AuthProvider>
    </ClientConfigProvider>
  );
}
