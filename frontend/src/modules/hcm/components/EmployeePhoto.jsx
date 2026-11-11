import { useState } from "react";

function initials(name = "") {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase() || "?";
}

/**
 * Fotografía de perfil (servida por la API con la cookie de sesión) o iniciales si no hay foto.
 * `onClick` la vuelve un botón (p. ej. para abrir el visor).
 */
export default function EmployeePhoto({ url, name, size = "md", onClick }) {
  const [failedUrl, setFailedUrl] = useState(null);
  const showImage = url && failedUrl !== url;
  const content = showImage ? (
    <img src={url} alt={`Fotografía de ${name}`} loading="lazy" onError={() => setFailedUrl(url)} />
  ) : (
    <span aria-hidden="true">{initials(name)}</span>
  );
  const className = `avatar avatar--${size}${showImage ? "" : " avatar--empty"}`;
  if (onClick && showImage) {
    return (
      <button type="button" className={`${className} avatar--button`} onClick={onClick} title="Ver fotografía">
        {content}
      </button>
    );
  }
  return (
    <span className={className} role={showImage ? undefined : "img"} aria-label={showImage ? undefined : `Sin fotografía: ${name}`}>
      {content}
    </span>
  );
}
