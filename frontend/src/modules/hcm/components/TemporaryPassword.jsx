import { useState } from "react";

/**
 * Contraseña temporal de una cuenta recién creada o reseteada. Se muestra UNA sola vez
 * (el servidor no la guarda en claro ni la vuelve a entregar).
 */
export default function TemporaryPassword({ username, password, onDismiss }) {
  const [copied, setCopied] = useState(false);
  const [visible, setVisible] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(password);
      setCopied(true);
    } catch {
      setVisible(true); // sin portapapeles: se muestra para copiarla a mano
    }
  };

  return (
    <div className="temp-password" role="status">
      <p className="temp-password__title">
        Contraseña temporal de <strong>{username}</strong>
      </p>
      <div className="temp-password__row">
        <code className="temp-password__value">{visible ? password : "•".repeat(password.length)}</code>
        <button type="button" className="button button--ghost button--sm" onClick={() => setVisible((v) => !v)}>
          {visible ? "Ocultar" : "Mostrar"}
        </button>
        <button type="button" className="button button--sm" onClick={copy}>
          {copied ? "Copiada ✓" : "Copiar"}
        </button>
      </div>
      <p className="muted small">
        Entréguela por un canal seguro: no se volverá a mostrar. El sistema pedirá cambiarla en el primer ingreso.
      </p>
      {onDismiss && (
        <button type="button" className="link-button" onClick={onDismiss}>
          Ya la entregué, ocultar
        </button>
      )}
    </div>
  );
}
