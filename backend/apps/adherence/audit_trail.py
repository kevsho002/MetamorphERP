"""Fase 18 — Audit trail de una línea de la grilla: un agente en una FECHA DE TURNO.

Reúne, en orden cronológico, todo lo que se hizo sobre ese registro:

* cambios del plan (segmentos programados / movidos / eliminados, con el antes y el después) y justificaciones,
  desde sys_audit_event (WFM) — los eventos guardan la fecha de turno en `details.shift_dates`;
* la AP de horario que creó el pre-contenedor vigente y las AP que justifican tiempo: elaboración, envío, cada
  firma de aprobación / rechazo (pa_action_signature) y su aplicación;
* el Team Manager vigente en el roster (quién lo registró y cuándo) y la cadena de mando derivada;
* las sesiones ACD del día (inicio / cierre, quién la cerró y el envío del tiempo pagado);
* el cálculo guardado para nómina y calidad (adh_adherence_day) y el cierre del corte de asistencia.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone

from apps.acd.models import AgentSession
from apps.adherence.models import AdherenceDay, AdherenceException, ScheduleSegment
from apps.adherence.services import fmt, hm, iso
from apps.hcm.models import Employee
from apps.operations import hierarchy
from apps.operations.models import TEAM_MANAGER_ATTRIBUTE
from apps.roster.models import RosterAssignment
from apps.scheduling.services import ScheduleBook, closed_cutoff_hit
from apps.system.models import AuditEvent

MAX_EVENTS = 400
KIND_LABELS = {"change": "Cambio", "approval": "Aprobación", "action": "Acción", "system": "Sistema"}


def _local(dt: datetime | None) -> str | None:
    """Instante (aware, UTC en la BD) → ISO en hora local de la operación, al segundo."""
    if dt is None:
        return None
    if timezone.is_aware(dt):
        dt = timezone.localtime(dt)
    return dt.replace(tzinfo=None, microsecond=0).isoformat()


def _entry(at, kind: str, source: str, title: str, summary: str = "", *, actor: str = "", action: str = "",
           before=None, after=None, ref: str = "") -> dict:
    return {"at": _local(at), "kind": kind, "kind_label": KIND_LABELS[kind], "source": source, "action": action,
            "title": title, "summary": summary, "actor": actor or "", "before": before, "after": after, "ref": ref}


def _user(u, fallback: str = "") -> str:
    return getattr(u, "username", "") or fallback


def _pa_entries(pa, role: str) -> list[dict]:
    """Ciclo de vida de una AP: elaborada → enviada → firmas → aplicada."""
    label = f"AP {pa.folio} · {pa.action_type.name}"
    out = [_entry(pa.created_at, "action", "pa", f"{label}: elaborada", f"{role}. Fecha efectiva {fmt(pa.effective_date)}.",
                  actor=_user(pa.created_by), action="pa_created", ref=pa.folio)]
    if pa.submitted_at:
        out.append(_entry(pa.submitted_at, "action", "pa", f"{label}: enviada a aprobación", role, action="pa_submitted", ref=pa.folio,
                          actor=_user(pa.created_by)))
    for sig in pa.signatures.all():
        verb = "aprobada" if sig.decision == "APPROVED" else "rechazada"
        out.append(_entry(sig.signed_at, "approval", "pa", f"{label}: {verb} — paso {sig.step_order} ({sig.step_label})",
                          (f"«{sig.comment}» · " if sig.comment else "") + f"Firma {sig.signature[:12]}…",
                          actor=f"{sig.signer_name or sig.signer_username} ({sig.get_signer_role_display()})",
                          action=f"pa_{sig.decision.lower()}", ref=pa.folio))
    if pa.applied_at:
        out.append(_entry(pa.applied_at, "system", "pa", f"{label}: aplicada", f"{role}. Estado actual: {pa.get_status_display()}.",
                          action="pa_applied", ref=pa.folio))
    return out


def _wfm_events(employee: Employee, d: date) -> list[dict]:
    """Eventos de auditoría del agente que tocan la fecha de turno (los anteriores a la Fase 18 se reconocen por la fecha
    escrita en el resumen: «del dd/mm/aaaa»)."""
    iso_d, text_d = d.isoformat(), fmt(d)
    qs = (AuditEvent.objects.filter(target_type="employee", target_id=employee.employee_code, category=AuditEvent.Category.WFM)
          .order_by("-occurred_at")[:2000])
    out = []
    for ev in qs:
        det = ev.details or {}
        dates = det.get("shift_dates") or ([det["shift_date"]] if det.get("shift_date") else [])
        if iso_d not in dates and not (not dates and text_d in ev.summary):
            continue
        kind = _WFM_KINDS.get(ev.action, "change")
        out.append(_entry(ev.occurred_at, kind, "wfm", _WFM_TITLES.get(ev.action, ev.action), ev.summary,
                          actor=ev.actor_username or "sistema", action=ev.action, before=det.get("before"), after=det.get("after"),
                          ref=str(det.get("segment_id") or det.get("folio") or "")))
    return out


_WFM_TITLES = {
    "adh_segment_created": "Segmento programado",
    "adh_segment_updated": "Segmento modificado / movido",
    "adh_segment_deleted": "Segmento eliminado",
    "adh_exception_created": "Justificación registrada",
    "adh_exception_deleted": "Justificación eliminada",
    "adh_day_recomputed": "Adherencia guardada recalculada",
    # Fase 19
    "adh_segment_replaced": "Lateness / ausencia reemplazado con AP",
    "adh_lateness_detected": "Lateness detectado (inicio de sesión tardío)",
    "adh_absence_detected": "Unjustified Absence (no-show) + Legal Benefit Lunch",
    "adh_request_created": "Solicitud de corrección enviada a la cola de WFM",
    "adh_request_approved": "Solicitud aprobada por WFM",
    "adh_request_rejected": "Solicitud rechazada por WFM",
    "adh_request_cancelled": "Solicitud anulada",
}
_WFM_KINDS = {
    "adh_day_recomputed": "system", "adh_lateness_detected": "system", "adh_absence_detected": "system",
    "adh_request_created": "action", "adh_request_cancelled": "action",
    "adh_request_approved": "approval", "adh_request_rejected": "approval",
}


def _bulk_events(employee: Employee, d: date) -> list[dict]:
    """Programación masiva que incluyó al agente en un rango con la fecha."""
    out = []
    iso_d = d.isoformat()
    for ev in AuditEvent.objects.filter(action="adh_segment_bulk").order_by("-occurred_at")[:300]:
        det = ev.details or {}
        if employee.employee_code in (det.get("employees") or []) and det.get("date_from", "9") <= iso_d <= det.get("date_to", ""):
            out.append(_entry(ev.occurred_at, "change", "wfm", "Programación masiva", ev.summary, actor=ev.actor_username or "sistema",
                              action=ev.action))
    return out


def audit_trail(employee: Employee, d: date) -> dict:
    entries: list[dict] = []
    entries += _wfm_events(employee, d)
    entries += _bulk_events(employee, d)

    # Segmentos vigentes sin evento propio (creados antes de esta auditoría detallada).
    seen = {e["ref"] for e in entries if e["source"] == "wfm"}
    segments = list(ScheduleSegment.objects.filter(employee=employee, shift_date=d).select_related("activity", "created_by"))
    for s in segments:
        if str(s.pk) not in seen:
            entries.append(_entry(s.created_at, "change", "wfm", "Segmento programado",
                                  f"{s.activity.name} {hm(s.start_at)}–{hm(s.end_at)} (sin detalle previo en la auditoría).",
                                  actor=_user(s.created_by, "—"), action="adh_segment_created", ref=str(s.pk)))

    # Pre-contenedor: AP(s) de horario vigentes en la fecha.
    book = ScheduleBook([employee.pk], d, d)
    schedule_aps = []
    for a in book.assignments_on(employee.pk, d):
        if a.personnel_action_id:
            schedule_aps.append(a.personnel_action_id)
        else:
            entries.append(_entry(a.created_at, "action", "schedule", "Horario registrado sin AP",
                                  f"Vigente desde {fmt(a.effective_start_date)}.", actor=_user(a.created_by)))
    # AP que justifican tiempo ese día.
    day0 = datetime.combine(d, time())
    just = list(AdherenceException.objects.filter(employee=employee, start_at__lt=day0 + timedelta(days=2),
                                                  end_at__gt=day0 - timedelta(hours=12)).select_related("personnel_action", "created_by"))
    from apps.personnel_actions.models import PersonnelAction

    pa_ids = set(schedule_aps) | {x.personnel_action_id for x in just}
    pas = {pa.pk: pa for pa in PersonnelAction.objects.filter(pk__in=pa_ids).select_related("action_type", "created_by")
           .prefetch_related("signatures")}
    for pk in schedule_aps:
        if pk in pas:
            entries += _pa_entries(pas[pk], "AP de horario: crea el pre-contenedor (turno) de esta fecha")
    for x in just:
        pa = pas.get(x.personnel_action_id)
        if pa and pa.pk not in schedule_aps:
            entries += _pa_entries(pa, f"Justifica {hm(x.start_at)}–{hm(x.end_at)}")
            schedule_aps.append(pa.pk)  # una AP con varias justificaciones se lista una vez

    # Roster: Team Manager vigente (y sus correcciones).
    tm_rows = (RosterAssignment.objects.filter(employee=employee, attribute__code=TEAM_MANAGER_ATTRIBUTE, effective_start__lte=d)
               .filter(Q(effective_end__isnull=True) | Q(effective_end__gte=d)).select_related("item").order_by("recorded_at"))
    for r in tm_rows:
        label = r.item.name if r.item_id else r.value
        entries.append(_entry(r.recorded_at, "change", "roster", f"Roster: Team Manager {label}",
                              f"Vigente {fmt(r.effective_start)} → {fmt(r.effective_end) if r.effective_end else 'Now'}"
                              + (f" · «{r.reason}»" if r.reason else ""), actor=r.recorded_by, action="roster_change"))
        if r.superseded_at:
            entries.append(_entry(r.superseded_at, "change", "roster", f"Roster: Team Manager {label} corregido",
                                  "La asignación fue reemplazada por una corrección.", actor=r.superseded_by, action="roster_superseded"))

    # Sesiones ACD del día (hora local).
    lo, hi = timezone.make_aware(day0 - timedelta(hours=6)), timezone.make_aware(day0 + timedelta(hours=30))
    for s in AgentSession.objects.filter(employee=employee, login_at__lt=hi).filter(Q(logout_at__isnull=True) | Q(logout_at__gt=lo)).select_related("group"):
        entries.append(_entry(s.login_at, "action", "acd", "ACD: inicio de sesión", f"Grupo {s.group.name}.", action="acd_login"))
        if s.logout_at:
            entries.append(_entry(s.logout_at, "action", "acd", "ACD: cierre de sesión",
                                  f"Cerrada por: {s.get_logout_source_display() or '—'} · tiempo pagado enviado: {s.paid_minutes} min"
                                  f" ({s.get_sync_status_display()})" + (f" · {s.sync_message}" if s.sync_message else ""),
                                  action="acd_logout"))

    # Resultado guardado y cierre del corte.
    stored = AdherenceDay.objects.filter(employee=employee, shift_date=d).select_related("computed_by").first()
    if stored:
        entries.append(_entry(stored.computed_at, "system", "adherence", "Adherencia guardada para nómina y calidad",
                              f"Adherencia {stored.adherence_pct if stored.adherence_pct is not None else '—'} % · programado "
                              f"{stored.scheduled_seconds} s · en adherencia {stored.in_adherence_seconds} s · Unpaid Excess Login "
                              f"{stored.unpaid_excess_seconds} s.", actor=_user(stored.computed_by, "sistema"), action="adh_computed"))
    cutoff = closed_cutoff_hit(employee, d, d)
    if cutoff:
        entries.append(_entry(cutoff.closed_at, "approval", "cutoff", f"Corte {cutoff.code} cerrado",
                              f"Asistencia del {fmt(cutoff.cutoff_start)} al {fmt(cutoff.cutoff_end)}: la fecha queda congelada.",
                              actor=_user(cutoff.closed_by), action="cutoff_closed"))

    entries = [e for e in entries if e["at"]]
    entries.sort(key=lambda e: e["at"], reverse=True)
    chain = hierarchy.agent_hierarchy([employee.pk], d).get(employee.pk)
    counts = {k: sum(1 for e in entries if e["kind"] == k) for k in KIND_LABELS}
    return {
        "employee_code": employee.employee_code, "full_name": employee.full_name, "date": d.isoformat(),
        "hierarchy": chain, "frozen": bool(cutoff), "cutoff": cutoff.code if cutoff else None,
        "segments": [{"id": s.pk, "activity": s.activity.code, "activity_name": s.activity.name, "start": iso(s.start_at),
                      "end": iso(s.end_at), "seconds": s.seconds} for s in sorted(segments, key=lambda s: s.start_at)],
        "counts": counts, "truncated": len(entries) > MAX_EVENTS, "entries": entries[:MAX_EVENTS],
    }
