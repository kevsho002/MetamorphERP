const EMPLOYMENT = {
  ACTIVE: ["ok", "Activo"],
  SUSPENDED: ["warn", "Suspendido"],
  TERMINATED: ["muted", "Retirado"],
};

const ROW = {
  CREATED: ["ok", "Creado"],
  VALID: ["ok", "Válida"],
  ERROR: ["error", "Con errores"],
  NOT_APPLIED: ["warn", "No aplicada"],
};

const BATCH = {
  COMPLETED: ["ok", "Completada"],
  PARTIAL: ["warn", "Con errores"],
  FAILED: ["error", "Sin altas"],
  DRY_RUN: ["info", "Solo validación"],
};

const MAPS = { employment: EMPLOYMENT, row: ROW, batch: BATCH };

export default function StatusBadge({ type = "employment", value, label }) {
  const [tone, fallback] = MAPS[type]?.[value] ?? ["info", value];
  return <span className={`badge badge--${tone}`}>{label ?? fallback}</span>;
}
