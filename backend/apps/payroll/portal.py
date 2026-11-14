"""Fase 21 — Pre-cierre de planilla: boletas preliminares en el portal del colaborador, excepciones reportadas a su
supervisor, corridas diarias automáticas y reglas por cuenta (séptimo día opcional).

* Mientras la planilla está abierta, cada corrida del motor (manual o diaria desde N días antes del fin del corte)
  publica la BOLETA PRELIMINAR del colaborador en su portal («Mis boletas»), con la marca «preliminar».
* El agente reporta excepciones (horas no reflejadas, nocturnidad, feriado, Lateness mal marcado…) que van a su Team
  Manager vigente (roster «team_manager»); la resuelve el supervisor o Planillas. El cierre (freeze) exige que no queden
  excepciones abiertas.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.permissions import user_permissions
from apps.accounts.roles import Perm
from apps.hcm.models import Employee
from apps.payroll.models import (
    PayrollAccountRule, PayrollDay, PayrollDetail, PayrollException, PayrollIteration, PayrollRun, PayrollSetting, Payslip,
)
from apps.payroll.services import (
    CLOSED_STATUSES, PayrollError, _h, calculate, day_dict, employee_breakdown, money, setting_for,
)
from apps.scheduling.models import AttendanceCutoff, PayPeriod
from apps.system.audit import record
from apps.system.models import AuditEvent

Category = AuditEvent.Category
X = PayrollException.Status


def fmt(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


def my_employee(user) -> Employee | None:
    return getattr(user, "employee", None) if getattr(user, "employee_id", None) else None


# ================================================================ portal del colaborador
def my_payslips(user, *, year=None, page=1, page_size=6) -> dict:
    """Boletas del colaborador: preliminares (planillas calculadas y publicadas, aún abiertas) y finales (cerradas)."""
    e = my_employee(user)
    if e is None:
        raise PayrollError("Su usuario no está vinculado a un colaborador: no tiene boletas.", "no_employee", 404)
    preliminary = []
    details = (PayrollDetail.objects.filter(employee=e, payroll__payroll_status="CALCULATED")
               .select_related("payroll").order_by("-payroll__period_end"))
    for d in details:
        run = PayrollRun.objects.filter(payroll=d.payroll).select_related("payroll", "pay_period", "pay_period__cycle").first()
        if run is None or run.preliminary_published_at is None:
            continue
        b = employee_breakdown(run, e.employee_code)
        b["preliminary"] = True
        b["exceptions"] = [exception_dict(x) for x in PayrollException.objects.filter(payroll=d.payroll, employee=e)]
        preliminary.append(b)
    # Fase 27: boletas finales paginadas y filtrables por año de pago.
    slips = Payslip.objects.filter(employee=e)
    final_years = sorted({d.year for d in slips.values_list("period_end", flat=True)}, reverse=True)
    try:
        year = int(year) if year not in (None, "") else None
    except (TypeError, ValueError):
        raise PayrollError("Año inválido.", "invalid", 400) from None
    if year is not None:
        slips = slips.filter(period_end__year=year)
    try:
        page_size = int(page_size) if int(page_size) in CUTOFF_PAGE_SIZES else 6
    except (TypeError, ValueError):
        page_size = 6
    count = slips.count()
    pages = max(1, -(-count // page_size))
    try:
        page = min(max(1, int(page)), pages)
    except (TypeError, ValueError):
        page = 1
    finals = [{"id": s.pk, "folio": s.folio, "payroll_code": s.content.get("payroll_code"), "period_start": s.period_start,
               "period_end": s.period_end, "payment_date": s.payment_date, "net_pay": s.net_pay, "content": s.content,
               "content_hash": s.content_hash}
              for s in slips.order_by("-period_end")[(page - 1) * page_size: page * page_size]]
    return {"employee": {"code": e.employee_code, "name": e.full_name}, "preliminary": preliminary, "final": finals,
            "final_page": {"year": year, "years": final_years, "count": count, "page": page, "pages": pages,
                           "page_size": page_size},
            "categories": [{"value": v, "label": label} for v, label in PayrollException.Category.choices]}


CUTOFF_PAGE_SIZES = (3, 6, 12, 24)


def my_cutoffs(user, *, year=None, page=1, page_size=6) -> dict:
    """Fase 27 — Historial de la boleta por CORTE interno de asistencia, paginado y filtrable por año.

    Lista cada corte del ciclo del colaborador en el que estuvo activo (ventana del corte ∩ [ingreso, baja u hoy]),
    del más reciente al más antiguo, con su desglose diario cuando la planilla que lo paga ya está cerrada (FINAL) o
    tiene la boleta preliminar publicada (PRELIMINAR). Los cortes aún sin cálculo publicado aparecen como PENDIENTE.
    """
    from apps.scheduling.services import cycle_for

    e = my_employee(user)
    if e is None:
        raise PayrollError("Su usuario no está vinculado a un colaborador: no tiene boletas.", "no_employee", 404)
    cycle = cycle_for(e)
    today = timezone.localdate()
    last = min(e.termination_date or today, today)
    qs = AttendanceCutoff.objects.none()
    if cycle is not None and e.hire_date and e.hire_date <= last:
        qs = (AttendanceCutoff.objects.filter(cycle=cycle, cutoff_end__gte=e.hire_date, cutoff_start__lte=last)
              .select_related("pay_period"))
    years = sorted({c.year for c in qs.values_list("cutoff_end", flat=True)}, reverse=True)
    try:
        year = int(year) if year not in (None, "") else None
    except (TypeError, ValueError):
        raise PayrollError("Año inválido.", "invalid", 400) from None
    if year is not None:
        qs = qs.filter(cutoff_end__year=year)
    try:
        page_size = int(page_size)
    except (TypeError, ValueError):
        page_size = 6
    page_size = page_size if page_size in CUTOFF_PAGE_SIZES else 6
    count = qs.count()
    pages = max(1, -(-count // page_size))
    try:
        page = min(max(1, int(page)), pages)
    except (TypeError, ValueError):
        page = 1
    cutoffs = list(qs.order_by("-cutoff_start")[(page - 1) * page_size: page * page_size])

    rows = []
    if cutoffs:
        lo, hi = min(c.cutoff_start for c in cutoffs), max(c.cutoff_end for c in cutoffs)
        days = list(PayrollDay.objects.filter(employee=e, work_date__range=(lo, hi))
                    .select_related("payroll").order_by("work_date"))
        calc_ids = {d.payroll_id for d in days if d.payroll.payroll_status == "CALCULATED"}
        published = set(PayrollRun.objects.filter(payroll_id__in=calc_ids, preliminary_published_at__isnull=False)
                        .values_list("payroll_id", flat=True))
        visible = [d for d in days if d.payroll.payroll_status in CLOSED_STATUSES or d.payroll_id in published]
        for c in cutoffs:
            mine = [d for d in visible if c.cutoff_start <= d.work_date <= c.cutoff_end
                    and (not d.cutoff_code or d.cutoff_code == c.code)]
            final = any(d.payroll.payroll_status in CLOSED_STATUSES for d in mine)
            if final:  # un corte pagado en planilla cerrada no mezcla días de una preliminar posterior
                mine = [d for d in mine if d.payroll.payroll_status in CLOSED_STATUSES]
            state = "FINAL" if final else ("PRELIMINARY" if mine else "PENDING")
            payroll = mine[0].payroll if mine else None
            rows.append({
                "id": c.pk, "code": c.code, "start": c.cutoff_start, "end": c.cutoff_end, "status": c.status,
                "status_label": c.get_status_display(), "state": state,
                "state_label": {"FINAL": "Pagado (boleta final)", "PRELIMINARY": "Preliminar",
                                "PENDING": "Pendiente de cálculo"}[state],
                "pay_period": {"code": c.pay_period.code, "payment_date": c.pay_period.payment_date},
                "payroll_code": payroll.payroll_code if payroll else None,
                "currency": payroll.currency_code if payroll else None,
                "scheduled_h": _h(sum(d.scheduled_seconds for d in mine)), "paid_h": _h(sum(d.paid_seconds for d in mine)),
                "total": money(sum((d.total_amount for d in mine), Decimal(0))),
                "days": [day_dict(d) for d in mine],
            })
    return {"employee": {"code": e.employee_code, "name": e.full_name}, "year": year, "years": years, "count": count,
            "page": page, "pages": pages, "page_size": page_size, "results": rows}


def team_manager_code(employee: Employee, on: date) -> str:
    from apps.operations.hierarchy import agent_hierarchy

    tm = (agent_hierarchy([employee.pk], on).get(employee.pk) or {}).get("TEAM_MANAGER")
    return tm["employee_code"] if tm else ""


@transaction.atomic
def report_exception(user, data: dict, *, request=None) -> PayrollException:
    from apps.personnel_actions.services import parse_date

    e = my_employee(user)
    if e is None:
        raise PayrollError("Su usuario no está vinculado a un colaborador.", "no_employee", 404)
    detail = PayrollDetail.objects.filter(employee=e, payroll_id=data.get("payroll_id")).select_related("payroll").first()
    if detail is None:
        raise PayrollError("No aparece en esa planilla.", "not_found", 404)
    if detail.payroll.payroll_status != "CALCULATED":
        raise PayrollError("La planilla ya está cerrada (freeze): las excepciones se reportan antes del cierre.", "closed")
    category = str(data.get("category") or "HOURS").upper()
    if category not in PayrollException.Category.values:
        raise PayrollError("Tipo de excepción inválido.", "invalid", 400)
    text = str(data.get("description") or "").strip()
    if len(text) < 10:
        raise PayrollError("Describa la excepción (al menos 10 caracteres).", "invalid", 400)
    work_date = parse_date(data.get("work_date")) if data.get("work_date") else None
    p = detail.payroll
    if work_date and not (p.period_start - timedelta(days=31) <= work_date <= p.period_end):
        raise PayrollError("La fecha no corresponde al periodo de la planilla.", "invalid", 400)
    x = PayrollException.objects.create(
        payroll=p, employee=e, work_date=work_date, category=category, description=text[:1000],
        supervisor_code=team_manager_code(e, timezone.localdate()), created_by=user)
    record("payroll_exception_reported", Category.PAYROLL,
           f"{e.employee_code} reportó una excepción en la planilla {p.payroll_code}: {x.get_category_display()}.",
           request=request, actor=user, target=e, details={"exception": x.pk, "supervisor": x.supervisor_code})
    return x


def _led_employee_ids(user) -> set[int]:
    """Colaboradores bajo los puestos de liderazgo del usuario (cadena de mando vigente)."""
    from apps.operations.hierarchy import employees_under
    from apps.operations.models import OperationalLeader

    e = my_employee(user)
    if e is None:
        return set()
    out: set[int] = set()
    today = timezone.localdate()
    for lead in OperationalLeader.objects.filter(employee=e, is_active=True):
        out |= employees_under(lead.level, e.employee_code, today)
    return out


def exceptions_scope(user):
    """Planillas (payroll.view) ve todas; un líder, las de su equipo; el colaborador, las suyas."""
    qs = PayrollException.objects.select_related("employee", "payroll", "resolved_by", "created_by")
    if Perm.PAYROLL_VIEW in user_permissions(user):
        return qs, "all"
    e = my_employee(user)
    if e is None:
        return qs.none(), "none"
    team = _led_employee_ids(user)
    return qs.filter(Q(supervisor_code=e.employee_code) | Q(employee_id__in=team) | Q(employee=e)), "team" if team else "mine"


def can_resolve(user, x: PayrollException) -> bool:
    if Perm.PAYROLL_MANAGE in user_permissions(user):
        return True
    e = my_employee(user)
    return bool(e) and x.employee_id != e.pk and (x.supervisor_code == e.employee_code or x.employee_id in _led_employee_ids(user))


@transaction.atomic
def resolve_exception(x: PayrollException, *, user, status: str, response: str, request=None) -> PayrollException:
    if x.status != X.OPEN:
        raise PayrollError("La excepción ya fue atendida.", "not_open")
    if not can_resolve(user, x):
        raise PayrollError("Solo su supervisor o Planillas atienden esta excepción.", "forbidden", 403)
    if status not in (X.RESOLVED, X.REJECTED):
        raise PayrollError("Estado inválido (RESOLVED o REJECTED).", "invalid", 400)
    response = (response or "").strip()
    if not response:
        raise PayrollError("Escriba la respuesta para el colaborador.", "required", 400)
    x.status, x.response, x.resolved_by, x.resolved_at = status, response[:1000], user, timezone.now()
    x.save(update_fields=["status", "response", "resolved_by", "resolved_at"])
    record("payroll_exception_resolved", Category.PAYROLL,
           f"Excepción #{x.pk} de {x.employee.employee_code} ({x.payroll.payroll_code}) {x.get_status_display().lower()}.",
           request=request, actor=user, target=x.employee, details={"exception": x.pk, "status": status})
    return x


def exception_dict(x: PayrollException, user=None) -> dict:
    out = {
        "id": x.pk, "payroll_id": x.payroll_id, "payroll_code": x.payroll.payroll_code, "payroll_status": x.payroll.payroll_status,
        "employee_code": x.employee.employee_code, "full_name": x.employee.full_name, "work_date": x.work_date,
        "category": x.category, "category_label": x.get_category_display(), "description": x.description, "status": x.status,
        "status_label": x.get_status_display(), "supervisor_code": x.supervisor_code, "created_at": x.created_at,
        "response": x.response, "resolved_by": x.resolved_by.username if x.resolved_by_id and x.resolved_by else None,
        "resolved_at": x.resolved_at,
    }
    if user is not None:
        out["can_resolve"] = x.status == X.OPEN and can_resolve(user, x)
    return out


# ================================================================ corridas diarias automáticas (pre-cierre)
def due_periods(today: date) -> list[PayPeriod]:
    """Periodos abiertos de ciclos predeterminados cuyo corte en curso termina dentro de los días de anticipación
    configurados (p. ej. desde el día 10 para el corte que cierra el 24)."""
    out = []
    cutoffs = (AttendanceCutoff.objects.filter(cycle__is_default=True, cycle__is_active=True, cutoff_end__gte=today,
                                               cutoff_start__lte=today + timedelta(days=31))
               .select_related("pay_period", "pay_period__cycle"))
    seen = set()
    for c in cutoffs:
        p = c.pay_period
        if p is None or p.pk in seen:
            continue
        s: PayrollSetting | None = setting_for(p.cycle.country_id, p.period_end)
        lead = s.preliminary_lead_days if s else 14
        if today < c.cutoff_end - timedelta(days=lead):
            continue
        run = PayrollRun.objects.filter(pay_period=p).select_related("payroll").first()
        if run and run.payroll.payroll_status in CLOSED_STATUSES:
            continue
        seen.add(p.pk)
        out.append(p)
    return out


def run_scheduled(today: date | None = None, *, user=None) -> list[dict]:
    today = today or timezone.localdate()
    done = []
    for p in due_periods(today):
        try:
            run = calculate(p, user=user, trigger=PayrollIteration.Trigger.SCHEDULED)
            done.append({"period": p.code, "payroll": run.payroll.payroll_code, "iteration": run.iterations})
        except PayrollError as exc:
            done.append({"period": p.code, "error": exc.message})
    return done


def iteration_dict(i: PayrollIteration) -> dict:
    return {"number": i.number, "trigger": i.trigger, "trigger_label": i.get_trigger_display(), "calculated_at": i.calculated_at,
            "calculated_by": i.calculated_by.username if i.calculated_by_id and i.calculated_by else None,
            "employees": i.employees, "scheduled_seconds": i.scheduled_seconds, "paid_seconds": i.paid_seconds,
            "gross": i.gross, "deductions": i.deductions, "net": i.net, "warnings": i.warnings, "open_exceptions": i.open_exceptions}


# ================================================================ reglas por cuenta (séptimo día)
def account_rules_list() -> dict:
    from apps.operations.models import Client

    rules = {r.client_id: r for r in PayrollAccountRule.objects.all()}
    return {"results": [{
        "client_id": c.pk, "client_code": c.code, "client_name": c.name, "has_rule": c.pk in rules,
        "seventh_day_penalty": rules[c.pk].seventh_day_penalty if c.pk in rules else None,
        "is_active": rules[c.pk].is_active if c.pk in rules else None, "notes": rules[c.pk].notes if c.pk in rules else "",
    } for c in Client.objects.order_by("name")]}


@transaction.atomic
def save_account_rule(client_id: int, data: dict, *, user=None, request=None) -> PayrollAccountRule:
    from apps.operations.models import Client

    client = Client.objects.filter(pk=client_id).first()
    if client is None:
        raise PayrollError("La cuenta no existe.", "not_found", 404)
    rule, _ = PayrollAccountRule.objects.get_or_create(client=client)
    if "seventh_day_penalty" in data:
        rule.seventh_day_penalty = bool(data["seventh_day_penalty"])
    if "is_active" in data:
        rule.is_active = bool(data["is_active"])
    if "notes" in data:
        rule.notes = str(data.get("notes") or "")[:300]
    rule.updated_by = user if getattr(user, "pk", None) else None
    rule.save()
    record("payroll_account_rule_saved", Category.PAYROLL,
           f"Regla de planilla de la cuenta {client.name}: séptimo día {'activo' if rule.seventh_day_penalty else 'inactivo'}.",
           request=request, actor=user, target_type="PayrollAccountRule", target_id=str(rule.pk),
           details={"client": client.code, "seventh_day_penalty": rule.seventh_day_penalty, "is_active": rule.is_active})
    return rule
