import { ThemedLogo } from "../components/ui/Brand.jsx";

/**
 * Fase 26 — Marco de las pantallas de acceso (login y cambio obligatorio de contraseña): panel de marca a la izquierda
 * con el saludo y la propuesta de valor, y el formulario a la derecha. En pantallas angostas el panel de marca se
 * reduce a una franja superior.
 */
export default function AuthShell({ children, greeting = "¡Hola,", highlight = "equipo Metamorph!" }) {
  const year = new Date().getFullYear();
  return (
    <main className="auth-split">
      <section className="auth-hero" aria-hidden="true">
        <svg className="auth-hero__lines" viewBox="0 0 600 800" preserveAspectRatio="xMidYMid slice" focusable="false">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <path key={i} d={`M ${-80 + i * 40} 820 C ${120 + i * 30} ${520 - i * 40}, ${260 + i * 36} ${180 - i * 20}, ${360 + i * 42} -40`} />
          ))}
        </svg>
        <div className="auth-hero__body">
          <img className="auth-hero__mark" src="/brand/icon-192.png" alt="" width={72} height={72} decoding="async" />
          <h2 className="auth-hero__title">
            {greeting}
            <br />
            <span>{highlight}</span>
          </h2>
          <p className="auth-hero__lead">
            Recursos humanos, Workforce Management y planillas en un solo lugar: horarios, asistencia, acciones de personal y
            boletas siempre al día.
          </p>
          <ul className="auth-hero__points">
            <li>Expediente digital y acciones de personal con firma</li>
            <li>Grilla de planificación y adherencia en tiempo real</li>
            <li>Planilla automática y boleta diaria</li>
          </ul>
        </div>
        <p className="auth-hero__foot">© {year} Metamorph ERP. Todos los derechos reservados.</p>
      </section>
      <section className="auth-panel">
        <div className="auth-panel__inner">
          <div className="auth-panel__logo">
            <ThemedLogo />
            <span className="sr-only">Metamorph ERP</span>
          </div>
          {children}
        </div>
      </section>
    </main>
  );
}
