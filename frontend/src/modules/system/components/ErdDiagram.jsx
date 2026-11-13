import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const BOX_W = 230;
const HEAD_H = 24;
const ROW_H = 16;
const GAP_X = 70;
const GAP_Y = 28;
const PER_COLUMN = 7;

function visibleColumns(t, showAll) {
  if (showAll) return t.columns;
  const keys = t.columns.filter((c) => c.pk || c.fk);
  return keys.length ? keys : t.columns.slice(0, 3);
}

function boxHeight(t, showAll) {
  const cols = visibleColumns(t, showAll);
  const extra = !showAll && cols.length < t.columns.length ? 1 : 0;
  return HEAD_H + (cols.length + extra) * ROW_H + 8;
}

const ROW_LIMIT = 2600;

/** Disposición inicial: un bloque de columnas por módulo; los bloques se acomodan en franjas (proporción de pantalla). */
function layout(tables, showAll) {
  const pos = {};
  const byModule = new Map();
  tables.forEach((t) => byModule.set(t.module, [...(byModule.get(t.module) ?? []), t]));
  let x = 20;
  let top = 20;
  let bandBottom = 20;
  for (const [, list] of byModule) {
    const cols = Math.ceil(list.length / PER_COLUMN);
    const blockW = cols * (BOX_W + GAP_X);
    if (x > 20 && x + blockW > ROW_LIMIT) {
      x = 20;
      top = bandBottom + 40;
    }
    for (let i = 0; i < list.length; i += PER_COLUMN) {
      let y = top;
      list.slice(i, i + PER_COLUMN).forEach((t) => {
        pos[t.name] = { x, y };
        y += boxHeight(t, showAll) + GAP_Y;
      });
      bandBottom = Math.max(bandBottom, y);
      x += BOX_W + GAP_X;
    }
    x += 30;
  }
  return pos;
}

/**
 * Fase 22 — Modelo entidad-relación interactivo (SVG): arrastre el fondo para desplazarse, la rueda o los botones para
 * acercar, arrastre una tabla para moverla y haga clic en ella para resaltar sus relaciones (FK entrantes y salientes).
 */
