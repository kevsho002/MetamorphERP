import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useAuth } from "../../../auth/AuthContext.jsx";
import { employeesApi } from "../api.js";
import DocumentsPanel, { Completeness } from "../components/DocumentsPanel.jsx";
import DossierTab from "../components/DossierTab.jsx";
import EmployeePhoto from "../components/EmployeePhoto.jsx";
import FeedbackPanel from "../components/Feedback.jsx";
import HistoryPanel from "../components/HistoryPanel.jsx";
import ImageUploadDialog from "../components/ImageUploadDialog.jsx";
import ImageViewer from "../components/ImageViewer.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import UserAccountPanel from "../components/UserAccountPanel.jsx";
import RosterPanel from "../../roster/components/RosterPanel.jsx";
import GeneralIdsPanel from "../../generalIds/components/GeneralIdsPanel.jsx";
import SchedulePanel from "../../scheduling/components/SchedulePanel.jsx";
import EmployeeActionsPanel from "../../personnelActions/components/EmployeeActionsPanel.jsx";
import { useCatalogs } from "../hooks/useCatalogs.js";
import { formatDate, todayIso } from "../lib/format.js";

const FIXED_TABS = {
  documents: "Documentos",
  roster: "Roster",
  general_ids: "General IDs",
  schedule: "Horario",
  actions: "Acciones de personal",
  account: "Cuenta Metamorph",
  history: "Historial",
};

/**
 * Expediente digital del empleado (/hcm/employees/:code).
 * Las pestañas y secciones salen de la plantilla JSON del país vigente a la fecha elegida
 * (por defecto, la fecha de ingreso); se agregan Documentos, Cuenta Metamorph e Historial.
 * La pestaña y la fecha viven en la URL (?tab=documents&as_of=2027-01-01) para compartir enlaces.
 */
