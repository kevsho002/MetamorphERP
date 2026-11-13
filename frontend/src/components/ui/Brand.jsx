/**
 * Fase 23 — Logos corporativos según el contexto (generados por `python manage.py brand_assets` desde logos/):
 *
 * - AppLogo     app_header_logo: tipografía BLANCA para fondos oscuros (barra superior).
 * - DocLogo     doc_header_logo: contraste para fondos BLANCOS (cabecera de documentos e impresos).
 * - BrandMark   favicon_logo: solo la silueta de la mariposa (íconos y avatares reducidos).
 * - ThemedLogo  pantallas de acceso: el de documentos en modo día y el de letras blancas en modo noche.
 */
export function AppLogo({ className = "", small = false }) {
  return (
    <img className={`brand-logo brand-logo--app ${className}`} src={small ? "/brand/app_header_logo_sm.png" : "/brand/app_header_logo.png"}
      alt="Metamorph ERP" width={small ? 96 : 120} height={small ? 24 : 30} decoding="async" />
  );
}

export function DocLogo({ className = "" }) {
  return <img className={`brand-logo brand-logo--doc ${className}`} src="/brand/doc_header_logo.png" alt="Metamorph ERP" width={140} height={36} decoding="async" />;
}

export function BrandMark({ size = 24, className = "", alt = "" }) {
  return <img className={`brand-mark ${className}`} src="/brand/favicon-64.png" alt={alt} width={size} height={size} decoding="async" />;
}

export function ThemedLogo() {
  return (
    <span className="brand-themed">
      <DocLogo className="brand-themed__light" />
      <AppLogo className="brand-themed__dark" />
    </span>
  );
}
