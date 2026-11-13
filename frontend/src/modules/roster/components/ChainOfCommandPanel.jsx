import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { leadersApi } from "../api.js";
import { LeaderEdit, LeaderNew } from "../pages/ChainOfCommandPage.jsx";

const AGENT_CHAIN = [
  ["TEAM_MANAGER", "Team Manager", "asignado en este roster"],
  ["ACCOUNT_SUPERVISOR", "Account Supervisor", "derivado"],
  ["OPS_MANAGER", "Operations Manager", "derivado"],
  ["OPS_DIRECTOR", "Operations Director", "derivado"],
];

/**
 * Cadena de mando dentro del roster del colaborador (Fase 18): como AGENTE, su Team Manager (atributo temporal del
 * roster) y los niveles derivados; como LÍDER, su rol, a quién reporta y cuántos le reportan. Desde aquí se registra
 * o se edita su rol de líder sin salir del roster.
 */
export default function ChainOfCommandPanel({ employee, chain, canManage, onChanged }) {
  const [leaders, setLeaders] = useState(null);
  const [mode, setMode] = useState(null); // "new" | id del rol en edición
  const [notice, setNotice] = useState(null);

  const load = useCallback(() => {
    leadersApi
      .list({ include_inactive: 1 })
      .then(setLeaders)
      .catch((err) => setNotice({ ok: false, text: err.message }));
  }, []);
  useEffect(() => {
    if (mode !== null && !leaders) load();
  }, [mode, leaders, load]);

  const done = (b) => {
    setNotice({ ok: true, text: b.feedback });
    setMode(null);
    setLeaders(null);
    onChanged();
  };
  const fail = (err) => setNotice({ ok: false, text: err.message, errors: err.body?.errors });
  const asAgent = chain?.as_agent;
  const roles = chain?.roles ?? [];

  return (
    <section className="detail-section roster-chain" aria-labelledby="roster-chain-title">
      <header className="roster-chain__head">
        <h3 id="roster-chain-title" className="section-title">
          Cadena de mando
        </h3>
        <Link to={`/roster/hierarchy?employee=${employee.employee_code}`} className="link-button">
          Ver organigrama
        </Link>
      </header>
      {notice && (
        <div className={`alert ${notice.ok ? "alert--ok" : "alert--error"}`} role="status">
          <p className="alert__text">
            {notice.text}
            {notice.errors && ` ${Object.values(notice.errors).join(" ")}`}
          </p>
        </div>
      )}
      <div className="roster-chain__grid">
        <div>
          <h4 className="roster-chain__sub">Como agente</h4>
          {asAgent ? (
            <ol className="roster-chain__list">
              {AGENT_CHAIN.map(([lvl, label, how]) => (
                <li key={lvl}>
                  <span className="muted small">{label}</span>
                  <strong>{asAgent[lvl]?.full_name ?? "—"}</strong>
                  <span className="muted small">{how}</span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="muted small">Sin Team Manager en el roster a esta fecha. Asígnelo con «Registrar cambios» (dato «Team Manager»).</p>
          )}
        </div>
        <div>
          <h4 className="roster-chain__sub">Como líder</h4>
          {roles.length === 0 && <p className="muted small">No tiene un rol en la cadena de mando.</p>}
          {roles.map((r) => (
            <div key={r.id} className={`org__card roster-chain__role${r.is_active ? "" : " is-inactive"}`}>
              <span className={`org__level org__level--${r.level.toLowerCase()}`}>{r.level_label}</span>
              <span className="small">
                {r.reports_to_name ? `Reporta a ${r.reports_to_name}` : "Nivel superior"}
                {r.chain.length > 1 ? ` (${r.chain.slice(1).map((c) => c.full_name).join(" → ")})` : ""}
                {` · ${r.subordinates} líder(es) a cargo`}
                {r.agents !== undefined && r.agents !== null ? ` · ${r.agents} agente(s)` : ""}
                {r.client_name ? ` · ${r.client_name}` : ""}
                {!r.is_active ? " · inactivo" : ""}
              </span>
              {canManage && (
                <button type="button" className="link-button" onClick={() => setMode(mode === r.id ? null : r.id)}>
                  {mode === r.id ? "Cerrar" : "Editar"}
                </button>
              )}
              {mode === r.id && leaders && <LeaderEdit lead={r} leaders={leaders.results} data={leaders} onDone={done} onError={fail} />}
            </div>
          ))}
          {canManage && mode !== "new" && (
            <button type="button" className="button button--ghost button--sm" onClick={() => setMode("new")}>
              Asignar rol de líder
            </button>
          )}
        </div>
      </div>
      {mode === "new" && leaders && (
        <LeaderNew data={leaders} leaders={leaders.results} employeeCode={employee.employee_code} fixedEmployee
          title={`Asignar rol de líder a ${employee.full_name ?? employee.employee_code}`} onDone={done} onError={fail} />
      )}
    </section>
  );
}
