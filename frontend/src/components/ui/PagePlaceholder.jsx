/** Marcador para pantallas cuyo desarrollo corresponde a fases posteriores. */
export default function PagePlaceholder({ title, description, tables = [] }) {
  return (
    <section className="card">
      <h1 className="page-title">{title}</h1>
      <p className="muted">{description}</p>
      {tables.length > 0 && (
        <>
          <h2 className="section-title">Tablas de soporte (ya creadas)</h2>
          <ul className="chip-list">
            {tables.map((t) => (
              <li key={t} className="chip">
                <code>{t}</code>
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="badge badge--info">Interfaz pendiente — fase posterior</p>
    </section>
  );
}
