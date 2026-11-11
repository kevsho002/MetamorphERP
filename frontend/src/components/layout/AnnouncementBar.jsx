import { useState } from "react";
import { useClientConfig } from "../../app/ClientConfigContext.jsx";

const STORAGE_KEY = "metamorph.dismissedAnnouncement";

function readDismissed() {
  try {
    return window.sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

/** Aviso general configurado en /admin/ (se puede ocultar hasta que cambie el texto). */
export default function AnnouncementBar() {
  const { config } = useClientConfig();
  const [dismissed, setDismissed] = useState(readDismissed);
  const text = config.announcement?.trim();
  if (!text || dismissed === text) return null;

  const dismiss = () => {
    setDismissed(text);
    try {
      window.sessionStorage.setItem(STORAGE_KEY, text);
    } catch {
      // almacenamiento no disponible: se oculta solo en esta vista
    }
  };

  const tone = { info: "info", warning: "warn", danger: "error" }[config.announcement_level] ?? "info";
  return (
    <div className={`announcement announcement--${tone}`} role={tone === "error" ? "alert" : "status"}>
      <span>{text}</span>
      <button type="button" className="announcement__close" onClick={dismiss} aria-label="Ocultar aviso">
        ×
      </button>
    </div>
  );
}
