"""API de Acciones de Personal (AP).

GET   /personnel-actions/types/                         tipos visibles (campos EAV y cadena de firmas)
GET   /personnel-actions/?status=&type=&employee=&search=&pending_for_me=1&from=&to=&page=
POST  /personnel-actions/            · /validate/       {action_type, employee_code, effective_date, justification, values, submit}
GET   /personnel-actions/{folio}/                       detalle: valores, firmas, integridad, acciones posibles
PATCH /personnel-actions/{folio}/                       editar un borrador
POST  /personnel-actions/{folio}/submit/                enviar a aprobación (sella el contenido)
POST  /personnel-actions/{folio}/sign/                  {decision: APPROVED|REJECTED, comment}
POST  /personnel-actions/{folio}/cancel/                {reason}
GET   /personnel-actions/employees/{ID}/                APs del empleado + horario vigente
GET   /personnel-actions/missing-initial/               empleados activos sin Primera AP de horario
POST  /personnel-actions/schedule-preview/              {schedule, country | employee_code, effective_date}
"""

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasActionPermission, PasswordChangeNotRequired, user_permissions
from apps.accounts.roles import Perm, Role
from apps.common.models import Country
from apps.hcm.models import Employee
from apps.personnel_actions import services
from apps.personnel_actions.models import ActionType, PersonnelAction, Status
from apps.scheduling import engine
from apps.scheduling import services as sch
from apps.scheduling.models import ScheduleAssignment

PERMISSIONS = [IsAuthenticated, PasswordChangeNotRequired, HasActionPermission]
NO_STORE = {"Cache-Control": "no-store"}


class _View(APIView):
    permission_classes = PERMISSIONS
    method_permissions: dict = {}

    @property
    def action(self):
        return self.request.method.lower()

    @property
    def action_permissions(self):
        return self.method_permissions


def _queryset(user):
    return PersonnelAction.objects.filter(action_type_id__in=services.visible_type_ids(user)).select_related(
        "action_type", "employee__country", "created_by"
    ).prefetch_related("action_type__steps", "signatures")


def _get(user, folio: str, *, lock=False) -> PersonnelAction:
    if lock:  # bloqueo de la fila de la AP (SQL Server no admite FOR UPDATE OF con joins)
        list(PersonnelAction.objects.select_for_update().filter(folio=folio.upper()).values_list("pk", flat=True))
    qs = _queryset(user).prefetch_related("values__attribute", "action_type__attributes")
    return get_object_or_404(qs, folio=folio.upper())


def _error(exc: services.ActionError) -> Response:
    return Response({"detail": exc.message, "code": exc.code}, status=status.HTTP_400_BAD_REQUEST)


class TypesView(_View):
    method_permissions = {"get": Perm.ACTIONS_VIEW}

    def get(self, request):
        types = ActionType.objects.prefetch_related("attributes", "steps").filter(is_active=True)
        return Response({"results": [services.type_dict(t, request.user) for t in types if services.can_view_type(request.user, t)]})


class ActionsView(_View):
    method_permissions = {"get": Perm.ACTIONS_VIEW, "post": Perm.ACTIONS_CREATE}
    dry_run = False

    def get(self, request):
        p = request.query_params
        qs = _queryset(request.user)
        if p.get("status"):
            qs = qs.filter(status__in=[s.strip().upper() for s in p["status"].split(",")])
        if p.get("type"):
            qs = qs.filter(action_type__code=p["type"].upper())
        if p.get("category"):
            qs = qs.filter(action_type__category=p["category"].upper())
        if p.get("employee"):
            qs = qs.filter(employee__employee_code=p["employee"].strip().upper())
        if p.get("from"):
            qs = qs.filter(effective_date__gte=services.parse_date(p["from"]) or "1900-01-01")
        if p.get("to"):
            qs = qs.filter(effective_date__lte=services.parse_date(p["to"]) or "9999-12-31")
        for term in p.get("search", "").split():
            qs = qs.filter(services.search_filter(term))
        rows = list(qs.order_by("-created_at", "-id")[:2000])
        if p.get("pending_for_me") in {"1", "true"}:
            rows = [a for a in rows if a.status == Status.PENDING and services.sign_block_reason(a, request.user) is None]
        try:
            page = max(1, int(p.get("page", 1)))
            size = max(1, min(int(p.get("page_size", 25)), 200))
        except ValueError:
            page, size = 1, 25
        pending_mine = sum(1 for a in _queryset(request.user).filter(status=Status.PENDING)
                           if services.sign_block_reason(a, request.user) is None)
        return Response({
            "count": len(rows), "pending_for_me": pending_mine,
            "results": [services.action_dict(a, request.user) for a in rows[(page - 1) * size: page * size]],
        }, headers=NO_STORE)

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        t = ActionType.objects.filter(code=str(data.get("action_type") or "").upper()).first()
        employee = Employee.objects.select_related("country").filter(employee_code=str(data.get("employee_code") or "").strip().upper()).first()
        check = services.validate(t, employee, data, user=request.user)
        if employee is None and data.get("employee_code"):
            check.errors = [e for e in check.errors if e["field"] != "employee_code"]
            check.error("employee_code", f"No existe el empleado {data['employee_code']}.", "not_found")
        if self.dry_run or not check.ok:
            return Response(check.as_dict(), status=status.HTTP_200_OK if self.dry_run else status.HTTP_400_BAD_REQUEST)
        try:
            action = services.create(check, user=request.user, request=request, submit_now=bool(data.get("submit")))
        except services.ActionError as exc:
            return _error(exc)
        action = _get(request.user, action.folio)
        feedback = f"AP {action.folio} {'enviada a aprobación' if action.status == Status.PENDING else action.get_status_display().lower()}."
        if action.status == Status.APPROVED:
            feedback = f"AP {action.folio} aprobada" + (" y aplicada." if action.applied_at else " (se aplicará en su fecha efectiva).")
        return Response({**check.as_dict(), "feedback": feedback, "action": services.action_dict(action, request.user, detail=True)},
                        status=status.HTTP_201_CREATED)


