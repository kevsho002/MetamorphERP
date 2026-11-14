import { useId } from "react";

/**
 * Fase 26 — Texto de ayuda de un campo como tooltip.
 *
 * Reemplaza los mensajes largos bajo las cajas de texto (que desalineaban los formularios en cuadrícula) por un ícono
 * «i» en la esquina del rótulo. La explicación aparece al pasar el cursor sobre el campo o al enfocarlo con el teclado,
 * encima del rótulo para no tapar lo que se escribe. Sigue en el árbol de accesibilidad: el control puede referenciarlo
 * con aria-describedby (prop `id`).
 *
 * Debe ir dentro de un contenedor `.field` (label o div); los errores de validación siguen visibles con `.field__error`.
 */
export default function FieldHint({ id, children, label = "Ayuda" }) {
  const auto = useId();
  if (children == null || children === false || children === "") return null;
  const tipId = id || `tip-${auto}`;
  return (
    <span className="field-tip">
      <span className="field-tip__icon" tabIndex={0} aria-label={label} aria-describedby={tipId}>
        i
      </span>
      <small id={tipId} role="tooltip" className="field-tip__bubble">
        {children}
      </small>
    </span>
  );
}
