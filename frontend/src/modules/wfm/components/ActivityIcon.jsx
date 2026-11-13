/**
 * Iconos de los cuadros de la barra de segmentos (Fase 17). Las claves coinciden con `adh_activity_type.icon`.
 * Trazos simples de 24×24 que heredan `currentColor`.
 */
const PATHS = {
  headset: "M4 14v-2a8 8 0 0 1 16 0v2 M4 14h3v6H5a1 1 0 0 1-1-1z M20 14h-3v6h2a1 1 0 0 0 1-1z M17 20c0 1-2 2-5 2",
  inbox: "M3 13l3-8h12l3 8 M3 13v6h18v-6 M3 13h5l1 3h6l1-3h5",
  coffee: "M4 9h13v5a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5z M17 10h1.5a2.5 2.5 0 0 1 0 5H17 M8 3v3 M12 3v3",
  utensils: "M7 3v8 M5 3v5a2 2 0 0 0 4 0V3 M7 11v10 M17 3c-2 2-2 6 0 8v10",
  school: "M2 9l10-5 10 5-10 5z M6 11v5c3 2 9 2 12 0v-5 M22 9v6",
  chat: "M4 5h16v10H9l-5 4z M8 9h8 M8 12h5",
  users: "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M3 20a6 6 0 0 1 12 0 M16 11a3 3 0 1 0 0-6 M17 14a5 5 0 0 1 4 6",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M12 7v5l3 2",
  star: "M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z",
  flag: "M5 21V4 M5 4h11l-2 4 2 4H5",
  // Fase 19
  heart: "M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.5-7 10-7 10z",
  laptop: "M5 5h14v10H5z M3 19h18 M10 17h4",
  briefcase: "M4 8h16v11H4z M9 8V5h6v3 M4 13h16",
  alarm: "M12 21a8 8 0 1 0 0-16 8 8 0 0 0 0 16z M12 9v4l2 2 M5 3L2 6 M19 3l3 3",
  "user-x": "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6z M3 20a6 6 0 0 1 12 0 M17 8l4 4 M21 8l-4 4",
};

export default function ActivityIcon({ name, size = 16, className = "" }) {
  const d = PATHS[name] ?? PATHS.clock;
  return (
    <svg className={`activity-icon ${className}`} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {d.split(" M").map((seg, i) => (
        <path key={i} d={i === 0 ? seg : `M${seg}`} />
      ))}
    </svg>
  );
}
