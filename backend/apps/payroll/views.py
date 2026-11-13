"""API de la Fase 20: cálculo automático de planilla y control de boletas físicas.

GET    /payroll/catalogs/                                     países, departamentos (centros de costos), estados, años
GET    /payroll/periods/?year=&country=                       periodos de pago de los ciclos predeterminados y su planilla
GET    /payroll/runs/?year=&status=  ·  POST {period_id}      planillas · calcula (o recalcula) la del periodo
GET    /payroll/runs/{id}/?search=&cost_center=&export=csv    totales y detalle por colaborador (CSV con export=csv)
GET    /payroll/runs/{id}/employees/{code}/                   desglose de la boleta (líneas con su origen y AP)
POST   /payroll/runs/{id}/recalculate/ · approve/ · pay/ · cancel/ {reason}
GET    /payroll/settings/  ·  POST                            parámetros salariales, conceptos y retenciones de ley · nueva vigencia
PATCH  /payroll/settings/{id}/                                edita una vigencia que ninguna planilla cerrada usó
PATCH  /payroll/concepts/{code}/                              afectación a ISSS / AFP y Renta, nombre, activo
POST   /payroll/deduction-types/{id}/versions/                nueva vigencia de ISSS / AFP / Renta (tasa, tope, tramos)
GET    /payroll/payslips/?payroll=&batch=&year=&month=&frequency=&cost_center=&printed=&signature=&archived=&search=&page=
                                                              inventario de boletas físicas (RRHH)
GET    /payroll/payslips/{id}/  ·  /payroll/payslips/print/?ids=&batch=   boleta(s) para imprimir
POST   /payroll/payslips/actions/ {ids[], action, signed_on?, location?, reason?}   PRINT · SIGN · ARCHIVE · UNPRINT · UNSIGN · UNARCHIVE
GET    /payroll/batches/?year=&month=&cost_center=&payroll=  ·  PATCH /payroll/batches/{id}/ {archive_location, notes}
"""

import csv

from django.db import DatabaseError
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasActionPermission, PasswordChangeNotRequired, user_permissions
from apps.accounts.roles import Perm
from apps.common.models import CostCenter, Country
from apps.hcm.models import Employee
from apps.payroll import services
from apps.payroll.models import DeductionType, PayConcept, PayrollRun, PayrollSetting, Payslip, PayslipBatch
from apps.scheduling.models import PayPeriod

PERMISSIONS = [IsAuthenticated, PasswordChangeNotRequired, HasActionPermission]
NO_STORE = {"Cache-Control": "no-store"}
SQL_ERRORS = (
    ("50090", "SQL Server rechazó el cambio: la planilla está cerrada o pagada."),
    ("50091", "SQL Server rechazó el cambio: el estado de la planilla solo avanza y una planilla cerrada no cambia sus totales."),
    ("50092", "SQL Server rechazó el cambio: el contenido de una boleta generada no cambia ni se elimina."),
    ("50093", "SQL Server rechazó la línea: la AP debe estar aprobada, ser del mismo empleado y ser un concepto de planilla."),
    ("ck_pay_slip_sign_printed", "Una boleta solo se marca como firmada si ya está impresa."),
    ("ck_pay_slip_archive_printed", "Una boleta solo se archiva si ya está impresa."),
    ("uq_pay_line_action_code", "La AP ya se pagó en otra planilla."),
)
MAX_PAGE_SIZE = 200


class _View(APIView):
    permission_classes = PERMISSIONS
    method_permissions: dict = {}

    @property
    def action(self):
        return self.request.method.lower()

    @property
    def action_permissions(self):
        return self.method_permissions

    def handle_exception(self, exc):
        if isinstance(exc, services.PayrollError):
            return Response({"detail": exc.message, "code": exc.code}, status=exc.status)
        if isinstance(exc, DatabaseError):
            text = str(exc)
            for number, message in SQL_ERRORS:
                if number in text:
                    return Response({"detail": message, "code": f"sql_{number}"}, status=status.HTTP_409_CONFLICT)
        return super().handle_exception(exc)


def _data(request) -> dict:
    return request.data if isinstance(request.data, dict) else {}