export default function ErdDiagram({ tables, relations, colors, focus, onFocus, showAll, search }) {
  const svgRef = useRef(null);
  const [view, setView] = useState({ x: 0, y: 0, k: 0.7 });
  const [pos, setPos] = useState(() => layout(tables, showAll));
  const drag = useRef(null);

  useEffect(() => setPos(layout(tables, showAll)), [tables, showAll]);

  const byName = useMemo(() => Object.fromEntries(tables.map((t) => [t.name, t])), [tables]);
  const rels = useMemo(() => relations.filter((r) => byName[r.from] && byName[r.to]), [relations, byName]);
  const related = useMemo(() => {
    if (!focus) return null;
    const s = new Set([focus]);
    rels.forEach((r) => {
      if (r.from === focus) s.add(r.to);
      if (r.to === focus) s.add(r.from);
    });
    return s;
  }, [focus, rels]);
  const term = search.trim().toLowerCase();
  const matches = (t) => !term || t.name.toLowerCase().includes(term) || t.columns.some((c) => c.name.toLowerCase().includes(term));

  const toWorld = useCallback((clientX, clientY) => {
    const r = svgRef.current.getBoundingClientRect();
    return { x: (clientX - r.left - view.x) / view.k, y: (clientY - r.top - view.y) / view.k };
  }, [view]);

  const zoom = useCallback((factor, cx, cy) => {
    setView((v) => {
      const k = Math.min(2.5, Math.max(0.15, v.k * factor));
      const r = svgRef.current.getBoundingClientRect();
      const px = cx ?? r.width / 2;
      const py = cy ?? r.height / 2;
      return { k, x: px - ((px - v.x) * k) / v.k, y: py - ((py - v.y) * k) / v.k };
    });
  }, []);

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return undefined;
    const onWheel = (e) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      zoom(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX - r.left, e.clientY - r.top);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoom]);

  const onPointerDown = (e, table) => {
    e.currentTarget.setPointerCapture?.(e.pointerId);
    if (table) {
      e.stopPropagation();
      const w = toWorld(e.clientX, e.clientY);
      drag.current = { table, dx: w.x - pos[table].x, dy: w.y - pos[table].y, moved: false };
    } else {
      drag.current = { pan: true, sx: e.clientX - view.x, sy: e.clientY - view.y, moved: false };
      svgRef.current.classList.add("is-panning");
    }
  };
  const onPointerMove = (e) => {
    const d = drag.current;
    if (!d) return;
    d.moved = true;
    if (d.pan) {
      setView((v) => ({ ...v, x: e.clientX - d.sx, y: e.clientY - d.sy }));
    } else {
      const w = toWorld(e.clientX, e.clientY);
      setPos((p) => ({ ...p, [d.table]: { x: w.x - d.dx, y: w.y - d.dy } }));
    }
  };
  const onPointerUp = () => {
    const d = drag.current;
    drag.current = null;
    svgRef.current?.classList.remove("is-panning");
    if (d && !d.moved) onFocus(d.pan ? null : d.table === focus ? null : d.table);
  };

  const fit = () => {
    const r = svgRef.current.getBoundingClientRect();
    const xs = Object.values(pos);
    if (!xs.length) return;
    const maxX = Math.max(...xs.map((p) => p.x)) + BOX_W + 20;
    const maxY = Math.max(...tables.map((t) => (pos[t.name]?.y ?? 0) + boxHeight(t, showAll))) + 20;
    const k = Math.min(1.2, Math.max(0.15, Math.min(r.width / maxX, r.height / maxY)));
    setView({ k, x: 10, y: 10 });
  };
  useEffect(() => {
    if (svgRef.current) fit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tables.length, showAll]);

  const colY = (t, column) => {
    const cols = visibleColumns(t, showAll);
    const i = cols.findIndex((c) => c.name === column);
    return HEAD_H + (i < 0 ? 0 : i) * ROW_H + ROW_H / 2 + 2;
  };

  return (
    <div className="erd">
      <svg ref={svgRef} onPointerDown={(e) => onPointerDown(e, null)} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
        role="img" aria-label={`Modelo entidad-relación: ${tables.length} tablas y ${rels.length} relaciones`}>
        <defs>
          <marker id="erd-one" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10" fill="none" stroke="currentColor" />
          </marker>
        </defs>
        <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>
          {rels.map((r) => {
            const a = pos[r.from];
            const b = pos[r.to];
            if (!a || !b) return null;
            const fromT = byName[r.from];
            const toT = byName[r.to];
            const y1 = a.y + colY(fromT, r.columns[0][0]);
            const y2 = b.y + colY(toT, r.columns[0][1]);
            const rightward = b.x > a.x + BOX_W / 2;
            const x1 = rightward ? a.x + BOX_W : a.x;
            const x2 = rightward ? b.x : b.x + BOX_W;
            const self = r.from === r.to;
            const bend = self ? 50 : Math.max(40, Math.abs(x2 - x1) / 2);
            const d = self
              ? `M ${a.x + BOX_W} ${y1} C ${a.x + BOX_W + bend} ${y1}, ${a.x + BOX_W + bend} ${y2}, ${a.x + BOX_W} ${y2}`
              : `M ${x1} ${y1} C ${x1 + (rightward ? bend : -bend)} ${y1}, ${x2 + (rightward ? -bend : bend)} ${y2}, ${x2} ${y2}`;
            const cls = related ? (r.from === focus || r.to === focus ? " is-focus" : " is-dim") : "";
            return (
              <path key={r.name} d={d} className={`erd-rel${cls}`} markerEnd="url(#erd-one)">
                <title>{`${r.from}.${r.columns.map((c) => c[0]).join(", ")} → ${r.to}.${r.columns.map((c) => c[1]).join(", ")} (${r.name})`}</title>
              </path>
            );
          })}
          {tables.map((t) => {
            const p = pos[t.name];
            if (!p) return null;
            const cols = visibleColumns(t, showAll);
            const h = boxHeight(t, showAll);
            const dim = (related && !related.has(t.name)) || !matches(t);
            const color = colors[t.module] ?? "#64748b";
            return (
              <g key={t.name} transform={`translate(${p.x} ${p.y})`} className={`erd-table${focus === t.name ? " is-focus" : ""}${dim ? " is-dim" : ""}`}
                onPointerDown={(e) => onPointerDown(e, t.name)}>
                <rect className="erd-table__box" width={BOX_W} height={h} rx="6" />
                <path d={`M0 6 a6 6 0 0 1 6 -6 h${BOX_W - 12} a6 6 0 0 1 6 6 v${HEAD_H - 6} h-${BOX_W} z`} fill={color} />
                <text className="erd-table__title" x="8" y="16">
                  {t.name.length > 30 ? `${t.name.slice(0, 29)}…` : t.name}
                </text>
                {cols.map((c, i) => (
                  <g key={c.name} transform={`translate(0 ${HEAD_H + i * ROW_H})`}>
                    <text className="erd-table__key" x="6" y="13">
                      {c.pk ? "PK" : c.fk ? "FK" : ""}
                    </text>
                    <text className="erd-table__col" x="28" y="13">
                      {c.name.length > 20 ? `${c.name.slice(0, 19)}…` : c.name}
                      {c.nullable ? "" : " *"}
                    </text>
                    <text className="erd-table__type" x={BOX_W - 6} y="13" textAnchor="end">
                      {c.type.length > 14 ? `${c.type.slice(0, 13)}…` : c.type}
                    </text>
                  </g>
                ))}
                {!showAll && cols.length < t.columns.length && (
                  <text className="erd-table__type" x="28" y={HEAD_H + cols.length * ROW_H + 13}>
                    + {t.columns.length - cols.length} columnas · {t.rows.toLocaleString("es-SV")} filas
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>
      <div className="erd__zoom">
        <button type="button" onClick={() => zoom(1.25)} aria-label="Acercar">+</button>
        <button type="button" onClick={() => zoom(1 / 1.25)} aria-label="Alejar">−</button>
        <button type="button" onClick={fit} aria-label="Ajustar a la pantalla">⤢</button>
      </div>
    </div>
  );
}
