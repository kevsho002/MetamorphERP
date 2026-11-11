/**
 * Retroalimentación en lenguaje natural del backend (alta, edición o fila de carga):
 * texto principal + lista de errores y advertencias con el campo afectado.
 */
export function MessageList({ messages = [], kind, labels = {} }) {
  if (!messages.length) return null;
  const title = kind === "error" ? (messages.length === 1 ? "Error" : `${messages.length} errores`) : messages.length === 1 ? "Advertencia" : `${messages.length} advertencias`;
  return (
    <div className={`msg-list msg-list--${kind}`}>
      <p className="msg-list__title">{title}</p>
      <ul>
        {messages.map((m, i) => (
          <li key={`${m.code}-${m.field}-${i}`}>
            {m.field && <span className="msg-list__field">{labels[m.field?.replace(/^attributes\./, "")] ?? m.field}</span>}
            {m.message}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function FeedbackPanel({ result, labels, title }) {
  if (!result) return null;
  const hasErrors = result.errors?.length > 0;
  const tone = hasErrors ? "error" : result.warnings?.length ? "warn" : "ok";
  return (
    <section className={`alert alert--${tone}`} aria-live="polite">
      {title && <h2 className="alert__title">{title}</h2>}
      <p className="alert__text">{result.feedback}</p>
      <MessageList messages={result.errors} kind="error" labels={labels} />
      <MessageList messages={result.warnings} kind="warn" labels={labels} />
    </section>
  );
}
