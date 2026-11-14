import { useEffect, useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext.jsx";
import { AgentPresenceProvider } from "../../modules/acd/AgentPresenceContext.jsx";
import { clearPersonal, loadProfile } from "../../app/appearance.js";
import { AppLogo } from "../ui/Brand.jsx";
import AnnouncementBar from "./AnnouncementBar.jsx";
import SessionWatcher from "./SessionWatcher.jsx";
import NotificationBell from "./NotificationBell.jsx";
import PendingAckBanner from "./PendingAckBanner.jsx";
import Sidebar, { useSidebarPin } from "./Sidebar.jsx";
import UserPresenceMenu from "./UserPresenceMenu.jsx";

const DESKTOP = "(min-width: 900px)";

export default function AppLayout({ modules }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [pinned, togglePin] = useSidebarPin();
  const { hasPermission } = useAuth();
  const location = useLocation();

  // Fase 23: preferencias visuales del perfil (paleta personal, modo, densidad, tiempos).
  useEffect(() => {
    loadProfile();
    return clearPersonal;
  }, []);

  // En móvil, el menú se cierra al navegar.
  useEffect(() => setMenuOpen(false), [location.pathname]);

  // El menú refleja la matriz RBAC; la autorización real la aplica la API.
  const visibleModules = modules.filter((m) => hasPermission(m.permission));
  // ☰: en móvil abre el panel deslizable; en escritorio fija / contrae el menú.
  const onMenuButton = () => (window.matchMedia(DESKTOP).matches ? togglePin() : setMenuOpen((v) => !v));

  return (
    <AgentPresenceProvider>
      <div className={`shell${pinned ? "" : " shell--collapsed"}`}>
        <header className="topbar">
          <button
            type="button"
            className="topbar__menu"
            aria-label="Mostrar u ocultar el menú"
            aria-expanded={menuOpen}
            aria-controls="sidebar"
            onClick={onMenuButton}
          >
            ☰
          </button>
          <Link to="/announcements" className="topbar__brand" aria-label="Metamorph ERP — periódico virtual" title="Periódico virtual">
            <AppLogo />
          </Link>
          <NotificationBell />
          <UserPresenceMenu />
        </header>

        <Sidebar modules={visibleModules} hasPermission={hasPermission} pinned={pinned} onTogglePin={togglePin} mobileOpen={menuOpen} />

        <main className="content">
          <AnnouncementBar />
          <PendingAckBanner />
          <Outlet />
        </main>
        <SessionWatcher />
      </div>
    </AgentPresenceProvider>
  );
}
