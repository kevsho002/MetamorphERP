"""Fase 21 — Ciclo de vida del colaborador mediante AP: suspensiones, terminaciones / renuncias y reingresos.

* Suspensión disciplinaria (efecto SUSPENSION): el colaborador queda INACTIVO del día efectivo durante los días
  indicados (sin goce de salario: la planilla no paga esas horas) y su antigüedad se CONGELA esos días. Al terminar,
  `sync_statuses` lo devuelve a ACTIVO (tarea diaria `apply_due_personnel_actions`).
* Terminación / renuncia (efecto TERMINATION): estado TERMINADO con fecha de terminación = fecha efectiva (último
  día laborado). Guarda el indicador INTERNO de recomendación de recontratación (visible solo para RRHH) y abre la
  liquidación del colaborador (Fase 21, módulo de liquidaciones).
* Reingreso (efecto REHIRE): reactiva a un colaborador TERMINADO; la fecha efectiva es su nueva fecha de ingreso
  (la antigüedad se reinicia). Si su última terminación NO lo recomendó, la validación emite una alerta formal con su
  historial y el generalista debe reconocerla expresamente para continuar.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Q
from django.utils import timezone

from apps.hcm.models import Employee
from apps.personnel_actions.models import EmploymentEvent, PersonnelAction, Status, TerminationReason

REHIRE_ALERT = "rehire_not_recommended"
Kind = EmploymentEvent.Kind


def fmt(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


# ================================================================ antigüedad
def _overlap(a1: date, b1: date, a2: date, b2: date) -> int:
    lo, hi = max(a1, a2), min(b1, b2)
    return (hi - lo).days + 1 if lo <= hi else 0


def suspended_days(employee: Employee, start: date, end: date, events=None) -> int:
    events = events if events is not None else EmploymentEvent.objects.filter(employee=employee, kind=Kind.SUSPENSION)
    return sum(_overlap(e.start_date, e.end_date, start, end) for e in events if e.kind == Kind.SUSPENSION and e.end_date)


def suspended_dates(employee_ids, lo: date, hi: date) -> dict[int, set[date]]:
    """Días de suspensión por colaborador dentro del rango (la planilla no los paga ni los programa)."""
    out: dict[int, set[date]] = {}
    for e in EmploymentEvent.objects.filter(employee_id__in=list(employee_ids), kind=Kind.SUSPENSION, start_date__lte=hi, end_date__gte=lo):
        d = max(e.start_date, lo)
        while d <= min(e.end_date, hi):
            out.setdefault(e.employee_id, set()).add(d)
            d += timedelta(days=1)
    return out


def _ymd(days: int) -> dict:
    years, rest = divmod(max(days, 0), 365)
    months, rest = divmod(rest, 30)
    return {"years": years, "months": months, "remainder_days": rest}


def tenure(employee: Employee, on: date | None = None, events=None) -> dict:
    """Antigüedad VIGENTE: desde la fecha de ingreso actual hasta hoy (o la terminación) menos los días suspendidos."""
    on = on or timezone.localdate()
    end = min(on, employee.termination_date) if employee.termination_date else on
    if end < employee.hire_date:
        return {"start": employee.hire_date, "end": end, "calendar_days": 0, "suspended_days": 0, **_ymd(0), "days": 0,
                "years_decimal": 0.0, "frozen": False, "label": "Aún no inicia"}
    calendar = (end - employee.hire_date).days + 1
    frozen = suspended_days(employee, employee.hire_date, end, events)
    days = calendar - frozen
    ymd = _ymd(days)
    parts = [f"{ymd['years']} año(s)" if ymd["years"] else "", f"{ymd['months']} mes(es)" if ymd["months"] else "",
             f"{ymd['remainder_days']} día(s)" if ymd["remainder_days"] or not (ymd["years"] or ymd["months"]) else ""]
    current = active_suspension(employee, on, events)
    return {
        "start": employee.hire_date, "end": end, "calendar_days": calendar, "suspended_days": frozen, **ymd, "days": days,
        "years_decimal": round(days / 365.25, 2), "frozen": current is not None,
        "label": " ".join(p for p in parts if p),
    }


def active_suspension(employee: Employee, on: date, events=None) -> EmploymentEvent | None:
    events = events if events is not None else EmploymentEvent.objects.filter(employee=employee, kind=Kind.SUSPENSION)
    return next((e for e in events if e.kind == Kind.SUSPENSION and e.start_date <= on <= e.end_date), None)


# ================================================================ historial y alerta de recontratación
def last_termination(employee: Employee) -> EmploymentEvent | None:
    return EmploymentEvent.objects.filter(employee=employee, kind=Kind.TERMINATION).order_by("-start_date", "-id").first()


def event_dict(e: EmploymentEvent, *, hr: bool) -> dict:
    body = {
        "id": e.pk, "kind": e.kind, "kind_label": e.get_kind_display(), "start_date": e.start_date, "end_date": e.end_date,
        "folio": e.action.folio if e.action_id else None,
        "days": (e.end_date - e.start_date).days + 1 if e.end_date else None,
        "previous_hire_date": e.previous_hire_date, "previous_termination_date": e.previous_termination_date,
        "reactivated_at": e.reactivated_at,
    }
    if e.kind == Kind.TERMINATION:
        body["termination_reason"] = e.termination_reason
        body["termination_reason_label"] = e.get_termination_reason_display() if e.termination_reason else ""
    if hr:  # indicador interno: solo Recursos Humanos
        body["rehire_eligible"] = e.rehire_eligible
        body["hr_notes"] = e.hr_notes
        body["rehire_acknowledged"] = e.rehire_acknowledged
    return body


def history(employee: Employee, *, hr: bool) -> list[dict]:
    events = EmploymentEvent.objects.filter(employee=employee).select_related("action").order_by("start_date", "id")
    return [event_dict(e, hr=hr) for e in events]


def rehire_alert(employee: Employee) -> dict | None:
    """Alerta formal si la última terminación NO recomendó la recontratación: historial y antecedentes."""
    last = last_termination(employee)
    if last is None or last.rehire_eligible is not False:
        return None
    events = list(EmploymentEvent.objects.filter(employee=employee).select_related("action").order_by("start_date", "id"))
    suspensions = [e for e in events if e.kind == Kind.SUSPENSION]
    terminations = [e for e in events if e.kind == Kind.TERMINATION]
    lines = [
        f"Última terminación: {fmt(last.start_date)} — {last.get_termination_reason_display() or 'sin motivo'}"
        + (f" (AP {last.action.folio})" if last.action_id else "") + ".",
        "Indicador de RRHH: NO recomendable para recontratación." + (f" Observaciones: {last.hr_notes}" if last.hr_notes else ""),
        f"Antecedentes: {len(terminations)} terminación(es), {len(suspensions)} suspensión(es) disciplinaria(s) "
        f"({sum((e.end_date - e.start_date).days + 1 for e in suspensions)} días).",
    ]
    return {
        "code": REHIRE_ALERT,
        "message": (f"ALERTA FORMAL: {employee.employee_code} {employee.full_name} NO fue recomendado para recontratación en su "
                    f"terminación del {fmt(last.start_date)}. Puede continuar con el reingreso solo si un generalista autorizado "
                    "revisa sus antecedentes y lo reconoce expresamente."),
        "details": lines,
        "history": [event_dict(e, hr=True) for e in events],
    }


# ================================================================ validación por efecto
def validate_effect(check, action_type, employee: Employee, eff: date | None, values: dict, data: dict, *,
                    instance: PersonnelAction | None, enforce_ack: bool) -> None:
    from apps.personnel_actions.models import Effect

    effect = action_type.effect
    if eff is None or not check.ok:
        return
    if effect == Effect.SUSPENSION:
        days = values.get("dias", (None, None))[1]
        if "dias" not in values:
            check.error(None, f"El tipo «{action_type.name}» suspende pero no tiene el campo «dias». Corríjalo en /admin/.", "config")
            return
        if employee.employment_status == Employee.Status.TERMINATED:
            check.error("employee_code", "El colaborador está terminado: no se suspende.", "terminated")
            return
        if days:
            end = eff + timedelta(days=int(days) - 1)
            if employee.termination_date and end > employee.termination_date:
                check.error("values.dias", f"La suspensión terminaría después de la terminación ({fmt(employee.termination_date)}).")
            clash = EmploymentEvent.objects.filter(employee=employee, kind=Kind.SUSPENSION, start_date__lte=end, end_date__gte=eff).first()
            if clash:
                check.error("effective_date", f"Se cruza con la suspensión del {fmt(clash.start_date)} al {fmt(clash.end_date)}.", "overlap")
            pending = PersonnelAction.objects.filter(employee=employee, action_type__effect=Effect.SUSPENSION, status=Status.PENDING)
            if instance is not None:
                pending = pending.exclude(pk=instance.pk)
            if pending.exists():
                check.warn(None, f"El colaborador tiene otra suspensión en aprobación ({pending.first().folio}).", "pending_suspension")
            if eff < timezone.localdate():
                check.warn("effective_date", "La suspensión es retroactiva: la planilla de esos días ya pudo haberse calculado.", "retroactive")
            check.cleaned["suspension_end"] = end
    elif effect == Effect.TERMINATION:
        for key in ("motivo_terminacion", "recomendable_recontratacion"):
            if key not in values:
                check.error(None, f"El tipo «{action_type.name}» no tiene el campo «{key}». Corríjalo en /admin/.", "config")
                return
        if employee.employment_status == Employee.Status.TERMINATED:
            check.error("employee_code", f"El colaborador ya está terminado desde el {fmt(employee.termination_date)}.", "terminated")
            return
        open_term = PersonnelAction.objects.filter(employee=employee, action_type__effect=Effect.TERMINATION,
                                                   status__in=[Status.DRAFT, Status.PENDING])
        if instance is not None:
            open_term = open_term.exclude(pk=instance.pk)
        if open_term.exists():
            check.error("action_type", f"Ya hay una terminación en trámite ({open_term.first().folio}).", "duplicate")
        if values["recomendable_recontratacion"][1] is False:
            check.warn("values.recomendable_recontratacion", "El colaborador quedará marcado como NO recomendable para recontratación "
                       "(indicador interno de RRHH).", "not_rehirable")
    elif effect == Effect.REHIRE:
        if employee.employment_status != Employee.Status.TERMINATED or not employee.termination_date:
            check.error("employee_code", "Solo se reingresa a un colaborador TERMINADO (ya laboró en la empresa).", "not_terminated")
            return
        if eff <= employee.termination_date:
            check.error("effective_date", f"La nueva fecha de ingreso debe ser posterior a la terminación ({fmt(employee.termination_date)}).")
            return
        if "new_base_salary" in values and (values["new_base_salary"][1] or 0) <= 0:
            check.error("values.new_base_salary", "El salario del reingreso debe ser mayor que cero.")
        alert = rehire_alert(employee)
        if alert:
            check.warnings.append({"field": None, "message": alert["message"], "code": REHIRE_ALERT, "details": alert["details"],
                                   "history": alert["history"]})
            acknowledged = REHIRE_ALERT in (data.get("acknowledge") or [])
            check.cleaned["rehire_acknowledged"] = acknowledged
            if enforce_ack and not acknowledged:
                check.error("acknowledge", "Revise la alerta formal de recontratación y reconózcala para continuar con el reingreso.",
                            "ack_required")


# ================================================================ aplicación del efecto
def apply(action: PersonnelAction, values: dict, *, user=None, today: date) -> str | None:
    """Ejecuta el efecto de ciclo de vida. Devuelve el resumen o None si espera su fecha efectiva."""
    from apps.personnel_actions.models import Effect

    effect = action.action_type.effect
    employee = Employee.objects.get(pk=action.employee_id)
    actor = user if getattr(user, "pk", None) else None
    if effect == Effect.SUSPENSION:
        days = int(values["dias"].value_decimal)
        end = action.effective_date + timedelta(days=days - 1)
        EmploymentEvent.objects.create(employee=employee, kind=Kind.SUSPENSION, start_date=action.effective_date, end_date=end,
                                       action=action, created_by=actor)
        sync_statuses(today, employee_ids=[employee.pk])
        return (f"Suspensión de {employee.employee_code} por {days} día(s): del {fmt(action.effective_date)} al {fmt(end)} "
                f"(inactivo; antigüedad congelada) — AP {action.folio}.")
    if action.effective_date > today:
        return None  # terminación / reingreso futuros: los aplica apply_due_actions en su fecha
    if effect == Effect.TERMINATION:
        reason = values["motivo_terminacion"].value_text or ""
        eligible = bool(values["recomendable_recontratacion"].value_bool)
        notes = values["observaciones_rrhh"].value_text if "observaciones_rrhh" in values else ""
        Employee.objects.filter(pk=employee.pk).update(employment_status=Employee.Status.TERMINATED,
                                                       termination_date=action.effective_date)
        EmploymentEvent.objects.create(employee=employee, kind=Kind.TERMINATION, start_date=action.effective_date, action=action,
                                       termination_reason=reason, rehire_eligible=eligible, hr_notes=notes or "",
                                       previous_hire_date=employee.hire_date, created_by=actor)
        try:
            from apps.payroll.settlements import open_from_termination

            open_from_termination(action, user=user)
        except ImportError:  # pragma: no cover - módulo de liquidaciones no instalado
            pass
        return f"{employee.employee_code} terminado el {fmt(action.effective_date)} (AP {action.folio}); liquidación abierta."
    if effect == Effect.REHIRE:
        salary = values["new_base_salary"].value_decimal
        last = last_termination(employee)
        EmploymentEvent.objects.create(
            employee=employee, kind=Kind.REHIRE, start_date=action.effective_date, action=action,
            previous_hire_date=employee.hire_date, previous_termination_date=employee.termination_date,
            rehire_acknowledged=bool(last and last.rehire_eligible is False), created_by=actor)
        Employee.objects.filter(pk=employee.pk).update(
            employment_status=Employee.Status.ACTIVE, termination_date=None, hire_date=action.effective_date, base_salary=salary)
        return (f"{employee.employee_code} reingresó el {fmt(action.effective_date)} (AP {action.folio}): antigüedad desde la nueva "
                f"fecha de ingreso.")
    return None


def sync_statuses(today: date | None = None, employee_ids=None) -> dict:
    """INACTIVO durante una suspensión vigente; ACTIVO de nuevo cuando terminan todas (solo si la suspensión lo inactivó)."""
    today = today or timezone.localdate()
    qs = EmploymentEvent.objects.filter(kind=Kind.SUSPENSION, start_date__lte=today)
    if employee_ids is not None:
        qs = qs.filter(employee_id__in=list(employee_ids))
    suspended, reactivated = [], []
    current = qs.filter(end_date__gte=today).values_list("employee_id", flat=True)
    for e in Employee.objects.filter(pk__in=list(current), employment_status=Employee.Status.ACTIVE):
        Employee.objects.filter(pk=e.pk).update(employment_status=Employee.Status.INACTIVE)
        suspended.append(e.employee_code)
    ended = qs.filter(end_date__lt=today, reactivated_at__isnull=True).exclude(employee_id__in=list(current))
    for ev in ended.select_related("employee"):
        if ev.employee.employment_status == Employee.Status.INACTIVE:
            Employee.objects.filter(pk=ev.employee_id).update(employment_status=Employee.Status.ACTIVE)
            reactivated.append(ev.employee.employee_code)
        EmploymentEvent.objects.filter(pk=ev.pk).update(reactivated_at=timezone.now())
    return {"suspended": suspended, "reactivated": sorted(set(reactivated))}


def employees_on_suspension(on: date) -> Q:
    return Q(employment_events__kind=Kind.SUSPENSION, employment_events__start_date__lte=on, employment_events__end_date__gte=on)


TERMINATION_REASONS = dict(TerminationReason.choices)