class ValidateView(ActionsView):
    dry_run = True
    method_permissions = {"post": Perm.ACTIONS_CREATE}


class ActionDetailView(_View):
    method_permissions = {"get": Perm.ACTIONS_VIEW, "patch": Perm.ACTIONS_CREATE}

    def get(self, request, folio: str):
        return Response(services.action_dict(_get(request.user, folio), request.user, detail=True), headers=NO_STORE)

    def patch(self, request, folio: str):
        action = _get(request.user, folio, lock=True)
        if action.status != Status.DRAFT:
            return Response({"detail": "Solo se editan las AP en borrador."}, status=status.HTTP_400_BAD_REQUEST)
        data = request.data if isinstance(request.data, dict) else {}
        merged = {
            "effective_date": data.get("effective_date", action.effective_date),
            "justification": data.get("justification", action.justification),
            "values": data.get("values", {v.attribute.key: services._json_safe(v.value) for v in action.values.all()}),
        }
        check = services.validate(action.action_type, action.employee, merged, user=request.user, instance=action)
        if not check.ok:
            return Response(check.as_dict(), status=status.HTTP_400_BAD_REQUEST)
        services.update_draft(action, check, user=request.user, request=request)
        action = _get(request.user, folio)
        return Response({**check.as_dict(), "feedback": "Borrador actualizado.", "action": services.action_dict(action, request.user, detail=True)})


class TransitionView(_View):
    """submit / sign / cancel."""

    transition = "submit"

    @property
    def method_permissions(self):
        return {"post": Perm.ACTIONS_VIEW if self.transition == "sign" else Perm.ACTIONS_CREATE}

    def post(self, request, folio: str):
        action = _get(request.user, folio, lock=True)
        data = request.data if isinstance(request.data, dict) else {}
        try:
            if self.transition == "submit":
                if not services.can_create_type(request.user, action.action_type):
                    return Response({"detail": "Su rol no puede enviar este tipo de AP."}, status=status.HTTP_403_FORBIDDEN)
                services.submit(action, user=request.user, request=request)
            elif self.transition == "sign":
                services.sign(action, user=request.user, decision=str(data.get("decision") or "").upper(),
                              comment=str(data.get("comment") or ""), request=request)
            else:
                if not services.can_create_type(request.user, action.action_type):
                    return Response({"detail": "Su rol no puede anular este tipo de AP."}, status=status.HTTP_403_FORBIDDEN)
                services.cancel(action, user=request.user, reason=str(data.get("reason") or ""), request=request)
        except services.ActionError as exc:
            return _error(exc)
        action = _get(request.user, folio)
        labels = {Status.PENDING: "en aprobación", Status.APPROVED: "aprobada", Status.REJECTED: "rechazada", Status.CANCELLED: "anulada"}
        feedback = f"AP {action.folio} {labels.get(action.status, action.get_status_display().lower())}."
        if action.status == Status.APPROVED:
            feedback += " Efecto aplicado." if action.applied_at else " Su efecto se aplicará en la fecha efectiva."
        elif action.status == Status.PENDING and action.signatures.exists():
            nxt = services.next_step(action)
            feedback += f" Siguiente firma: {nxt.label} ({nxt.get_role_display()})." if nxt else ""
        return Response({"feedback": feedback, "action": services.action_dict(action, request.user, detail=True)})


