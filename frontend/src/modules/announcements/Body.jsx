/** Contenido en texto plano: párrafos separados por línea en blanco y viñetas con «- ». Nunca se interpreta HTML. */
export default function Body({ text }) {
  const blocks = (text || "").split(/\n{2,}/);
  return blocks.map((block, i) => {
    const lines = block.split("\n");
    if (lines.every((l) => /^\s*[-•]\s+/.test(l))) {
      return (
        <ul key={i}>
          {lines.map((l, j) => (
            <li key={j}>{l.replace(/^\s*[-•]\s+/, "")}</li>
          ))}
        </ul>
      );
    }
    return (
      <p key={i}>
        {lines.map((l, j) => (
          <span key={j}>
            {j > 0 && <br />}
            {l}
          </span>
        ))}
      </p>
    );
  });
}
