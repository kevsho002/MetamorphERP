import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext.jsx";
import AnnouncementBar from "./AnnouncementBar.jsx";
import SessionWatcher from "./SessionWatcher.jsx";

export default function AppLayout({ modules }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const { user, logout, hasPermission } = useAuth();
  const location = useLocation();

  // En móvil, el menú se cierra al navegar.
  useEffect(() => setMenuOpen(false), [location.pathname]);

  // El menú refleja la matriz RBAC; la autorización real la aplica la API.
  const visibleModules = modules.filter((m) => hasPermission(m.permission));

  return (
    <div className="shell">
      <header className="topbar">
        <button
          type="button"
          className="topbar__menu"
          aria-label="Abrir menú"
          aria-expanded={menuOpen}
          aria-controls="sidebar"
          onClick={() => setMenuOpen((v) => !v)}
        >
          ☰
        </button>
        <span className="topbar__brand">Metamorph ERP</span>
        <span className="topbar__user" title={user?.employee_code ?? undefined}>
          {user?.display_name} · {user?.role_label}
        </span>
        <button type="button" className="topbar__logout" onClick={() => logout()}>
          Salir
        </button>
      </header>

      <nav id="sidebar" className={`sidebar${menuOpen ? " sidebar--open" : ""}`} aria-label="Módulos">
        {visibleModules.map((m) => (
          <section key={m.id} className="sidebar__group">
            <h2 className="sidebar__title">{m.label}</h2>
            {m.menu
              .filter((item) => hasPermission(item.permission))
              .map((item) => (
              <NavLink key={item.to} to={item.to} end={item.end} className="sidebar__link">
                {item.label}
              </NavLink>
              ))}
          </section>
        ))}
        {visibleModules.length === 0 && <p className="muted">Su rol aún no tiene módulos habilitados.</p>}
      </nav>

      <main className="content">
        <AnnouncementBar />
        <Outlet />
      </main>
      <SessionWatcher />
    </div>
  );
}
