import { useState } from "react";
import { fmtDuration, fmtTime } from "../api.js";
import { useAgentPresence, useTicker } from "../AgentPresenceContext.jsx";

/**
 * Consola del agente: iniciar sesión (Available), entrar a colas (On Queue = tiempo productivo) o elegir un estado y
 * un auxiliar / sub-auxiliar permitido para su grupo. Cada cambio lo registra el SERVIDOR con su hora exacta
 * (Start Time / End Time / Duration); aquí el cronómetro solo muestra el tiempo transcurrido. Comparte el estado con
 * la barra superior (botón de turno y avatar), así que un cambio hecho en cualquiera de los dos se refleja en ambos.
 */
export default function AgentConsolePage() {
  const presence = useAgentPresence();
  const { busy, offset } = presence;
  const state = { loading: presence.loading, data: presence.data, error: presence.error };
  const [picked, setPicked] = useState(null); // estado primario elegido que tiene auxiliares
  const now = useTicker();

  const run = async (fn) => {
    const data = await fn();
    if (data) setPicked(null);
  };

  const d = state.data;
  const current = d?.current;
  const elapsed = current ? now + offset - new Date(current.start_at).getTime() : 0;
  const choose = (option) => {
    if (option.aux_codes.length) setPicked(option.code === picked ? null : option.code);
    else run(() => presence.setStatus(option.code));
  };
  const pickedOption = d?.options.find((o) => o.code === picked);

  return (
    <section className="card card--wide" aria-busy={state.loading}>
      <header className="card__header">
        <div>
          <h1 className="page-title">Mi estado (ACD)</h1>
          <p className="muted page-subtitle">
            {d ? (
              <>
                {d.full_name} · <code>{d.employee_code}</code>
                {d.group ? ` · Grupo ${d.group.name} · División ${d.division?.name}` : ""}
              </>
            ) : (
              "Consola del agente"
            )}
          </p>
        </div>
        {d?.group &&
          (d.logged_in ? (
            <button type="button" className="button button--danger" disabled={busy} onClick={() => run(presence.logout)}>
              Cerrar sesión (Offline)
            </button>
          ) : (
            <button type="button" className="button" disabled={busy} onClick={() => run(presence.login)}>
              Iniciar sesión
            </button>
          ))}
      </header>

      {state.error && <p className="error-box">{state.error}</p>}
      {!presence.enabled && (
        <div className="alert alert--warn" role="status">
          <p className="alert__text">Su usuario no tiene un expediente de empleado vinculado: la consola de estados ACD es para agentes.</p>
        </div>
      )}
      {d && !d.group && (
        <div className="alert alert--warn" role="status">
          <p className="alert__text">No pertenece a ningún grupo ACD. Pida a Workforce que lo asigne a un grupo de agentes.</p>
        </div>
      )}

      {d && (
        <div className="acd-now" style={{ "--status-color": current?.color ?? "#94a3b8" }}>
          <span className="acd-now__dot" aria-hidden="true" />
          <div>
            <p className="acd-now__label">
              {current ? current.primary_label : "Offline"}
              {current?.secondary_status && <span className="acd-now__aux"> · {current.secondary_status}</span>}
            </p>
            <p className="muted small">
              {current ? `${current.primary_name} desde las ${fmtTime(current.start_at)}` : "Sin sesión"}
              {d.session && ` · sesión iniciada a las ${fmtTime(d.session.login_at)}`}
            </p>
          </div>
          <p className={`acd-now__timer${current?.max_minutes && elapsed > current.max_minutes * 60_000 ? " acd-now__timer--over" : ""}`} aria-live="off">
            {fmtDuration(elapsed)}
            {current?.max_minutes ? <span className="muted small"> / máx. {current.max_minutes} min</span> : null}
          </p>
        </div>
      )}

      {d?.logged_in && (
        <>
          <h2 className="section-title">Cambiar estado</h2>
          <div className="acd-options" role="group" aria-label="Estados disponibles">
            {d.options.map((o) => {
              const active = current?.primary_status === o.code && (!o.aux_codes.length || picked !== o.code);
              return (
                <button
                  key={o.code}
                  type="button"
                  className={`acd-option${active ? " acd-option--active" : ""}${picked === o.code ? " acd-option--open" : ""}`}
                  style={{ "--status-color": o.color }}
                  disabled={busy}
                  aria-pressed={active}
                  onClick={() => choose(o)}
                >
                  <span className="acd-option__label">{o.label}</span>
                  <span className="acd-option__name">
                    {o.name}
                    {o.aux_codes.length ? " ▾" : ""}
                  </span>
                </button>
              );
            })}
          </div>
          {pickedOption && (
            <div className="acd-aux form-section">
              <p className="form-section__title">
                {pickedOption.label}: elija el auxiliar
                <button type="button" className="link-button" onClick={() => run(() => presence.setStatus(pickedOption.code))} disabled={busy}>
                  Sin auxiliar
                </button>
              </p>
              <ul className="acd-aux__list">
                {pickedOption.aux_codes.map((a) => (
                  <li key={a.code}>
                    {a.children.length ? (
                      <>
                        <span className="acd-aux__parent">{a.name}</span>
                        <span className="acd-aux__children">
                          {a.children.map((c) => (
                            <button key={c.code} type="button" className="button button--ghost button--sm" disabled={busy}
                              onClick={() => run(() => presence.setStatus(pickedOption.code, c.code))}>
                              {c.name}
                              {c.max_minutes ? <span className="muted small"> · {c.max_minutes} min</span> : null}
                            </button>
                          ))}
                        </span>
                      </>
                    ) : (
                      <button type="button" className="button button--ghost button--sm" disabled={busy}
                        onClick={() => run(() => presence.setStatus(pickedOption.code, a.code))}>
                        {a.name}
                        {a.max_minutes ? <span className="muted small"> · {a.max_minutes} min</span> : null}
                        {!a.is_paid && <span className="badge badge--muted shift-grid__badge">no pagado</span>}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {d && (
        <>
          <h2 className="section-title">Mi día</h2>
          {d.today_totals_ms.length > 0 && (
            <dl className="kpis">
              {d.today_totals_ms.map((t) => (
                <div className="kpi" key={t.primary_status}>
                  <dt>{t.primary_status}</dt>
                  <dd>{fmtDuration(t.duration_ms)}</dd>
                </div>
              ))}
            </dl>
          )}
          {d.today.length === 0 ? (
            <p className="muted">Sin actividad hoy.</p>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Start Time</th>
                    <th scope="col">End Time</th>
                    <th scope="col">Primary Status</th>
                    <th scope="col">Secondary Status</th>
                    <th scope="col">Duración</th>
                  </tr>
                </thead>
                <tbody>
                  {[...d.today].reverse().map((s) => (
                    <tr key={s.id}>
                      <td>{fmtTime(s.start_at)}</td>
                      <td>{s.is_open ? "en curso" : fmtTime(s.end_at)}</td>
                      <td>
                        <span className="acd-pill" style={{ "--status-color": s.color }}>
                          {s.primary_label}
                        </span>
                      </td>
                      <td>{s.secondary_status || "—"}</td>
                      <td>{s.is_open ? fmtDuration(now + offset - new Date(s.start_at).getTime()) : fmtDuration(s.duration_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {d.last_session && (
            <p className="muted small">
              Última sesión: {fmtTime(d.last_session.login_at)}–{fmtTime(d.last_session.logout_at)} · tiempo real:{" "}
              {d.last_session.sync_status_label.toLowerCase()} ({d.last_session.sync_message})
            </p>
          )}
        </>
      )}
    </section>
  );
}