export default function EmployeeDetailPage() {
  const { code } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const { hasPermission } = useAuth();
  const catalogs = useCatalogs();
  const asOf = params.get("as_of") || "";
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const [reloadKey, setReloadKey] = useState(0);
  const [flash, setFlash] = useState(location.state?.flash ?? null);
  const [notice, setNotice] = useState(null);
  const [upload, setUpload] = useState(null); // {mode, type}
  const [viewer, setViewer] = useState(null); // {items, index}
  const [customDate, setCustomDate] = useState(asOf || todayIso());

  useEffect(() => {
    if (location.state?.flash) navigate(`${location.pathname}${location.search}`, { replace: true, state: null });
  }, [location, navigate]);

  useEffect(() => {
    const controller = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    employeesApi
      .digitalFile(code, asOf || undefined, { signal: controller.signal })
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((err) => {
        if (err.name === "AbortError") return;
        setState({ loading: false, data: null, error: err.status === 404 ? "El empleado no existe." : err.message });
      });
    return () => controller.abort();
  }, [code, asOf, reloadKey]);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);
  const data = state.data;
  const emp = data?.employee;
  const perms = data?.permissions ?? {};

  const tabs = useMemo(() => {
    if (!data) return [];
    const list = data.tabs.map((t) => ({ id: t.id, label: t.label, dynamic: true }));
    list.push({ id: "documents", label: `${FIXED_TABS.documents} (${data.documents.required_ok}/${data.documents.required_total})` });
    if (hasPermission("roster.view")) list.push({ id: "roster", label: FIXED_TABS.roster });
    if (hasPermission("general_ids.view")) list.push({ id: "general_ids", label: FIXED_TABS.general_ids });
    if (hasPermission("schedules.view")) list.push({ id: "schedule", label: FIXED_TABS.schedule });
    if (hasPermission("actions.view")) list.push({ id: "actions", label: FIXED_TABS.actions });
    if (hasPermission("users.view")) list.push({ id: "account", label: FIXED_TABS.account });
    if (hasPermission("hcm.manage")) list.push({ id: "history", label: FIXED_TABS.history });
    return list;
  }, [data, hasPermission]);

  const activeTab = tabs.some((t) => t.id === params.get("tab")) ? params.get("tab") : tabs[0]?.id;
  const setTab = (id) =>
    setParams(
      (p) => {
        const next = new URLSearchParams(p);
        next.set("tab", id);
        return next;
      },
      { replace: true },
    );
  const setAsOf = (value) =>
    setParams(
      (p) => {
        const next = new URLSearchParams(p);
        if (value) next.set("as_of", value);
        else next.delete("as_of");
        return next;
      },
      { replace: true },
    );

  // ------------------------------------------------------------- visor de imágenes
  const openPhoto = () =>
    data?.photo &&
    setViewer({
      items: [{ src: data.photo.url, title: `Fotografía de ${emp.full_name}`, subtitle: `Versión ${data.photo.version}` }],
      index: 0,
    });

  const openDocument = (typeCode, version) => {
    const viewable = data.documents.items.filter((d) => d.current && d.viewable);
    if (version) {
      const doc = data.documents.items.find((d) => d.code === typeCode);
      setViewer({
        items: [
          {
            src: version.content_url,
            title: doc?.label ?? typeCode,
            subtitle: `Versión ${version.version}${version.is_current ? " (vigente)" : ""} · ${version.original_name ?? ""}`,
            downloadUrl: employeesApi.contentUrl(version.content_url, { download: true }),
          },
        ],
        index: 0,
      });
      return;
    }
    setViewer({
      items: viewable.map((d) => ({
        src: d.current.content_url,
        title: d.label,
        subtitle: `Versión ${d.current.version} · ${d.current.original_name ?? ""}${d.current.expiry_date ? ` · vence ${formatDate(d.current.expiry_date)}` : ""}`,
        downloadUrl: employeesApi.contentUrl(d.current.content_url, { download: true }),
      })),
      index: Math.max(0, viewable.findIndex((d) => d.code === typeCode)),
    });
  };

  const onUploaded = (result) => {
    setUpload(null);
    setNotice(result.feedback);
    reload();
  };

  // ------------------------------------------------------------- render
  if (state.loading && !data) return <p className="muted">Cargando expediente…</p>;
  if (state.error && !data) {
    return (
      <section className="card">
        <p className="error-box">{state.error}</p>
        <Link to="/hcm/employees">← Volver a la lista</Link>
      </section>
    );
  }

  const template = data.template;
  const dynamicTab = data.tabs.find((t) => t.id === activeTab);
  const account = emp.user_account;

  return (
    <div className="stack">
      <section className="card card--wide dossier-header">
        <nav className="breadcrumb" aria-label="Ruta">
          <Link to="/hcm/employees">Empleados</Link>
          <span aria-hidden="true">/</span>
          <span>{emp.employee_code}</span>
        </nav>
        <div className="dossier-header__main">
          <div className="dossier-header__photo">
            <EmployeePhoto url={data.photo?.url} name={emp.full_name} size="lg" onClick={openPhoto} />
            {perms.can_upload && (
              <button type="button" className="link-button" onClick={() => setUpload({ mode: "photo" })}>
                {data.photo ? "Cambiar foto" : "Agregar foto"}
              </button>
            )}
          </div>
          <div className="dossier-header__info">
            <h1 className="page-title">{emp.full_name}</h1>
            <p className="page-subtitle">
              <code>{emp.employee_code}</code> · {emp.country_name} ·{" "}
              <StatusBadge value={emp.employment_status} label={emp.employment_status_label} />
            </p>
            <dl className="dossier-facts">
              <div>
                <dt>Ingreso</dt>
                <dd>{formatDate(emp.hire_date)}</dd>
              </div>
              {emp.termination_date && (
                <div>
                  <dt>Terminación</dt>
                  <dd>{formatDate(emp.termination_date)}</dd>
                </div>
              )}
              <div>
                <dt>Centro de costos</dt>
                <dd>{emp.cost_center ? `${emp.cost_center} — ${emp.cost_center_name ?? ""}` : "—"}</dd>
              </div>
              <div>
                <dt>Expediente</dt>
                <dd>{data.file.status_label}</dd>
              </div>
              <div>
                <dt>Cuenta Metamorph</dt>
                <dd>
                  {account ? (
                    <>
                      <code>{account.username}</code> · {account.is_active ? account.role_label : "desactivada"}
                    </>
                  ) : emp.has_user_account ? (
                    "Vinculada"
                  ) : (
                    <span className="muted">Sin cuenta</span>
                  )}
                </dd>
              </div>
            </dl>
            <Completeness
              ok={data.documents.required_ok}
              total={data.documents.required_total}
              percent={data.documents.percent}
              compact
            />
          </div>
          {hasPermission("hcm.manage") && (
            <div className="dossier-header__actions">
              <Link className="button" to={`/hcm/employees/${emp.employee_code}/edit`}>
                Editar datos
              </Link>
            </div>
          )}
        </div>

        {flash && (
          <div className="flash">
            <FeedbackPanel result={flash} title={flash.saved ? "Cambios guardados" : null} />
            <button type="button" className="button button--ghost button--sm" onClick={() => setFlash(null)}>
              Cerrar
            </button>
          </div>
        )}
        {notice && (
          <div className="alert alert--ok flash" role="status">
            <p className="alert__text">{notice}</p>
            <button type="button" className="button button--ghost button--sm" onClick={() => setNotice(null)}>
              Cerrar
            </button>
          </div>
        )}
      </section>

      <section className="card card--wide">
        {/* ------------------------------------------------ fecha de efectividad */}
        <div className="effective-bar" role="group" aria-label="Versión de la plantilla">
          <span className="effective-bar__label">Ver el expediente según la plantilla vigente a:</span>
          <label className="radio radio--inline">
            <input type="radio" name="basis" checked={!asOf} onChange={() => setAsOf("")} />
            <span>Fecha de ingreso ({formatDate(emp.hire_date)})</span>
          </label>
          <label className="radio radio--inline">
            <input type="radio" name="basis" checked={Boolean(asOf)} onChange={() => setAsOf(customDate || todayIso())} />
            <span>Otra fecha</span>
          </label>
          <input
            type="date"
            value={asOf || customDate}
            aria-label="Fecha de efectividad"
            onChange={(e) => {
              setCustomDate(e.target.value);
              if (e.target.value) setAsOf(e.target.value);
            }}
          />
          <button type="button" className="button button--ghost button--sm" onClick={() => setAsOf(todayIso())}>
            Hoy
          </button>
          {state.loading && <span className="muted small">Actualizando…</span>}
        </div>
        {template ? (
          <p className="muted small effective-bar__template">
            Plantilla «{template.name}», vigente desde {formatDate(template.effective_date)}
            {template.is_hire_template ? " (la que validó el alta)." : "."}
            {!template.is_hire_template && " Esta versión es distinta a la de la fecha de ingreso: los campos y documentos pueden variar."}
          </p>
        ) : (
          <p className="alert alert--warn">{data.template_error}</p>
        )}
        {data.gaps.length > 0 && (
          <p className="alert alert--warn">
            Según esta versión de la plantilla faltan {data.gaps.length} dato{data.gaps.length === 1 ? "" : "s"} obligatorio
            {data.gaps.length === 1 ? "" : "s"}: {data.gaps.map((g) => g.label).join(", ")}.
          </p>
        )}

        {/* ------------------------------------------------ pestañas */}
        <div className="tabs" role="tablist" aria-label="Secciones del expediente">
          {tabs.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              id={`tab-${t.id}`}
              aria-selected={activeTab === t.id}
              aria-controls={`panel-${t.id}`}
              className={`tab${activeTab === t.id ? " tab--active" : ""}`}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div role="tabpanel" id={`panel-${activeTab}`} aria-labelledby={`tab-${activeTab}`}>
          {dynamicTab && <DossierTab tab={dynamicTab} employee={emp} catalogs={catalogs} templateId={template?.id} />}
          {activeTab === "documents" && (
            <DocumentsPanel
              code={emp.employee_code}
              documents={data.documents}
              canUpload={perms.can_upload}
              onUpload={(type) => setUpload({ mode: "document", type })}
              onView={openDocument}
            />
          )}
          {activeTab === "roster" && <RosterPanel employee={emp} />}
          {activeTab === "general_ids" && <GeneralIdsPanel employee={emp} />}
          {activeTab === "schedule" && <SchedulePanel employee={emp} />}
          {activeTab === "actions" && <EmployeeActionsPanel employee={emp} />}
          {activeTab === "account" && <UserAccountPanel employee={emp} onChanged={reload} />}
          {activeTab === "history" && <HistoryPanel code={emp.employee_code} refreshKey={reloadKey} />}
        </div>

        <p className="muted small">
          Creado {formatDate(emp.created_at)} por {emp.created_by || "—"}
          {emp.updated_at && ` · Modificado ${formatDate(emp.updated_at)} por ${emp.updated_by || "—"}`}
        </p>
      </section>

      {upload && (
        <ImageUploadDialog
          mode={upload.mode}
          employeeCode={emp.employee_code}
          documents={data.documents.items}
          initialType={upload.type ?? undefined}
          onClose={() => setUpload(null)}
          onUploaded={onUploaded}
        />
      )}
      {viewer && (
        <ImageViewer
          items={viewer.items}
          index={viewer.index}
          onIndexChange={(index) => setViewer((v) => ({ ...v, index }))}
          onClose={() => setViewer(null)}
        />
      )}
    </div>
  );
}
