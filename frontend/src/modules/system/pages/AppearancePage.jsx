import { useEffect, useRef, useState } from "react";
import {
  DENSITIES, PALETTES, THEMES, paletteColors, resetPersonalPalette, saveProfile, setAppearance, setBrand, setPersonalPalette,
  useAppearance,
} from "../../../app/appearance.js";
import { useClientConfig } from "../../../app/ClientConfigContext.jsx";
import { formatCurrency } from "../../../app/currency.js";
import { TIME_MODES, useTimeFormat } from "../../../app/timeFormat.js";
import { api } from "../../../services/apiClient.js";

function Choices({ options, value, onChange, label, disabled = false }) {
  return (
    <div className="appearance__choices" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value} disabled={disabled}
          className={`appearance__choice${value === o.value ? " is-active" : ""}`} onClick={() => onChange(o.value)}>
          {o.swatch && (
            <span className="appearance__swatch" aria-hidden="true">
              <span style={{ background: o.swatch[0] }} />
              <span style={{ background: o.swatch[1] }} />
            </span>
          )}
          {o.label}
        </button>
      ))}
    </div>
  );
}

const paletteOptions = (accent) => [
  ...Object.entries(PALETTES).map(([value, p]) => ({ value, label: p.label, swatch: [p.primary, p.accent] })),
  { value: "CUSTOM", label: "Personalizada", swatch: [paletteColors("CUSTOM", accent).primary, accent] },
];

/**
 * Sistema › Apariencia y configuraciones visuales. Fase 22: formato de tiempos, modo día / noche y densidad.
 * Fase 23: paleta DUAL — la global por defecto (la fija el Administrador para todo el ERP y el Django Admin) y una paleta
 * personal opcional guardada en el perfil del usuario; «Usar la predeterminada» vuelve al respaldo de fábrica.
 */
