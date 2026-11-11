import { Link } from "react-router-dom";
import { useAuth } from "./AuthContext.jsx";

/**
 * Protege una ruta según la matriz RBAC (/auth/me -> permissions).
 * Es solo experiencia de usuario: la autorización real la aplica la API (403).
 */
export default function RequirePermission({ permission, children }) {
  const { hasPermission } = useAuth();
  if (hasPermission(permission)) return children;
  return (
    <section className="card">
      <h1 className="page-title">Acceso restringido</h1>
      <p className="muted">Su rol no tiene permiso para esta sección. Si lo necesita, solicítelo a un administrador.</p>
      <Link className="button button--ghost" to="/">
        Volver al inicio
      </Link>
    </section>
  );
}
