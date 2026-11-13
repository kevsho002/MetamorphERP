"""Fase 22 — Centro de notificaciones operativas (en vivo).

Se calculan al consultar (el navegador consulta cada 30 s y al volver a la pestaña), según los permisos y la
jerarquía del usuario:

* AP pendientes de SU firma (el siguiente paso corresponde a su rol).
* Solicitudes de planilla: planillas calculadas por aprobar y liquidaciones por aprobar (payroll.manage) y excepciones
  de planilla abiertas en su alcance (Planillas: todas; líder: las de su equipo).
* Solicitudes de WFM pendientes (cola de aprobación) para wfm.manage.
* Altas de nuevos empleados (últimos 7 días) bajo su jerarquía (Team Manager y superiores) o todas con hcm.manage.
* Ausentismo del día (no-shows: Unjustified Absence de hoy) de su equipo, o de todos con wfm.view / hcm.manage.

Solo se persiste qué notificaciones leyó cada usuario (sys_notification_read).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.utils import timezone

from apps.accounts.permissions import user_permissions
from apps.accounts.roles import Perm
from apps.system.models import NotificationRead

NEW_HIRE_DAYS = 7
LIMIT = 60


def _employee(user):
    return getattr(user, "employee", None) if getattr(user, "employee_id", None) else None


def team_ids(user) -> set[int]:
    from apps.payroll.portal import _led_employee_ids

    return _led_employee_ids(user)


def _item(key, kind, title, body, link, at, severity="info") -> dict:
    return {"key": key, "kind": kind, "title": title, "body": body, "link": link, "at": at, "severity": severity}


def _pending_actions(user) -> list[dict]:
    from apps.personnel_actions import services as pa
    from apps.personnel_actions.models import PersonnelAction, Status

    out = []
    qs = (PersonnelAction.objects.filter(status=Status.PENDING, action_type_id__in=pa.visible_type_ids(user))
          .select_related("action_type", "employee", "employee__country").prefetch_related("signatures", "action_type__steps")
          .order_by("-submitted_at")[:200])
    for a in qs:
        if pa.sign_block_reason(a, user) is not None:
            continue
        signed = a.signatures.count()
        out.append(_item(f"ap:{a.folio}:{signed}", "ap", "AP pendiente de su firma",
                         f"{a.folio} · {a.action_type.name} · {a.employee.full_name}", f"/personnel-actions/{a.folio}",
                         a.submitted_at or a.created_at, "warn"))
    return out


def _payroll(user, perms) -> list[dict]:
    from apps.payroll.models import PayrollException, PayrollRun, Settlement
    from apps.payroll.portal import exceptions_scope

    out = []
    if Perm.PAYROLL_MANAGE in perms:
        for run in PayrollRun.objects.filter(payroll__payroll_status="CALCULATED").select_related("payroll").order_by("-calculated_at")[:20]:
            out.append(_item(f"payroll:{run.pk}:{run.iterations}", "payroll", "Planilla calculada por aprobar",
                             f"{run.payroll.payroll_code} · corrida {run.iterations}", f"/payroll/runs/{run.pk}",
                             run.calculated_at, "info"))
        for s in Settlement.objects.filter(status=Settlement.Status.CALCULATED).select_related("employee").order_by("-calculated_at")[:20]:
            out.append(_item(f"settlement:{s.pk}", "payroll", "Liquidación por aprobar", f"{s.folio} · {s.employee.full_name}",
                             f"/payroll/settlements/{s.pk}", s.calculated_at, "info"))
    qs, scope = exceptions_scope(user)
    if scope in ("all", "team"):
        me = _employee(user)
        open_qs = qs.filter(status=PayrollException.Status.OPEN)
        if me is not None:
            open_qs = open_qs.exclude(employee=me)
        for x in open_qs.order_by("-created_at")[:20]:
            out.append(_item(f"pay-exc:{x.pk}", "payroll", "Excepción de planilla por atender",
                             f"{x.employee.full_name}: {x.get_category_display()}", "/portal/exceptions", x.created_at, "warn"))
    return out


def _wfm_requests(perms) -> list[dict]:
    from apps.adherence.models import ChangeRequest

    if Perm.WFM_MANAGE not in perms:
        return []
    out = []
    for r in ChangeRequest.objects.filter(status=ChangeRequest.Status.PENDING).select_related("employee").order_by("-requested_at")[:20]:
        out.append(_item(f"wfm-req:{r.pk}", "wfm", "Solicitud de WFM pendiente",
                         f"{r.employee.full_name} · {r.get_kind_display()} · {r.shift_date:%d/%m/%Y}", "/wfm/requests",
                         r.requested_at, "info"))
    return out


def _new_hires(user, perms, team: set[int], today) -> list[dict]:
    from apps.hcm.models import Employee

    since = today - timedelta(days=NEW_HIRE_DAYS)
    qs = Employee.objects.filter(hire_date__gte=since, hire_date__lte=today + timedelta(days=30)).order_by("-hire_date")
    if Perm.HCM_MANAGE not in perms:
        if not team:
            return []
        qs = qs.filter(pk__in=team)
    out = []
    for e in qs[:20]:
        out.append(_item(f"hire:{e.employee_code}", "hire", "Nuevo empleado en su equipo" if Perm.HCM_MANAGE not in perms else "Alta de empleado",
                         f"{e.full_name} ({e.employee_code}) · ingreso {e.hire_date:%d/%m/%Y}", f"/hcm/employees/{e.employee_code}",
                         timezone.make_aware(datetime.combine(e.hire_date, time())), "info"))
    return out


def _no_shows(perms, team: set[int], today) -> list[dict]:
    from apps.adherence.models import ActivityType, ScheduleSegment

    qs = (ScheduleSegment.objects.filter(shift_date=today, activity__system_role=ActivityType.SystemRole.ABSENCE)
          .select_related("employee").order_by("start_at"))
    if not ({Perm.WFM_VIEW, Perm.HCM_MANAGE} & set(perms)):
        if not team:
            return []
        qs = qs.filter(employee_id__in=team)
    seen, out = set(), []
    for s in qs[:100]:
        if s.employee_id in seen:
            continue
        seen.add(s.employee_id)
        out.append(_item(f"noshow:{s.employee_id}:{today.isoformat()}", "noshow", "Ausentismo (no-show) de hoy",
                         f"{s.employee.full_name} · turno desde {s.start_at:%H:%M}",
                         f"/wfm/planner?date={today.isoformat()}&employee={s.employee.employee_code}",
                         timezone.make_aware(s.start_at) if timezone.is_naive(s.start_at) else s.start_at, "danger"))
    return out


def for_user(user) -> dict:
    perms = user_permissions(user)
    today = timezone.localdate()
    team = team_ids(user)
    items = []
    if Perm.ACTIONS_VIEW in perms:
        items += _pending_actions(user)
    items += _payroll(user, perms)
    items += _wfm_requests(perms)
    if Perm.HCM_VIEW in perms or team:
        items += _new_hires(user, perms, team, today)
    items += _no_shows(perms, team, today)
    read = set(NotificationRead.objects.filter(user=user, key__in=[i["key"] for i in items]).values_list("key", flat=True))
    for i in items:
        i["read"] = i["key"] in read
    items.sort(key=lambda i: (i["read"], -(i["at"].timestamp() if i["at"] else 0)))
    counts = {}
    for i in items:
        counts[i["kind"]] = counts.get(i["kind"], 0) + (0 if i["read"] else 1)
    return {"results": items[:LIMIT], "unread": sum(1 for i in items if not i["read"]), "total": len(items),
            "by_kind": counts, "generated_at": timezone.now(), "poll_seconds": 30}


def mark_read(user, keys: list[str] | None = None, *, all_keys: bool = False) -> int:
    if all_keys:
        keys = [i["key"] for i in for_user(user)["results"]]
    keys = [str(k)[:120] for k in (keys or []) if k][:200]
    existing = set(NotificationRead.objects.filter(user=user, key__in=keys).values_list("key", flat=True))
    NotificationRead.objects.bulk_create([NotificationRead(user=user, key=k) for k in keys if k not in existing])
    # Limpieza: se olvidan las lecturas de más de 60 días.
    NotificationRead.objects.filter(user=user, read_at__lt=timezone.now() - timedelta(days=60)).delete()
    return len(keys)