export default function AppearancePage() {
  const time = useTimeFormat();
  const look = useAppearance();
  const { refresh } = useClientConfig();
  const [org, setOrg] = useState(null);
  const [draft, setDraft] = useState({ brand_palette: "NAVY", brand_accent: "#2f7dd1" });
  const [mine, setMine] = useState({ palette: "", accent: "#2f7dd1" });
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(null);
  const orgRef = useRef(null);
  const savedMine = useRef({ palette: "", accent: "" });

  // Al salir sin guardar, se descartan las vistas previas (global y personal).
  useEffect(() => () => {
    if (orgRef.current) setBrand(orgRef.current.brand_palette, orgRef.current.brand_accent);
    setPersonalPalette(savedMine.current.palette, savedMine.current.accent);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    api.get("/system/appearance/", { signal: controller.signal })
      .then((data) => {
        setOrg(data);
        orgRef.current = data;
        setDraft({ brand_palette: data.brand_palette, brand_accent: data.brand_accent || "#2f7dd1" });
        savedMine.current = { palette: data.personal.palette, accent: data.personal.accent };
        setMine({ palette: data.personal.palette, accent: data.personal.accent || "#2f7dd1" });
      })
      .catch(() => {});
    return () => controller.abort();
  }, []);

  const done = (promise, key) => {
    setBusy(key);
    setNotice(null);
    return promise
      .then((b) => b && setNotice({ ok: true, text: b.feedback }))
      .catch((err) => setNotice({ ok: false, text: err.message }))
      .finally(() => setBusy(null));
  };

  // ---- paleta global (Administrador)
  const previewGlobal = (patch) => {
    const next = { ...draft, ...patch };
    setDraft(next);
    setBrand(next.brand_palette, next.brand_accent);
  };
  const saveGlobal = () =>
    done(api.patch("/system/appearance/", draft).then((b) => {
      setOrg((o) => ({ ...o, ...b }));
      orgRef.current = { ...orgRef.current, ...b };
      refresh();
      return b;
    }), "global");
  const globalDirty = org && (org.brand_palette !== draft.brand_palette || (draft.brand_palette === "CUSTOM" && org.brand_accent !== draft.brand_accent));

  // ---- paleta personal (perfil)
  const previewMine = (patch) => {
    const next = { ...mine, ...patch };
    setMine(next);
    setPersonalPalette(next.palette, next.accent);
  };
  const saveMine = () =>
    done(setPersonalPalette(mine.palette, mine.accent, true).then((b) => {
      savedMine.current = { palette: mine.palette, accent: mine.palette === "CUSTOM" ? mine.accent : "" };
      return b;
    }), "mine");
  const useDefault = () =>
    done(resetPersonalPalette().then((b) => {
      savedMine.current = { palette: "", accent: "" };
      setMine((m) => ({ ...m, palette: "" }));
      return b;
    }), "reset");
  const mineDirty = mine.palette !== savedMine.current.palette || (mine.palette === "CUSTOM" && mine.accent !== savedMine.current.accent);
  const globalLabel = org ? (PALETTES[org.brand_palette]?.label ?? "Personalizada") : "…";

  return (
    <section className="card card--wide">
      <header className="card__header">
        <div>
          <h1 className="page-title">Apariencia y configuraciones visuales</h1>
          <p className="muted page-subtitle">
            Sus preferencias se guardan en su perfil y le siguen en cualquier equipo. La paleta global la define el Administrador y es el respaldo de
            fábrica de todo el ERP (también del panel /admin/).
          </p>
        </div>
      </header>
      {notice && <p className={notice.ok ? "alert alert--ok" : "error-box"}>{notice.text}</p>}
      <div className="appearance">
        <section>
          <h2 className="section-title">Formato de tiempos</h2>
          <p className="muted small">Totales y cúmulos de tiempo de planillas, adherencia, horarios y reportes.</p>
          <Choices label="Formato de tiempos" options={TIME_MODES} value={time.mode}
            onChange={(m) => { time.setMode(m); saveProfile({ time_mode: m }); }} />
          <p className="small">
            Ejemplo: 7 h 30 min = <strong>{time.seconds(27000)}</strong>
          </p>
        </section>
        <section>
          <h2 className="section-title">Modo día / noche</h2>
          <Choices label="Tema" options={THEMES} value={look.theme} onChange={(theme) => setAppearance({ theme })} />
          <p className="muted small">Activo ahora: {look.resolved === "dark" ? "noche (oscuro)" : "día (claro)"}.</p>
        </section>
        <section>
          <h2 className="section-title">Densidad de la interfaz</h2>
          <Choices label="Densidad" options={DENSITIES} value={look.density} onChange={(density) => setAppearance({ density })} />
        </section>
        <section>
          <h2 className="section-title">Paleta de colores</h2>
          <p className="muted small">
            Paleta en uso: <strong>{look.source === "personal" ? "su paleta personal" : `la global (${globalLabel})`}</strong>.
          </p>
          <div className="appearance__layers">
            <div className="appearance__layer">
              <h3>Mi paleta (personal)</h3>
              <p className="muted small">Solo para usted. «Usar la predeterminada» vuelve a la paleta global.</p>
              <Choices label="Mi paleta" value={mine.palette || "DEFAULT"}
                options={[{ value: "DEFAULT", label: `Usar la predeterminada (${globalLabel})` }, ...paletteOptions(mine.accent)]}
                onChange={(v) => (v === "DEFAULT" ? previewMine({ palette: "" }) : previewMine({ palette: v }))} />
              {mine.palette === "CUSTOM" && (
                <label className="field" style={{ maxWidth: 220 }}>
                  <span className="field__label">Mi color de acento</span>
                  <input type="color" value={mine.accent} onChange={(e) => previewMine({ accent: e.target.value })} />
                </label>
              )}
              <div className="form-actions form-actions--start">
                <button type="button" className="button button--sm" disabled={!mineDirty || !!busy} onClick={saveMine}>
                  {busy === "mine" ? "Guardando…" : "Guardar en mi perfil"}
                </button>
                <button type="button" className="button button--ghost button--sm" disabled={!savedMine.current.palette || !!busy} onClick={useDefault}>
                  Restablecer la predeterminada
                </button>
              </div>
            </div>
            <div className="appearance__layer">
              <h3>Paleta global por defecto</h3>
              <p className="muted small">
                {org?.can_manage ? "Aplica a todos los usuarios sin paleta personal y al panel /admin/." : "Solo el Administrador la cambia."}
              </p>
              <Choices label="Paleta global" options={paletteOptions(draft.brand_accent)} value={draft.brand_palette} disabled={!org?.can_manage}
                onChange={(brand_palette) => previewGlobal({ brand_palette })} />
              {org?.can_manage && draft.brand_palette === "CUSTOM" && (
                <label className="field" style={{ maxWidth: 220 }}>
                  <span className="field__label">Color de acento global</span>
                  <input type="color" value={draft.brand_accent} onChange={(e) => previewGlobal({ brand_accent: e.target.value })} />
                </label>
              )}
              {org?.can_manage && (
                <div className="form-actions form-actions--start">
                  <button type="button" className="button button--sm" disabled={!globalDirty || !!busy} onClick={saveGlobal}>
                    {busy === "global" ? "Guardando…" : "Guardar para todos"}
                  </button>
                  <button type="button" className="button button--ghost button--sm" disabled={!globalDirty || !!busy}
                    onClick={() => previewGlobal({ brand_palette: org.brand_palette, brand_accent: org.brand_accent || "#2f7dd1" })}>
                    Descartar
                  </button>
                </div>
              )}
            </div>
          </div>
          <div className="appearance__preview" aria-label="Vista previa" style={{ marginTop: 12 }}>
            <div className="appearance__bar" />
            <div className="pay-actions">
              <button type="button" className="button button--sm">Botón principal</button>
              <button type="button" className="button button--ghost button--sm">Secundario</button>
              <a href="#preview" onClick={(e) => e.preventDefault()}>Enlace</a>
            </div>
            <p className="small muted">
              Montos: {formatCurrency(1234.5, "USD")} · {formatCurrency(1234.5, "GTQ")} · {formatCurrency(1234.5, "MXN")} · {formatCurrency(1234.5, "COP")}
            </p>
          </div>
        </section>
      </div>
    </section>
  );
}