class EmployeePickerView(_View):
    """Fase 23 — GET /personnel-actions/employees/picker/?q=&terminated=1 — colaboradores a los que el usuario puede
    elaborarles una AP (su jerarquía directa e indirecta; ver apps/personnel_actions/scope.py)."""

    method_permissions = {"get": Perm.ACTIONS_CREATE}

    def get(self, request):
        from apps.personnel_actions import scope

        p = request.query_params
        limit = int(p["limit"]) if str(p.get("limit") or "").isdigit() else 20
        return Response(scope.search(request.user, p.get("q", ""), include_terminated=p.get("terminated") == "1", limit=limit),
                        headers=NO_STORE)


class EmployeeActionsView(_View):
    method_permissions = {"get": Perm.ACTIONS_VIEW}

    def get(self, request, code: str):
        employee = get_object_or_404(Employee.objects.select_related("country"), employee_code=code.upper())
        today = timezone.localdate()
        actions = _queryset(request.user).filter(employee=employee).order_by("-effective_date", "-id")
        assignments = ScheduleAssignment.objects.filter(employee=employee).select_related("personnel_action__action_type").order_by("-effective_start_date")
        primary = [a for a in assignments if a.mode == ScheduleAssignment.Mode.PRIMARY]
        current = next((a for a in primary if a.covers(today)), None) or next((a for a in reversed(primary) if a.effective_start_date > today), None)
        # Varias AP el mismo día: además del principal, las asignaciones adicionales vigentes o futuras.
        additional = [a for a in assignments if a.mode == ScheduleAssignment.Mode.ADDITIONAL and (a.effective_end_date or today) >= today]
        initial = PersonnelAction.objects.filter(employee=employee, is_initial=True, status__in=["DRAFT", "PENDING", "APPROVED"]).first()
        perms = user_permissions(request.user)
        types = [t for t in ActionType.objects.prefetch_related("attributes", "steps").filter(is_active=True)
                 if services.can_create_type(request.user, t)]
        return Response({
            "employee_code": employee.employee_code, "full_name": employee.full_name, "country": employee.country.country_code,
            "hire_date": employee.hire_date, "termination_date": employee.termination_date,
            "employment_status": employee.employment_status,
            "initial_action": {"folio": initial.folio, "status": initial.status, "status_label": initial.get_status_display()} if initial else None,
            "current_schedule": sch.assignment_dict(current, today) if current else None,
            "additional_schedules": [sch.assignment_dict(a, today) for a in sorted(additional, key=lambda a: a.effective_start_date)],
            "schedules": [sch.assignment_dict(a, today) for a in assignments],
            "results": [services.action_dict(a, request.user) for a in actions],
            "creatable_types": [{"code": t.code, "name": t.name, "effect": t.effect, "is_initial_schedule": t.is_initial_schedule,
                                 "schedule_mode": t.schedule_mode} for t in types],
            "can_create": "actions.create" in perms and employee.employment_status != Employee.Status.TERMINATED,
            # Fase 22: valores vigentes del roster / expediente (los campos «Dato del roster» de la AP los muestran)
            "roster": _roster_now(employee, today),
            "cost_center": employee.cost_center.code if employee.cost_center_id else None,
        }, headers=NO_STORE)


def _roster_now(employee: Employee, today) -> dict:
    from apps.roster import services as roster

    return {row["code"]: row["current"]["label"] for row in roster.snapshot(employee, today) if row["current"]}


class MissingInitialView(_View):
    method_permissions = {"get": Perm.ACTIONS_VIEW}

    def get(self, request):
        rows = services.employees_missing_initial(Employee.objects.select_related("country")).order_by("employee_code")[:500]
        return Response({"count": len(rows), "results": [
            {"employee_code": e.employee_code, "full_name": e.full_name, "country": e.country.country_code, "hire_date": e.hire_date}
            for e in rows
        ]})