def _int(value, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _run(pk) -> PayrollRun:
    return get_object_or_404(PayrollRun.objects.select_related("payroll", "pay_period", "pay_period__cycle", "calculated_by", "setting"), pk=pk)


def _can_manage(request) -> bool:
    return Perm.PAYROLL_MANAGE in user_permissions(request.user)


class CatalogsView(_View):
    method_permissions = {"get": Perm.PAYROLL_VIEW}

    def get(self, request):
        years = sorted({d.year for d in PayPeriod.objects.filter(cycle__is_default=True).dates("period_start", "year")}
                       | {services.timezone.localdate().year})
        return Response({
            "countries": [{"id": c.country_id, "code": c.country_code, "name": c.country_name, "currency": c.currency_code}
                          for c in Country.objects.filter(is_active=True)],
            "cost_centers": [{"code": c.code, "name": c.name, "country": c.country_id}
                             for c in CostCenter.objects.filter(is_active=True).order_by("code")],
            "statuses": [{"value": k, "label": v} for k, v in services.STATUS_LABELS.items()],
            "frequencies": [{"value": v, "label": label} for v, label in Employee.PayFrequency.choices],
            "inventory_actions": services.INVENTORY_ACTIONS,
            "years": years, "can_manage": _can_manage(request),
        }, headers=NO_STORE)


class PeriodsView(_View):
    method_permissions = {"get": Perm.PAYROLL_VIEW}

    def get(self, request):
        year = _int(request.query_params.get("year"), services.timezone.localdate().year, 2000, 2100)
        country = request.query_params.get("country")
        return Response({"year": year, "results": services.period_rows(year, country_id=int(country) if str(country or "").isdigit() else None),
                         "can_manage": _can_manage(request)}, headers=NO_STORE)


class RunsView(_View):
    method_permissions = {"get": Perm.PAYROLL_VIEW, "post": Perm.PAYROLL_MANAGE}

    def get(self, request):
        qs = PayrollRun.objects.select_related("payroll", "pay_period", "pay_period__cycle", "calculated_by", "setting")
        year = request.query_params.get("year")
        if str(year or "").isdigit():
            qs = qs.filter(pay_period__period_start__year=int(year))
        if request.query_params.get("status"):
            qs = qs.filter(payroll__payroll_status=request.query_params["status"])
        runs = list(qs.order_by("-pay_period__period_start", "pay_period__cycle__code")[:200])
        return Response({"results": [services.run_dict(r) for r in runs], "can_manage": _can_manage(request)}, headers=NO_STORE)

    def post(self, request):
        period = get_object_or_404(PayPeriod.objects.select_related("cycle"), pk=_data(request).get("period_id"))
        run = services.calculate(period, user=request.user, request=request)
        run = _run(run.pk)
        return Response({"run": services.run_dict(run), "feedback": (
            f"Planilla {run.payroll.payroll_code} calculada: {run.employees} colaboradores, líquido total "
            f"{services.money(run.payroll.total_net)} {run.payroll.currency_code}"
            + (f" ({len(run.warnings)} advertencias)." if run.warnings else "."))}, status=status.HTTP_201_CREATED)


class RunDetailView(_View):
    method_permissions = {"get": Perm.PAYROLL_VIEW}

    def get(self, request, pk):
        run = _run(pk)
        search = str(request.query_params.get("search") or "").strip()
        cost_center = str(request.query_params.get("cost_center") or "").strip()
        rows = services.detail_rows(run, search=search, cost_center=cost_center)
        if request.query_params.get("export") == "csv":
            return _csv(run, rows)
        return Response({"run": services.run_dict(run), "rows": rows, "can_manage": _can_manage(request)}, headers=NO_STORE)


def _csv(run: PayrollRun, rows: list[dict]) -> HttpResponse:
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="planilla-{run.payroll.payroll_code}.csv"'
    response.write("﻿")
    w = csv.writer(response)
    w.writerow(["ID", "Colaborador", "Centro de costos", "Salario base mensual", "Rate por hora", "Horas programadas", "Horas pagadas",
                "Horas no pagadas", "Horas nocturnas", "Horas feriado", "Horas extra (monto)", "Otros devengos", "Devengado",
                "Base gravada", "Descuentos", "Líquido", "Aportes patronales", "Boleta"])
    for r in rows:
        w.writerow([r["employee_code"], r["full_name"], r["cost_center"] or "", r["base_salary"], r["hourly_rate"] or "",
                    r["horas_programadas_hours"] or 0, r["horas_pagadas_hours"] or 0, r["horas_no_pagadas_hours"] or 0,
                    r["nocturnidad_hours"] or 0, r["feriado_hours"] or 0, r["overtime_amount"], r["other_earnings"], r["gross_pay"],
                    r["taxable_base"], r["total_deductions"], r["net_pay"], r["employer_contributions"],
                    (r["payslip"] or {}).get("folio", "")])
    return response


class RunEmployeeView(_View):
    method_permissions = {"get": Perm.PAYROLL_VIEW}

    def get(self, request, pk, code):
        return Response(services.employee_breakdown(_run(pk), str(code).upper()), headers=NO_STORE)


class RunActionView(_View):
    method_permissions = {"post": Perm.PAYROLL_MANAGE}

    def post(self, request, pk, action):
        run = _run(pk)
        if action == "recalculate":
            services.calculate(run.pay_period, user=request.user, request=request)
            feedback = "Planilla recalculada."
        elif action == "approve":
            out = services.approve(run, user=request.user, request=request)
            feedback = f"Planilla cerrada: {out['payslips']} boletas generadas en {out['batches']} lotes por departamento."
        elif action == "pay":
            services.mark_paid(run, user=request.user, request=request)
            feedback = "Planilla marcada como pagada."
        elif action == "cancel":
            services.cancel(run, reason=_data(request).get("reason"), user=request.user, request=request)
            feedback = "Planilla anulada: sus AP quedan libres para otra planilla."
        else:
            return Response({"detail": "Acción no válida."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"run": services.run_dict(_run(pk)), "feedback": feedback})


class SettingsView(_View):
    method_permissions = {"get": Perm.PAYROLL_VIEW, "post": Perm.PAYROLL_MANAGE}

    def get(self, request):
        from apps.scheduling.models import NightRule

        types = DeductionType.objects.filter(is_active=True).prefetch_related("brackets").order_by("country_id", "calculation_order", "code", "-effective_start_date")
        return Response({
            "settings": [services.setting_dict(s) for s in PayrollSetting.objects.order_by("country_id", "-effective_start_date")],
            "concepts": [services.concept_dict(c) for c in PayConcept.objects.all()],
            "deduction_types": [services.deduction_type_dict(t) for t in types],
            "night_rules": [{"country": r.country_id, "name": r.name, "start": r.start_time.strftime("%H:%M"), "end": r.end_time.strftime("%H:%M"),
                             "surcharge_percent": r.surcharge_percent, "effective_start_date": r.effective_start_date,
                             "effective_end_date": r.effective_end_date} for r in NightRule.objects.filter(is_active=True)],
            "countries": [{"id": c.country_id, "code": c.country_code, "name": c.country_name} for c in Country.objects.filter(is_active=True)],
            "can_manage": _can_manage(request),
        }, headers=NO_STORE)

    def post(self, request):
        s = services.save_setting(_data(request), user=request.user, request=request)
        return Response({"setting": services.setting_dict(s), "feedback": f"Nueva vigencia «{s.name}» creada."}, status=status.HTTP_201_CREATED)


class SettingDetailView(_View):
    method_permissions = {"patch": Perm.PAYROLL_MANAGE}

    def patch(self, request, pk):
        s = services.save_setting(_data(request), instance=get_object_or_404(PayrollSetting, pk=pk), user=request.user, request=request)
        return Response({"setting": services.setting_dict(s), "feedback": "Parámetros guardados."})


class ConceptView(_View):
    method_permissions = {"patch": Perm.PAYROLL_MANAGE}
    FIELDS = ("name", "affects_social_security", "affects_income_tax", "is_active", "description", "display_order")

    def patch(self, request, code):
        c = get_object_or_404(PayConcept, code=str(code).upper())
        data = _data(request)
        for f in self.FIELDS:
            if f in data:
                setattr(c, f, data[f])
        c.full_clean()
        c.save()
        services.record("payroll_concept_updated", services.Category.PAYROLL, f"Concepto {c.code} actualizado.", request=request,
                        target_type="PayConcept", target_id=c.code, details={f: data[f] for f in self.FIELDS if f in data})
        return Response({"concept": services.concept_dict(c), "feedback": f"Concepto {c.code} guardado."})


class DeductionVersionView(_View):
    method_permissions = {"post": Perm.PAYROLL_MANAGE}

    def post(self, request, pk):
        source = get_object_or_404(DeductionType, pk=pk)
        new = services.new_deduction_version(source, _data(request), user=request.user, request=request)
        return Response({"deduction_type": services.deduction_type_dict(new),
                         "feedback": f"Nueva vigencia de {new.code} desde el {services.fmt(new.effective_start_date)}."},
                        status=status.HTTP_201_CREATED)


class PayslipsView(_View):
    method_permissions = {"get": Perm.PAYROLL_VIEW}

    def get(self, request):
        params = request.query_params
        base = Payslip.objects.filter(services.filter_payslips(params))
        page = _int(params.get("page"), 1, 1, 100000)
        size = _int(params.get("page_size"), 50, 1, MAX_PAGE_SIZE)
        total = base.count()
        rows = services.payslip_queryset().filter(pk__in=base.values("pk")).order_by("-period_end", "folio")[(page - 1) * size: page * size]
        # Los contadores de cabecera ignoran los filtros de estado (impresa / firma / archivo) para mostrar el avance del lote.
        scope_params = {k: v for k, v in params.items() if k not in ("printed", "signature", "archived", "page", "page_size")}
        return Response({
            "count": total, "page": page, "page_size": size, "pages": max(1, -(-total // size)),
            "results": [services.payslip_row(s) for s in rows],
            "summary": services.inventory_counts(Payslip.objects.filter(services.filter_payslips(scope_params))),
            "can_manage": _can_manage(request),
        }, headers=NO_STORE)


class PayslipDetailView(_View):
    method_permissions = {"get": Perm.PAYROLL_VIEW}

    def get(self, request, pk):
        s = get_object_or_404(services.payslip_queryset(), pk=pk)
        return Response({**services.payslip_row(s), "content": s.content, "content_hash": s.content_hash,
                         "verified": services.content_hash(s.content) == s.content_hash}, headers=NO_STORE)


class PayslipPrintView(_View):
    method_permissions = {"get": Perm.PAYROLL_VIEW}

    def get(self, request):
        qs = services.payslip_queryset()
        ids = [int(x) for x in str(request.query_params.get("ids") or "").split(",") if x.strip().isdigit()]
        if ids:
            qs = qs.filter(pk__in=ids)
        elif request.query_params.get("batch"):
            qs = qs.filter(batch_id=request.query_params["batch"]) if str(request.query_params["batch"]).isdigit() else qs.filter(batch__code=request.query_params["batch"])
        else:
            qs = qs.filter(services.filter_payslips(request.query_params))
        slips = list(qs.order_by("cost_center__code", "employee__employee_code")[:500])
        return Response({"results": [{**services.payslip_row(s), "content": s.content, "content_hash": s.content_hash} for s in slips]},
                        headers=NO_STORE)


class PayslipActionView(_View):
    method_permissions = {"post": Perm.PAYROLL_MANAGE}

    def post(self, request):
        data = _data(request)
        ids = data.get("ids") if isinstance(data.get("ids"), list) else []
        try:
            ids = [int(x) for x in ids]
        except (TypeError, ValueError):
            return Response({"detail": "«ids» debe ser una lista de números."}, status=status.HTTP_400_BAD_REQUEST)
        out = services.inventory_action(ids, data.get("action"), user=request.user, data=data, request=request)
        return Response(out)


class BatchesView(_View):
    method_permissions = {"get": Perm.PAYROLL_VIEW}

    def get(self, request):
        return Response({"results": services.batch_rows(request.query_params), "can_manage": _can_manage(request)}, headers=NO_STORE)


class BatchDetailView(_View):
    method_permissions = {"patch": Perm.PAYROLL_MANAGE}

    def patch(self, request, pk):
        b = get_object_or_404(PayslipBatch, pk=pk)
        data = _data(request)
        if "archive_location" in data:
            b.archive_location = str(data["archive_location"] or "").strip()[:150]
        if "notes" in data:
            b.notes = str(data["notes"] or "").strip()[:300]
        b.save(update_fields=["archive_location", "notes"])
        services.record("payslip_batch_updated", services.Category.PAYROLL, f"Lote {b.code}: ubicación «{b.archive_location}».",
                        request=request, target_type="PayslipBatch", target_id=str(b.pk))
        return Response({"feedback": f"Lote {b.code} actualizado."})



# ================================================================ Fase 21: pre-cierre, portal, excepciones, cuentas, liquidaciones
from apps.payroll import portal, settlements  # noqa: E402
from apps.payroll.models import PayrollException, Settlement, SettlementBatch  # noqa: E402


class _Fase21View(_View):
    def handle_exception(self, exc):
        if isinstance(exc, settlements.SettlementError):
            return Response({"detail": exc.message, "code": exc.code}, status=exc.status)
        if isinstance(exc, DatabaseError):
            text = str(exc)
            for number, message in (("50095", "SQL Server rechazó el cambio: la liquidación aprobada o pagada no cambia."),
                                    ("50096", "SQL Server rechazó el cambio: regla del lote de pago de liquidaciones."),
                                    ("uq_pay_settlement_check", "Ese número de cheque ya está en el lote.")):
                if number in text:
                    return Response({"detail": message, "code": f"sql_{number}"}, status=status.HTTP_409_CONFLICT)
        return super().handle_exception(exc)


class IterationsView(_View):
    method_permissions = {"get": Perm.PAYROLL_VIEW}

    def get(self, request, pk):
        run = _run(pk)
        return Response({"results": [portal.iteration_dict(i) for i in run.iteration_log.select_related("calculated_by")[:100]]},
                        headers=NO_STORE)


class MyPayslipsView(_View):
    """Portal del colaborador: sus boletas preliminares (antes del freeze) y finales."""

    method_permissions = {"get": Perm.SELF_SERVICE}

    def get(self, request):
        return Response(portal.my_payslips(request.user), headers=NO_STORE)


class ExceptionsView(_View):
    method_permissions = {"get": Perm.SELF_SERVICE, "post": Perm.SELF_SERVICE}

    def get(self, request):
        qs, scope = portal.exceptions_scope(request.user)
        p = request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"].upper())
        if str(p.get("payroll") or "").isdigit():
            qs = qs.filter(payroll_id=int(p["payroll"]))
        rows = [portal.exception_dict(x, request.user) for x in qs.order_by("status", "-created_at")[:500]]
        return Response({"scope": scope, "results": rows,
                         "open": sum(1 for r in rows if r["status"] == "OPEN"),
                         "categories": [{"value": v, "label": label} for v, label in PayrollException.Category.choices]},
                        headers=NO_STORE)

    def post(self, request):
        x = portal.report_exception(request.user, _data(request), request=request)
        return Response({"exception": portal.exception_dict(x, request.user),
                         "feedback": "Excepción enviada a su supervisor. Se revisa antes del cierre de la planilla."},
                        status=status.HTTP_201_CREATED)


class ExceptionDetailView(_View):
    method_permissions = {"post": Perm.SELF_SERVICE}

    def post(self, request, pk):
        x = get_object_or_404(PayrollException.objects.select_related("employee", "payroll"), pk=pk)
        data = _data(request)
        x = portal.resolve_exception(x, user=request.user, status=str(data.get("status") or "").upper(),
                                     response=data.get("response"), request=request)
        return Response({"exception": portal.exception_dict(x, request.user), "feedback": f"Excepción {x.get_status_display().lower()}."})


class AccountRulesView(_View):
    method_permissions = {"get": Perm.PAYROLL_VIEW}

    def get(self, request):
        return Response({**portal.account_rules_list(), "can_manage": _can_manage(request)}, headers=NO_STORE)


class AccountRuleView(_View):
    method_permissions = {"patch": Perm.PAYROLL_MANAGE}

    def patch(self, request, client_id):
        portal.save_account_rule(client_id, _data(request), user=request.user, request=request)
        return Response(portal.account_rules_list())


def _settlement(pk) -> Settlement:
    return get_object_or_404(Settlement.objects.select_related("employee", "employee__country", "batch", "termination_action"), pk=pk)


class SettlementsView(_Fase21View):
    method_permissions = {"get": Perm.PAYROLL_VIEW, "post": Perm.PAYROLL_MANAGE}

    def get(self, request):
        p = request.query_params
        qs = Settlement.objects.select_related("employee", "batch", "termination_action")
        if p.get("status"):
            qs = qs.filter(status__in=[x.strip().upper() for x in p["status"].split(",")])
        if p.get("unbatched") in {"1", "true"}:
            qs = qs.filter(batch__isnull=True)
        for term in str(p.get("search") or "").split():
            qs = qs.filter(Q(folio__icontains=term) | Q(employee__employee_code__icontains=term)
                           | Q(employee__first_name__icontains=term) | Q(employee__last_name__icontains=term))
        rows = [settlements.settlement_dict(s) for s in qs.order_by("-created_at")[:500]]
        return Response({"results": rows, "pending_terminations": settlements.pending_terminations(),
                         "reasons": [{"value": k, "label": v} for k, v in settlements.REASON_LABELS.items()],
                         "can_manage": _can_manage(request)}, headers=NO_STORE)

    def post(self, request):
        """Abre la liquidación de un colaborador terminado que no la tenga (p. ej. terminado antes de la Fase 21)."""
        data = _data(request)
        e = get_object_or_404(Employee.objects.select_related("country"), employee_code=str(data.get("employee_code") or "").upper())
        if e.employment_status != Employee.Status.TERMINATED or not e.termination_date:
            return Response({"detail": "El colaborador no está terminado: la liquidación nace de su AP de terminación."},
                            status=status.HTTP_400_BAD_REQUEST)
        s = settlements.open_settlement(e, reason=str(data.get("reason") or "RENUNCIA").upper(), termination_date=e.termination_date,
                                        user=request.user, request=request)
        return Response({"settlement": settlements.settlement_dict(_settlement(s.pk), detail=True)}, status=status.HTTP_201_CREATED)


class SettlementDetailView(_Fase21View):
    method_permissions = {"get": Perm.PAYROLL_VIEW, "post": Perm.PAYROLL_MANAGE}

    def get(self, request, pk):
        s = _settlement(pk)
        return Response({"settlement": settlements.settlement_dict(s, detail=True), "content": s.content,
                         "can_manage": _can_manage(request)}, headers=NO_STORE)

    def post(self, request, pk, action=None):
        s = _settlement(pk)
        data = _data(request)
        if action == "calculate":
            s = settlements.calculate(s, user=request.user, request=request)
            feedback = "Liquidación calculada."
        elif action == "approve":
            s = settlements.approve(s, user=request.user, request=request)
            feedback = "Liquidación aprobada y sellada: lista para su lote de pago."
        elif action == "cancel":
            s = settlements.cancel(s, reason=data.get("reason"), user=request.user, request=request)
            feedback = "Liquidación anulada."
        elif action == "lines":
            s = settlements.add_manual_line(s, data, user=request.user, request=request)
            feedback = "Ajuste agregado y liquidación recalculada."
        elif action == "remove-line":
            s = settlements.remove_manual_line(s, int(data.get("line_id") or 0), user=request.user, request=request)
            feedback = "Ajuste retirado y liquidación recalculada."
        elif action == "check":
            s = settlements.set_check(s, data.get("check_number"))
            feedback = "Número de cheque asignado."
        else:
            return Response({"detail": "Acción no válida."}, status=status.HTTP_404_NOT_FOUND)
        warnings = getattr(s, "_warnings", [])
        s = _settlement(s.pk)
        s._warnings = warnings
        return Response({"settlement": settlements.settlement_dict(s, detail=True), "content": s.content, "feedback": feedback})


class SettlementBatchesView(_Fase21View):
    method_permissions = {"get": Perm.PAYROLL_VIEW, "post": Perm.PAYROLL_MANAGE}

    def get(self, request):
        return Response({"results": [settlements.batch_dict(b) for b in SettlementBatch.objects.all()[:200]],
                         "methods": [{"value": v, "label": label} for v, label in SettlementBatch.Method.choices],
                         "can_manage": _can_manage(request)}, headers=NO_STORE)

    def post(self, request):
        b = settlements.create_batch(_data(request), user=request.user, request=request)
        return Response({"batch": settlements.batch_dict(b, detail=True), "feedback": f"Lote {b.code} creado."},
                        status=status.HTTP_201_CREATED)


class SettlementBatchDetailView(_Fase21View):
    method_permissions = {"get": Perm.PAYROLL_VIEW, "post": Perm.PAYROLL_MANAGE}

    def get(self, request, pk):
        return Response({"batch": settlements.batch_dict(get_object_or_404(SettlementBatch, pk=pk), detail=True),
                         "can_manage": _can_manage(request)}, headers=NO_STORE)

    def post(self, request, pk, action=None):
        b = get_object_or_404(SettlementBatch, pk=pk)
        data = _data(request)
        if action == "add":
            out = settlements.add_to_batch(b, data.get("settlements") or [], user=request.user, request=request,
                                           first_check=data.get("first_check"))
            feedback = f"{out['added']} liquidación(es) agregada(s) al lote."
        elif action == "remove":
            settlements.remove_from_batch(b, int(data.get("settlement_id") or 0), user=request.user, request=request)
            feedback = "Liquidación retirada del lote."
        elif action in ("close", "reopen", "pay"):
            b = settlements.batch_transition(b, action, user=request.user, request=request)
            feedback = {"close": "Lote cerrado: listo para imprimir cheques y pagar.", "reopen": "Lote reabierto.",
                        "pay": "Lote pagado: sus liquidaciones quedan pagadas."}[action]
        else:
            return Response({"detail": "Acción no válida."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"batch": settlements.batch_dict(SettlementBatch.objects.get(pk=b.pk), detail=True), "feedback": feedback})
