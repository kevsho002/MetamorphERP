/** Paginación para respuestas DRF PageNumberPagination ({count, next, previous, results}). */
export default function Pagination({ page, pageSize, count, onPage }) {
  const pages = Math.max(1, Math.ceil(count / pageSize));
  if (count === 0) return null;
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, count);
  return (
    <nav className="pagination" aria-label="Paginación">
      <span className="muted">
        {from}–{to} de {count}
      </span>
      <div className="pagination__buttons">
        <button type="button" className="button button--ghost button--sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
          ‹ Anterior
        </button>
        <span className="pagination__page">
          Página {page} de {pages}
        </span>
        <button type="button" className="button button--ghost button--sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
          Siguiente ›
        </button>
      </div>
    </nav>
  );
}
