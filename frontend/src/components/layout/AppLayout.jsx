import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext.jsx";
import { AgentPresenceProvider } from "../../modules/acd/AgentPresenceContext.jsx";
import AnnouncementBar from "./AnnouncementBar.jsx";
import SessionWatcher from "./SessionWatcher.jsx";
import TimeFormatSelect from "./TimeFormatSelect.jsx";
import Sidebar, { useSidebarPin } from "./Sidebar.jsx";
import UserPresenceMenu from "./UserPresenceMenu.jsx";

const DESKTOP = "(min-width: 900px)";

export default function AppLayout({ modules }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [pinned, togglePin] = useSidebarPin();
  const { hasPermission } = useAuth();
  const location = useLocation();

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
          <span className="topbar__brand">Metamorph ERP</span>
          <TimeFormatSelect />
          <UserPresenceMenu />
        </header>

        <Sidebar modules={visibleModules} hasPermission={hasPermission} pinned={pinned} onTogglePin={togglePin} mobileOpen={menuOpen} />

        <main className="content">
          <AnnouncementBar />
          <Outlet />
        </main>
        <SessionWatcher />
      </div>
    </AgentPresenceProvider>
  );
}
