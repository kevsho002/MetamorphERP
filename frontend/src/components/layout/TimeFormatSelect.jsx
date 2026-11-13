import { TIME_MODES, useTimeFormat } from "../../app/timeFormat.js";

/** Fase 21: alterna al instante todos los totales de tiempo entre HH:MM:SS y horas decimales (dos decimales). */
export default function TimeFormatSelect() {
  const { mode, setMode } = useTimeFormat();
  return (
    <label className="time-format" title="Formato de los totales y cúmulos de tiempo">
      <span className="time-format__label">Tiempos</span>
      <select value={mode} onChange={(e) => setMode(e.target.value)} aria-label="Formato de tiempos">
        {TIME_MODES.map((m) => (
          <option key={m.value} value={m.value}>
            {m.label}
          </option>
        ))}
      </select>
    </label>
  );
}
