import { useCallback, useEffect, useRef, useState } from "react";

const MIN_ZOOM = 0.25;
const MAX_ZOOM = 8;
const clamp = (v, min, max) => Math.min(max, Math.max(min, v));

/**
 * Visor interactivo de imágenes del expediente.
 * items: [{ src, title, subtitle?, downloadUrl? }]
 * - Zoom: botones, rueda del mouse, teclas + / - y doble clic.
 * - Mover: arrastrar con el mouse o el dedo cuando hay zoom.
 * - Girar: botón o tecla R. Ajustar: botón o tecla 0.
 * - Navegar: flechas ← → (si hay varias imágenes). Cerrar: Esc.
 */
export default function ImageViewer({ items, index = 0, onClose, onIndexChange }) {
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [status, setStatus] = useState("loading"); // loading | ready | error
  const drag = useRef(null);
  const closeRef = useRef(null);
  const item = items[index];
  const many = items.length > 1;

  const reset = useCallback(() => {
    setZoom(1);
    setRotation(0);
    setOffset({ x: 0, y: 0 });
  }, []);

  const go = useCallback(
    (delta) => {
      if (!many) return;
      reset();
      setStatus("loading");
      onIndexChange?.((index + delta + items.length) % items.length);
    },
    [many, index, items.length, onIndexChange, reset],
  );

  const zoomBy = useCallback((factor) => setZoom((z) => clamp(z * factor, MIN_ZOOM, MAX_ZOOM)), []);

  useEffect(() => {
    closeRef.current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight") go(1);
      else if (e.key === "ArrowLeft") go(-1);
      else if (e.key === "+" || e.key === "=") zoomBy(1.25);
      else if (e.key === "-") zoomBy(0.8);
      else if (e.key === "0") reset();
      else if (e.key.toLowerCase() === "r") setRotation((r) => (r + 90) % 360);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, onClose, reset, zoomBy]);

  const onWheel = (e) => zoomBy(e.deltaY < 0 ? 1.15 : 0.87);

  const onPointerDown = (e) => {
    if (zoom <= 1) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX - offset.x, y: e.clientY - offset.y };
  };
  const onPointerMove = (e) => {
    if (!drag.current) return;
    setOffset({ x: e.clientX - drag.current.x, y: e.clientY - drag.current.y });
  };
  const onPointerUp = () => {
    drag.current = null;
  };

  if (!item) return null;
  const percent = Math.round(zoom * 100);

  return (
    <div className="viewer" role="dialog" aria-modal="true" aria-label={`Visor: ${item.title}`}>
      <header className="viewer__bar">
        <div className="viewer__title">
          <strong>{item.title}</strong>
          {item.subtitle && <span className="viewer__subtitle">{item.subtitle}</span>}
        </div>
        <div className="viewer__tools" role="toolbar" aria-label="Herramientas de imagen">
          <button type="button" onClick={() => zoomBy(0.8)} aria-label="Alejar" title="Alejar (-)">
            −
          </button>
          <span className="viewer__zoom" aria-live="polite">
            {percent}%
          </span>
          <button type="button" onClick={() => zoomBy(1.25)} aria-label="Acercar" title="Acercar (+)">
            +
          </button>
          <button type="button" onClick={() => setRotation((r) => (r + 90) % 360)} aria-label="Girar 90°" title="Girar (R)">
            ⟳
          </button>
          <button type="button" onClick={reset} aria-label="Ajustar a la pantalla" title="Ajustar (0)">
            ⤢
          </button>
          {item.downloadUrl && (
            <a href={item.downloadUrl} download aria-label="Descargar" title="Descargar">
              ⭳
            </a>
          )}
          <button type="button" ref={closeRef} onClick={onClose} aria-label="Cerrar visor" title="Cerrar (Esc)">
            ✕
          </button>
        </div>
      </header>

      <div
        className={`viewer__stage${zoom > 1 ? " viewer__stage--pan" : ""}`}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={() => (zoom === 1 ? setZoom(2) : reset())}
        onClick={(e) => e.target === e.currentTarget && zoom === 1 && onClose()}
      >
        {status === "loading" && <p className="viewer__status">Cargando imagen…</p>}
        {status === "error" && (
          <p className="viewer__status viewer__status--error">
            No se pudo cargar la imagen (puede estar restringida o haber sido retirada del almacenamiento).
          </p>
        )}
        <img
          key={item.src}
          src={item.src}
          alt={item.title}
          draggable={false}
          onLoad={() => setStatus("ready")}
          onError={() => setStatus("error")}
          style={{
            transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom}) rotate(${rotation}deg)`,
            visibility: status === "error" ? "hidden" : "visible",
          }}
        />
        {many && (
          <>
            <button type="button" className="viewer__nav viewer__nav--prev" onClick={() => go(-1)} aria-label="Imagen anterior">
              ‹
            </button>
            <button type="button" className="viewer__nav viewer__nav--next" onClick={() => go(1)} aria-label="Imagen siguiente">
              ›
            </button>
          </>
        )}
      </div>
      <footer className="viewer__help">
        {many && `${index + 1} de ${items.length} · `}Rueda o +/− para zoom · arrastre para mover · R para girar · Esc para cerrar
      </footer>
    </div>
  );
}