class SchedulePreviewView(_View):
    method_permissions = {"post": Perm.ACTIONS_VIEW}

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        on = services.parse_date(data.get("effective_date")) or timezone.localdate()
        country_id = None
        if data.get("employee_code"):
            emp = Employee.objects.filter(employee_code=str(data["employee_code"]).upper()).first()
            country_id = emp.country_id if emp else None
        if country_id is None and data.get("country"):
            c = Country.objects.filter(country_code=str(data["country"]).upper()).first()
            country_id = c.country_id if c else None
        if data.get("schedule") in (None, "", {}):
            raise ValidationError({"schedule": "Envíe el horario."})
        try:
            body = sch.preview_schedule(data["schedule"], country_id=country_id, on=on, days=7, start=on)
        except engine.DefinitionError as exc:
            return Response({"valid": False, "errors": exc.errors, "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"valid": True, **body})



# ================================================================ Fase 21: ciclo de vida y roles por tipo de AP
class LifecycleView(_View):
    """Estado, antigüedad (congelada por suspensiones) e historial laboral. El indicador de recontratación y la alerta
    formal solo se entregan a quien administra empleados (Recursos Humanos / Administración)."""

    method_permissions = {"get": Perm.HCM_VIEW}

    def get(self, request, code: str):
        from apps.personnel_actions import lifecycle

        employee = get_object_or_404(Employee, employee_code=code.upper())
        hr = Perm.HCM_MANAGE in user_permissions(request.user)
        today = timezone.localdate()
        current = lifecycle.active_suspension(employee, today)
        body = {
            "employee_code": employee.employee_code, "full_name": employee.full_name,
            "status": employee.employment_status, "status_label": employee.get_employment_status_display(),
            "hire_date": employee.hire_date, "termination_date": employee.termination_date,
            "tenure": lifecycle.tenure(employee, today),
            "active_suspension": lifecycle.event_dict(current, hr=hr) if current else None,
            "history": lifecycle.history(employee, hr=hr), "is_hr": hr,
        }
        if hr:
            last = lifecycle.last_termination(employee)
            body["rehire_eligible"] = last.rehire_eligible if last else None
            body["rehire_alert"] = lifecycle.rehire_alert(employee)
        return Response(body, headers=NO_STORE)


class RoleMatrixView(_View):
    """Quién elabora y quién firma cada tipo de AP. GET para todos los que ven AP; PATCH solo el Administrador."""

    method_permissions = {"get": Perm.ACTIONS_VIEW, "patch": Perm.ACTIONS_VIEW}

    def get(self, request):
        types = ActionType.objects.prefetch_related("steps").order_by("display_order", "name")
        return Response({
            "roles": [{"value": r, "label": services.ROLE_LABELS.get(r, r)} for r in Role.values],
            "can_edit": request.user.effective_role == Role.ADMIN,
            "results": [{
                "code": t.code, "name": t.name, "effect": t.effect, "effect_label": t.get_effect_display(), "is_active": t.is_active,
                "creator_roles": t.creator_roles or [], "admin_signs_any_step": t.admin_signs_any_step,
                "create_permission": t.create_permission, "view_permission": t.view_permission,
                "steps": [{"order": s.order, "label": s.label, "role": s.role} for s in t.steps.all()],
            } for t in types],
        }, headers=NO_STORE)

    def patch(self, request, code: str | None = None):
        if request.user.effective_role != Role.ADMIN:
            return Response({"detail": "Solo el Administrador cambia los roles de las AP."}, status=status.HTTP_403_FORBIDDEN)
        t = get_object_or_404(ActionType, code=(code or "").upper())
        data = request.data if isinstance(request.data, dict) else {}
        changes = {}
        if "creator_roles" in data:
            roles = data.get("creator_roles") or []
            if not isinstance(roles, list) or any(r not in Role.values for r in roles):
                return Response({"detail": f"Roles válidos: {', '.join(Role.values)}."}, status=status.HTTP_400_BAD_REQUEST)
            t.creator_roles = [r for r in Role.values if r in roles]
            changes["creator_roles"] = t.creator_roles
        if "admin_signs_any_step" in data:
            t.admin_signs_any_step = bool(data["admin_signs_any_step"])
            changes["admin_signs_any_step"] = t.admin_signs_any_step
        steps = data.get("steps") or []
        by_order = {s.order: s for s in t.steps.all()}
        for item in steps:
            step = by_order.get(int(item.get("order", 0) or 0)) if isinstance(item, dict) else None
            if step is None or item.get("role") not in Role.values:
                return Response({"detail": "Paso o rol inválido."}, status=status.HTTP_400_BAD_REQUEST)
            if step.role != item["role"]:
                step.role = item["role"]
                step.save(update_fields=["role"])
                changes[f"step_{step.order}"] = step.role
        t.save()
        from apps.system.audit import Category, record

        record("action_type_roles_changed", Category.PERSONNEL_ACTIONS, f"Roles del tipo de AP {t.code} actualizados.",
               request=request, actor=request.user, target_type="ActionType", target_id=t.code, details=changes)
        return self.get(request)
