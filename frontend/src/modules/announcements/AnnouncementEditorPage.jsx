import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { todayIso } from "../hcm/lib/format.js";
import { newsApi, notifyChanged } from "./api.js";
import Body from "./Body.jsx";
import FieldHint from "../../components/ui/FieldHint.jsx";

const EMPTY = {
  title: "", summary: "", body: "", category: "NEWS", requires_ack: false, pinned: false, link_url: "", link_label: "",
  audience_roles: [], ack_due_date: "", expires_at: "",
};
const addDays = (iso, n) => {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
};

/** Fase 25 — Redactar / editar un comunicado (announcements.manage). */
export default function AnnouncementEditorPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [meta, setMeta] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [current, setCurrent] = useState(null);
  const [errors, setErrors] = useState({});
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    newsApi.list({ scope: "draft" }, { signal: controller.signal }).then(setMeta).catch((err) => err.name !== "AbortError" && setError(err.message));
    if (id) {
      newsApi
        .get(id, { signal: controller.signal })
        .then((a) => {
          setCurrent(a);
          setForm({
            title: a.title, summary: a.summary, body: a.body, category: a.category, requires_ack: a.requires_ack, pinned: a.pinned,
            link_url: a.link_url, link_label: a.link_label, audience_roles: a.audience_roles ?? [], ack_due_date: a.ack_due_date ?? "",
            expires_at: a.expires_at ?? "",
          });
        })
        .catch((err) => err.name !== "AbortError" && setError(err.message));
    }
    return () => controller.abort();
  }, [id]);

  const critical = (meta?.categories ?? []).find((c) => c.value === form.category)?.critical;
  const frozen = current?.content_frozen;
  const set = (patch) => setForm((f) => ({ ...f, ...patch }));
  const toggleRole = (r) => set({ audience_roles: form.audience_roles.includes(r) ? form.audience_roles.filter((x) => x !== r) : [...form.audience_roles, r] });

  const save = async (publish) => {
    setBusy(true);
    setError(null);
    setErrors({});
    const payload = { ...form, requires_ack: critical || form.requires_ack, ack_due_date: form.ack_due_date || null, expires_at: form.expires_at || null };
    if (frozen) {
      ["title", "summary", "body", "category", "requires_ack", "link_url", "link_label", "audience_roles"].forEach((k) => delete payload[k]);
    }
    try {
      let body;
      if (id) {
        body = await newsApi.update(id, payload);
        if (publish && body.announcement.status === "DRAFT") body = await newsApi.publish(id);
      } else {
        body = await newsApi.create({ ...payload, publish });
      }
      notifyChanged();
      navigate(`/announcements/${body.announcement.id}`);
    } catch (err) {
      setError(err.message);
      setErrors(err.body?.errors ?? {});
      setBusy(false);
    }
  };

  const err = (k) => errors[k] && <span className="field__error">{errors[k]}</span>;
  if (meta && !meta.can_manage) return <section className="card"><p className="error-box">Su rol no publica comunicados.</p></section>;

  return (
    <section className="card card--wide news-editor">
      <p className="small">
        <Link to={id ? `/announcements/${id}` : "/announcements"}>← Volver</Link>
      </p>
      <h1 className="page-title">{id ? "Editar comunicado" : "Publicar comunicado"}</h1>
      {frozen && (
        <div className="alert alert--warn" role="note">
          <p className="alert__text">
            Comunicado con acuse ya publicado: su contenido está congelado. Solo puede fijarlo, extender el plazo del acuse o la vigencia.
          </p>
        </div>
      )}
      {error && <p className="error-box">{error}</p>}
      <div className="news-editor__grid">
        <label className="field">
          <span className="field__label">Categoría</span>
          <select value={form.category} disabled={frozen} onChange={(e) => set({ category: e.target.value })}>
            {(meta?.categories ?? []).map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
                {c.critical ? " — crítico (acuse obligatorio)" : ""}
              </option>
            ))}
          </select>
          {err("category")}
        </label>
        <label className="field news-editor__wide">
          <span className="field__label">Título</span>
          <input maxLength={200} value={form.title} disabled={frozen} onChange={(e) => set({ title: e.target.value })} required />
          {err("title")}
        </label>
        <label className="field news-editor__full">
          <span className="field__label">Resumen</span>
          <input maxLength={400} value={form.summary} disabled={frozen} onChange={(e) => set({ summary: e.target.value })} />
          <FieldHint>Opcional: se muestra en la portada del periódico.</FieldHint>
        </label>
        <label className="field news-editor__full">
          <span className="field__label">Contenido</span>
          <textarea rows={12} maxLength={20000} value={form.body} disabled={frozen} onChange={(e) => set({ body: e.target.value })}
            placeholder={"Párrafos separados por una línea en blanco.\n- Las viñetas empiezan con guion."} />
          <span className="muted small">{form.body.length.toLocaleString("es-SV")} / 20 000 · texto plano (párrafos y viñetas «- »).</span>
          {err("body")}
        </label>
        <label className="field news-editor__wide">
          <span className="field__label">Enlace (formulario o recurso){form.category === "FORM" ? " — obligatorio" : ""}</span>
          <input type="url" placeholder="https://…" maxLength={500} value={form.link_url} disabled={frozen} onChange={(e) => set({ link_url: e.target.value })} />
          {err("link_url")}
        </label>
        <label className="field">
          <span className="field__label">Texto del enlace</span>
          <input maxLength={80} placeholder="Llenar formulario" value={form.link_label} disabled={frozen} onChange={(e) => set({ link_label: e.target.value })} />
        </label>
        <fieldset className="field news-editor__full news-editor__roles" disabled={frozen}>
          <legend className="field__label">Audiencia (vacío = todos los usuarios)</legend>
          {(meta?.roles ?? []).map((r) => (
            <label key={r.value} className="checkbox">
              <input type="checkbox" checked={form.audience_roles.includes(r.value)} onChange={() => toggleRole(r.value)} /> {r.label}
            </label>
          ))}
        </fieldset>
        <label className="checkbox">
          <input type="checkbox" checked={critical || form.requires_ack} disabled={critical || frozen} onChange={(e) => set({ requires_ack: e.target.checked })} />{" "}
          Requiere acuse de recibo{critical ? " (obligatorio en esta categoría)" : ""}
        </label>
        <label className="checkbox">
          <input type="checkbox" checked={form.pinned} onChange={(e) => set({ pinned: e.target.checked })} /> Fijar como destacado
        </label>
        {(critical || form.requires_ack) && (
          <label className="field">
            <span className="field__label">Plazo del acuse</span>
            <input type="date" min={todayIso()} value={form.ack_due_date} onChange={(e) => set({ ack_due_date: e.target.value })} />
            <FieldHint>Vacío = {meta?.default_ack_days ?? 7} días desde la publicación ({addDays(todayIso(), meta?.default_ack_days ?? 7)}).</FieldHint>
            {err("ack_due_date")}
          </label>
        )}
        <label className="field">
          <span className="field__label">Visible hasta (opcional)</span>
          <input type="date" value={form.expires_at} onChange={(e) => set({ expires_at: e.target.value })} />
          {err("expires_at")}
        </label>
      </div>

      <div className="form-actions">
        <button type="button" className="button button--ghost" onClick={() => setPreview((p) => !p)}>
          {preview ? "Ocultar vista previa" : "Vista previa"}
        </button>
        {(!current || current.status === "DRAFT") && (
          <button type="button" className="button button--ghost" disabled={busy} onClick={() => save(false)}>
            Guardar borrador
          </button>
        )}
        <button type="button" className="button" disabled={busy} onClick={() => save(!current || current.status === "DRAFT")}>
          {busy ? "Guardando…" : current && current.status !== "DRAFT" ? "Guardar cambios" : "Publicar"}
        </button>
      </div>
      {preview && (
        <article className="news-detail__body news-editor__preview">
          <h2 className="news__title">{form.title || "(sin título)"}</h2>
          {form.summary && <p className="news-detail__summary">{form.summary}</p>}
          <Body text={form.body} />
        </article>
      )}
    </section>
  );
}
