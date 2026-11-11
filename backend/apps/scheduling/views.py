"""API de horarios, tiempo por fecha de ocurrencia y cortes de nómina (Fase 8).

GET    /scheduling/catalogs/                                   reglas de nocturnidad, ciclos, opciones
GET    /scheduling/employees/{ID}/assignments/             horarios vigentes (los crea una Acción de Personal)
POST   /scheduling/schedule-preview/                       {schedule, country, effective_date} -> horas diurnas/nocturnas por día
GET    /scheduling/employees/{ID}/timeline/?from=&to=          turnos, registros y resumen por fecha de ocurrencia
GET    /scheduling/employees/{ID}/days/{AAAA-MM-DD}/           desglose de una fecha de ocurrencia (Fase 10)
GET    /scheduling/time-records/?employee=&from=&to=&source=   registros de tiempo (consulta)
POST   /scheduling/time-records/?dry_run=1                     } carga MANUAL retirada (Fase 10): 403 salvo
DELETE /scheduling/time-records/{pk}/                          } SCHEDULING_MANUAL_TIME_ENTRY=true; la base queda
POST   /scheduling/time-records/upload/?dry_run=1              } lista para el futuro Web Timer interno
GET    /scheduling/report/?from=&to=&period=&cutoff=&basis=&country=&search=&employee=&tolerance=&export=csv
GET    /scheduling/night-rules/  ·  /scheduling/lunch-rules/
GET    /scheduling/pay-cycles/?year=&frequency=                ciclos con sus periodos de PAGO del año y, aparte, los
                                                               CORTES internos de asistencia que se pagan en ellos (Fase 11)
POST   /scheduling/pay-cycles/{code}/generate/                 {year} periodos de pago + cortes
GET    /scheduling/pay-periods/{id}/hours/?export=csv          horas para planilla: suma de los cortes mapeados al periodo
POST   /scheduling/cutoffs/{id}/close/  ·  /reopen/            cerrar / reabrir un corte de asistencia
"""

import csv
from datetime import timedelta

from django.conf import settings
from django.db import DatabaseError, transaction
from django.db.models import Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasActionPermission, PasswordChangeNotRequired, user_permissions
from apps.accounts.roles import Perm
from apps.common.models import Country
from apps.employees.parsers import FileFormatError, parse_records, parse_upload
from apps.hcm.models import Employee
from apps.scheduling import engine, services
from apps.scheduling.models import (
    AttendanceCutoff, LunchRule, NightRule, PayCycle, PayPeriod, ScheduleAssignment, TimeRecord, TimeRecordDay,
)

PERMISSIONS = [IsAuthenticated, PasswordChangeNotRequired, HasActionPermission]
NO_STORE = {"Cache-Control": "no-store"}
TRUE = {"1", "true", "yes", "si", "sí"}


def _flag(request, name: str) -> bool:
    value = request.query_params.get(name)
    if value is None and isinstance(request.data, dict):
        value = request.data.get(name)
    return str(value).strip().lower() in TRUE if value is not None else False


def _date_param(request, name: str, default=None):
    raw = request.query_params.get(name, "").strip()
    if not raw:
        return default
    parsed = services.parse_any_date(raw)
    if parsed is None:
        raise ValidationError({name: "Use el formato AAAA-MM-DD."})
    return parsed


def _employee(code: str) -> Employee:
    return get_object_or_404(Employee.objects.select_related("country"), employee_code=code.upper())


def _sql_error(exc: DatabaseError) -> Response:
    text = str(exc)
    for number, message in (
        ("50040", "SQL Server rechazó el horario: se traslapa con otro horario activo del empleado."),
        ("50041", "SQL Server rechazó el registro: se traslapa con otro registro de tiempo del empleado."),
        ("50042", "SQL Server rechazó la regla: ya hay otra regla de nocturnidad activa para el país en esas fechas."),
        ("50043", "SQL Server rechazó el periodo de pago: se traslapa con otro periodo de pago del ciclo."),
        ("50044", "SQL Server rechazó el corte: su ventana de asistencia se traslapa con la de otro corte del ciclo."),
        ("50045", "SQL Server rechazó el periodo de pago: debe iniciar el día siguiente al fin del periodo anterior (sin huecos ni colisiones)."),
        ("50046", "SQL Server rechazó el corte: debe iniciar el día siguiente al cierre del corte anterior (sin huecos ni colisiones)."),
        ("50047", "SQL Server rechazó la regla: ya hay otra regla de almuerzo activa del país con el mismo umbral en esas fechas."),
        ("50048", "SQL Server rechazó el corte: se mapea al periodo de pago de su ciclo que contiene su fecha de cierre."),
        ("50049", "SQL Server rechazó el cambio: el corte está cerrado; reábralo antes de modificar sus fechas."),
    ):
        if number in text:
            return Response({"detail": message, "code": f"sql_{number}"}, status=status.HTTP_409_CONFLICT)
    raise exc


class _View(APIView):
    permission_classes = PERMISSIONS
    method_permissions: dict = {}

    @property
    def action(self):  # HasActionPermission resuelve el permiso por método HTTP
        return self.request.method.lower()

    @property
    def action_permissions(self):
        return self.method_permissions


def _check_body(check: services.Check, feedback: str | None = None) -> dict:
    body = check.as_dict()
    if check.errors:
        body["detail"] = " ".join(e["message"] for e in check.errors)
    elif feedback:
        body["feedback"] = feedback + (" " + " ".join(w["message"] for w in check.warnings) if check.warnings else "")
    return body


# ================================================================ catálogos
class CatalogsView(_View):
    method_permissions = {"get": Perm.SCHEDULES_VIEW}

    def get(self, request):
        perms = user_permissions(request.user)
        rules = NightRule.objects.select_related("country").filter(is_active=True).order_by("country_id", "-effective_start_date")
        cycles = PayCycle.objects.select_related("country").filter(is_active=True)
        lunch = LunchRule.objects.select_related("country").filter(is_active=True).order_by("country_id", "min_block_minutes")
        return Response({
            "lunch_allocations": [{"value": k, "label": v} for k, v in engine.LUNCH_ALLOCATIONS.items()],
            "days": [{"key": k, "label": engine.DAY_LABELS[k]} for k in engine.DAY_KEYS],
            "night_rules": [_night_rule_dict(r) for r in rules],
            "lunch_rules": [{**services.lunch_rule_dict(r), "country": r.country.country_code} for r in lunch],
            "assignment_modes": [{"value": v, "label": label} for v, label in ScheduleAssignment.Mode.choices],
            "manual_time_entry": settings.SCHEDULING_MANUAL_TIME_ENTRY,
            "pay_cycles": [_cycle_dict(c) for c in cycles],
            "sources": [{"value": v, "label": label} for v, label in TimeRecord.Source.choices],
            "flags": [{"value": k, "label": v} for k, v in services.FLAG_LABELS.items()],
            "countries": [{"code": c.country_code, "name": c.country_name} for c in Country.objects.filter(is_active=True)],
            "can_manage": Perm.SCHEDULES_MANAGE in perms,
            "can_manage_cycles": Perm.PAYROLL_MANAGE in perms,
        }, headers=NO_STORE)


def _night_rule_dict(r: NightRule) -> dict:
    return {
        "id": r.pk, "country": r.country.country_code, "name": r.name,
        "start_time": r.start_time.strftime("%H:%M"), "end_time": r.end_time.strftime("%H:%M"),
        "surcharge_percent": float(r.surcharge_percent), "effective_start_date": r.effective_start_date,
        "effective_end_date": r.effective_end_date, "legal_reference": r.legal_reference, "is_active": r.is_active,
    }


def _cycle_dict(c: PayCycle) -> dict:
    return {
        "code": c.code, "name": c.name, "country": c.country.country_code,
        "pay_frequency": c.pay_frequency, "pay_frequency_label": c.get_pay_frequency_display(),
        "period_rule": c.period_rule, "period_rule_label": c.get_period_rule_display(), "rule_description": c.rule_description,
        "period_start_day": c.period_start_day, "crosses_month": c.period_rule != "FIXED_DAYS" and c.period_start_day > 1,
        "first_half_end_day": c.first_half_end_day, "length_days": c.length_days, "anchor_date": c.anchor_date,
        "cutoff_rule_description": c.cutoff_rule_description, "has_own_cutoffs": c.has_own_cutoffs,
        "cutoff_start_day": c.cutoff_start_day, "cutoff_first_end_day": c.cutoff_first_end_day,
        "cutoffs_cross_month": c.has_own_cutoffs and (c.cutoff_start_day or 1) > 1,
        "cutoff_lag_days": c.cutoff_lag_days, "payment_lag_days": c.payment_lag_days,
        "is_default": c.is_default, "is_active": c.is_active, "notes": c.notes,
    }


class NightRulesView(_View):
    method_permissions = {"get": Perm.SCHEDULES_VIEW}

    def get(self, request):
        rules = NightRule.objects.select_related("country").order_by("country_id", "-effective_start_date")
        return Response({"results": [_night_rule_dict(r) for r in rules]})


class LunchRulesView(_View):
    """Horas mínimas de jornada continua para recibir almuerzo, por país (se parametrizan en /admin/)."""

    method_permissions = {"get": Perm.SCHEDULES_VIEW}

    def get(self, request):
        rules = LunchRule.objects.select_related("country").order_by("country_id", "min_block_minutes", "-effective_start_date")
        return Response({"results": [{**services.lunch_rule_dict(r), "country": r.country.country_code, "is_active": r.is_active} for r in rules]})


# ================================================================ horarios vigentes (solo lectura: los crea una AP)
class EmployeeAssignmentsView(_View):
    method_permissions = {"get": Perm.SCHEDULES_VIEW}

    def get(self, request, code: str):
        employee = _employee(code)
        today = timezone.localdate()
        rows = ScheduleAssignment.objects.filter(employee=employee).select_related("personnel_action__action_type").order_by("-effective_start_date")
        current = next((a for a in rows if a.covers(today) and a.mode == ScheduleAssignment.Mode.PRIMARY), None)
        return Response({
            "employee_code": employee.employee_code, "full_name": employee.full_name,
            "country": employee.country.country_code, "hire_date": employee.hire_date,
            "current": services.assignment_dict(current, today) if current else None,
            "current_all": [services.assignment_dict(a, today) for a in rows if a.covers(today)],
            "results": [services.assignment_dict(a, today) for a in rows],
        }, headers=NO_STORE)


class SchedulePreviewView(_View):
    method_permissions = {"post": Perm.SCHEDULES_VIEW}

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        on = services.parse_any_date(data.get("effective_date")) or timezone.localdate()
        country = Country.objects.filter(country_code=str(data.get("country") or "").upper()).first()
        try:
            body = services.preview_schedule(data.get("schedule"), country_id=country.country_id if country else None, on=on, start=on)
        except engine.DefinitionError as exc:
            return Response({"valid": False, "errors": exc.errors, "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"valid": True, **body})


# ================================================================ línea de tiempo del empleado
class EmployeeTimelineView(_View):
    method_permissions = {"get": Perm.SCHEDULES_VIEW}

    def get(self, request, code: str):
        employee = _employee(code)
        today = timezone.localdate()
        date_from = _date_param(request, "from", today - timedelta(days=today.weekday()))
        date_to = _date_param(request, "to", date_from + timedelta(days=6))
        if date_to < date_from:
            raise ValidationError({"to": "«Hasta» no puede ser anterior a «desde»."})
        if (date_to - date_from).days > 62:
            raise ValidationError({"to": "Consulte como máximo 62 días."})
        rules = services.NightRules([employee.country_id])
        instances = services.employee_instances(employee, date_from - timedelta(days=1), date_to, rules=rules)
        instances = [i for i in instances if any(date_from <= s.occurrence_date <= date_to for s in i.segments)]
        records = TimeRecord.objects.filter(
            Q(days__occurrence_date__range=(date_from, date_to)), employee=employee,
        ).distinct().select_related("employee", "created_by").prefetch_related(Prefetch("days", TimeRecordDay.objects.order_by("occurrence_date")))
        report = services.hours_report([employee], date_from, date_to, include_empty=True)
        cycle = services.cycle_for(employee)
        cutoffs = []
        if cycle:
            cutoffs = [services.cutoff_dict(c) for c in cycle.cutoffs.select_related("cycle", "pay_period", "closed_by").filter(
                cutoff_start__lte=date_to, cutoff_end__gte=date_from)]
        return Response({
            "employee_code": employee.employee_code, "full_name": employee.full_name, "country": employee.country.country_code,
            "from": date_from, "to": date_to,
            "instances": [i.as_dict() for i in instances],
            "records": [services.time_record_dict(r) for r in records],
            "days": report["rows"], "totals": report["totals"], "cutoffs": cutoffs,
            "night_rule": _night_rule_dict(rules.rule_for(employee.country_id, date_to)) if rules.rule_for(employee.country_id, date_to) else None,
        }, headers=NO_STORE)


class EmployeeDayView(_View):
    """Pantalla de desglose de una fecha de ocurrencia (enlace desde el reporte y la semana del expediente)."""

    method_permissions = {"get": Perm.SCHEDULES_VIEW}

    def get(self, request, code: str, day: str):
        employee = _employee(code)
        d = services.parse_any_date(day)
        if d is None:
            raise ValidationError({"date": "Use el formato AAAA-MM-DD."})
        return Response(services.day_detail(employee, d), headers=NO_STORE)


# ================================================================ registros de tiempo
MANUAL_DISABLED = (
    "La carga manual de registros de tiempo está retirada temporalmente por el riesgo de manipulación incorrecta. "
    "Las horas reales llegarán del futuro Web Timer interno."
)


def _manual_disabled() -> Response | None:
    if settings.SCHEDULING_MANUAL_TIME_ENTRY:
        return None
    return Response({"detail": MANUAL_DISABLED, "code": "manual_time_disabled"}, status=status.HTTP_403_FORBIDDEN)


class TimeRecordsView(_View):
    method_permissions = {"get": Perm.SCHEDULES_VIEW, "post": Perm.SCHEDULES_MANAGE}

    def get(self, request):
        today = timezone.localdate()
        date_from = _date_param(request, "from", today - timedelta(days=13))
        date_to = _date_param(request, "to", today)
        qs = TimeRecord.objects.filter(occurrence_date__range=(date_from, date_to)).select_related("employee", "created_by").prefetch_related("days")
        code = request.query_params.get("employee", "").strip().upper()
        if code:
            qs = qs.filter(employee__employee_code=code)
        source = request.query_params.get("source", "").strip().upper()
        if source:
            qs = qs.filter(source=source)
        country = request.query_params.get("country", "").strip().upper()
        if country:
            qs = qs.filter(employee__country__country_code=country)
        total = qs.count()
        page, size = _page(request, default_size=50)
        rows = qs.order_by("-occurrence_date", "employee__employee_code", "start_at")[(page - 1) * size: page * size]
        return Response({"count": total, "results": [services.time_record_dict(r) for r in rows]}, headers=NO_STORE)

    def post(self, request):
        if (blocked := _manual_disabled()) is not None:
            return blocked
        if not isinstance(request.data, dict):
            raise ValidationError({"detail": "Envíe {employee_code, start_at, end_at} o {employee_code, occurrence_date, minutes|hours}."})
        employee = _employee(str(request.data.get("employee_code") or "-"))
        data = dict(request.data)
        data.setdefault("source", TimeRecord.Source.MANUAL)
        check = services.check_time_record(employee, data)
        if not check.ok or _flag(request, "dry_run"):
            body = _check_body(check, "Datos válidos.")
            if check.ok:
                c = check.cleaned
                if c["kind"] == TimeRecord.Kind.INTERVAL:
                    body["segments"] = [s.as_dict() for s in engine.segments_for_interval(
                        c["start_at"], c["end_at"], night_lookup=services.NightRules([employee.country_id]).lookup(employee.country_id))]
            return Response(body, status=status.HTTP_200_OK if check.ok else status.HTTP_400_BAD_REQUEST)
        try:
            with transaction.atomic():
                rec = services.create_time_record(employee, check, user=request.user, request=request)
        except DatabaseError as exc:
            return _sql_error(exc)
        rec = TimeRecord.objects.select_related("employee", "created_by").prefetch_related("days").get(pk=rec.pk)
        return Response({**_check_body(check, "Registro guardado por fecha de ocurrencia."), "record": services.time_record_dict(rec)},
                        status=status.HTTP_201_CREATED)


class TimeRecordDetailView(_View):
    method_permissions = {"delete": Perm.SCHEDULES_MANAGE}

    def delete(self, request, pk: int):
        if (blocked := _manual_disabled()) is not None:
            return blocked
        rec = get_object_or_404(TimeRecord.objects.select_for_update().select_related("employee"), pk=pk)
        check = services.check_time_record_delete(rec)
        if not check.ok:
            return Response(_check_body(check), status=status.HTTP_400_BAD_REQUEST)
        services.delete_time_record(rec, user=request.user, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TimeRecordUploadView(_View):
    method_permissions = {"post": Perm.SCHEDULES_MANAGE}
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        if (blocked := _manual_disabled()) is not None:
            return blocked
        dry_run = _flag(request, "dry_run")
        try:
            upload = request.FILES.get("file")
            if upload is not None:
                parsed = parse_upload(upload.read(), upload.name, upload.content_type)
            elif isinstance(request.data, dict) and isinstance(request.data.get("rows"), list):
                parsed = parse_records(request.data["rows"], "registros.json")
            else:
                raise ValidationError({"file": "Adjunte un archivo CSV, Excel (.xlsx) o JSON en el campo «file»."})
        except FileFormatError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)
        source = str(request.data.get("source") or "IMPORT").upper() if isinstance(request.data, dict) else "IMPORT"
        if source not in TimeRecord.Source.values:
            source = "IMPORT"
        try:
            with transaction.atomic():
                result = services.process_time_upload(parsed, user=request.user, dry_run=dry_run, default_source=source, request=request)
        except DatabaseError as exc:
            return _sql_error(exc)
        result["file_name"] = parsed.file_name
        return Response(result, status=status.HTTP_400_BAD_REQUEST if result["errors"] and not dry_run else status.HTTP_200_OK)


# ================================================================ reporte teórico vs real
def _page(request, default_size=100, max_size=500):
    try:
        page = max(1, int(request.query_params.get("page", 1)))
    except ValueError:
        page = 1
    try:
        size = max(1, min(int(request.query_params.get("page_size", default_size)), max_size))
    except ValueError:
        size = default_size
    return page, size


REPORT_COLUMNS = [
    ("employee_code", "ID corporativo"), ("full_name", "Empleado"), ("country", "País"),
    ("occurrence_date", "Fecha de ocurrencia"), ("weekday", "Día"), ("actions", "AP de horario"),
    ("shift_dates", "Fecha(s) de turno"), ("scheduled_minutes", "Min. teóricos"),
    ("scheduled_night_minutes", "Min. teóricos nocturnos"), ("worked_minutes", "Min. reales"),
    ("worked_night_minutes", "Min. reales nocturnos"), ("night_surcharge_percent", "Recargo nocturno %"),
    ("night_premium_minutes", "Min. equivalentes de recargo"), ("variance_minutes", "Diferencia (min)"),
    ("flag_label", "Resultado"),
]


class HoursReportView(_View):
    method_permissions = {"get": Perm.SCHEDULES_VIEW}

    def get(self, request):
        params = request.query_params
        today = timezone.localdate()
        period = cutoff = None
        basis = None
        employees = Employee.objects.select_related("country")
        if params.get("cutoff"):
            cutoff = get_object_or_404(AttendanceCutoff.objects.select_related("cycle__country", "pay_period", "closed_by"), pk=params["cutoff"])
            period, basis = cutoff.pay_period, "cutoff"
            date_from, date_to = cutoff.cutoff_start, cutoff.cutoff_end
            employees = employees.filter(country_id=cutoff.cycle.country_id, pay_frequency=cutoff.cycle.pay_frequency)
        elif params.get("period"):
            period = get_object_or_404(PayPeriod.objects.select_related("cycle__country"), pk=params["period"])
            basis = "period" if params.get("basis") == "period" else "cutoff"
            cuts = list(period.cutoffs.order_by("cutoff_start"))
            if basis == "cutoff" and cuts:  # horas de los cortes que se pagan en el periodo (ventanas contiguas)
                date_from, date_to = cuts[0].cutoff_start, cuts[-1].cutoff_end
            else:
                date_from, date_to = period.period_start, period.period_end
            employees = employees.filter(country_id=period.cycle.country_id, pay_frequency=period.cycle.pay_frequency)
        else:
            date_from = _date_param(request, "from", today - timedelta(days=today.weekday()))
            date_to = _date_param(request, "to", date_from + timedelta(days=6))
        if date_to < date_from:
            raise ValidationError({"to": "«Hasta» no puede ser anterior a «desde»."})
        if (date_to - date_from).days >= services.MAX_REPORT_DAYS:
            raise ValidationError({"to": f"Consulte como máximo {services.MAX_REPORT_DAYS} días."})
        country = params.get("country", "").strip().upper()
        if country:
            employees = employees.filter(country__country_code=country)
        code = params.get("employee", "").strip().upper()
        if code:
            employees = employees.filter(employee_code=code)
        search = params.get("search", "").strip()
        if search:
            for term in search.split():
                employees = employees.filter(
                    Q(employee_code__icontains=term) | Q(first_name__icontains=term) | Q(last_name__icontains=term)
                    | Q(second_last_name__icontains=term) | Q(middle_name__icontains=term)
                )
        with_schedule = ScheduleAssignment.objects.filter(effective_start_date__lte=date_to).filter(
            Q(effective_end_date__isnull=True) | Q(effective_end_date__gte=date_from - timedelta(days=1)))
        with_time = TimeRecordDay.objects.filter(occurrence_date__range=(date_from, date_to)).values("employee_id")
        employees = employees.filter(Q(pk__in=with_schedule.values("employee_id")) | Q(pk__in=with_time))
        try:
            tolerance = max(0, min(int(params.get("tolerance", 0)), 240))
        except ValueError:
            tolerance = 0
        report = services.hours_report(employees.order_by("employee_code"), date_from, date_to, tolerance=tolerance)
        rows = report["rows"]
        flag = params.get("flag", "").strip().upper()
        if flag:
            rows = [r for r in rows if r["flag"] == flag]

        if params.get("export") == "csv":
            response = HttpResponse(content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = f'attachment; filename="horas_teoricas_vs_reales_{date_from}_{date_to}.csv"'
            response.write("﻿")
            writer = csv.writer(response)
            writer.writerow([label for _, label in REPORT_COLUMNS])
            for r in rows:
                writer.writerow([
                    " / ".join(r[k]) if k == "actions" else " / ".join(d.isoformat() for d in r[k]) if k == "shift_dates" else r[k]
                    for k, _ in REPORT_COLUMNS
                ])
            return response

        page, size = _page(request)
        return Response({
            "from": date_from, "to": date_to, "tolerance": tolerance,
            "period": services.period_dict(period) if period else None,
            "cutoff": services.cutoff_dict(cutoff) if cutoff else None,
            "basis": basis,
            "count": len(rows), "results": rows[(page - 1) * size: page * size],
            "by_employee": report["by_employee"], "totals": report["totals"],
        }, headers=NO_STORE)


# ================================================================ ciclos: periodos de pago y cortes internos (Fase 11)
class PayCyclesView(_View):
    """Ciclos con sus PERIODOS DE PAGO de un año (por fecha de inicio) y, como dimensión aparte, los CORTES internos de
    asistencia que se pagan en esos periodos (el corte 25/12–09/01 aparece en enero, junto a la quincena 1–15 que lo
    paga). `years` = años con periodos generados, para agrupar."""

    method_permissions = {"get": Perm.SCHEDULES_VIEW}

    def get(self, request):
        today = timezone.localdate()
        try:
            year = int(request.query_params.get("year", today.year))
        except ValueError:
            year = today.year
        cycles = PayCycle.objects.select_related("country").order_by("country_id", "pay_frequency", "code")
        if not _flag(request, "include_inactive"):
            cycles = cycles.filter(is_active=True)
        country = request.query_params.get("country", "").strip().upper()
        if country:
            cycles = cycles.filter(country__country_code=country)
        frequency = request.query_params.get("frequency", "").strip().upper()
        if frequency:
            cycles = cycles.filter(pay_frequency=frequency)
        years = sorted(set(PayPeriod.objects.filter(cycle__in=cycles).values_list("period_start__year", flat=True).distinct())
                       | {today.year, year})
        out = []
        for c in cycles:
            periods = list(c.periods.select_related("cycle").filter(period_start__year=year).order_by("period_start"))
            cutoffs = list(c.cutoffs.select_related("cycle", "pay_period", "closed_by").filter(pay_period__in=periods).order_by("cutoff_start"))
            by_period: dict[int, list] = {}
            for cut in cutoffs:
                by_period.setdefault(cut.pay_period_id, []).append(cut)
            current_cut = c.cutoffs.filter(cutoff_start__lte=today, cutoff_end__gte=today).first()
            current_period = c.periods.filter(period_start__lte=today, period_end__gte=today).first()
            out.append({**_cycle_dict(c), "periods": [services.period_dict(p, by_period.get(p.pk, [])) for p in periods],
                        "stats": {"total": len(periods), "cutoffs": len(cutoffs),
                                  "closed": sum(1 for x in cutoffs if x.status == AttendanceCutoff.Status.CLOSED),
                                  "periods_without_cutoff": sum(1 for p in periods if p.pk not in by_period),
                                  "current": current_cut.code if current_cut else None,
                                  "current_period": current_period.code if current_period else None},
                        "preview": [] if periods else services.preview_cycle(c, year)})
        perms = user_permissions(request.user)
        return Response({
            "year": year, "years": years, "results": out, "can_manage": Perm.PAYROLL_MANAGE in perms,
            "frequencies": [{"value": v, "label": label} for v, label in Employee.PayFrequency.choices],
        }, headers=NO_STORE)


class PayCycleGenerateView(_View):
    method_permissions = {"post": Perm.PAYROLL_MANAGE}

    def post(self, request, code: str):
        cycle = get_object_or_404(PayCycle, code=code.upper(), is_active=True)
        try:
            year = int((request.data or {}).get("year"))
        except (TypeError, ValueError):
            raise ValidationError({"year": "Indique el año (p. ej. 2026)."}) from None
        if not 2000 <= year <= 2100:
            raise ValidationError({"year": "Año fuera de rango."})
        try:
            with transaction.atomic():
                result = services.generate_periods(cycle, year, user=request.user, request=request)
        except services.PeriodGenerationError as exc:
            return Response({"detail": str(exc), "code": "period_gap"}, status=status.HTTP_400_BAD_REQUEST)
        except DatabaseError as exc:
            return _sql_error(exc)
        existing = " y ".join(x for x in (
            f"{result['skipped']} periodos" if result["skipped"] else "",
            f"{result['cutoffs_skipped']} cortes" if result["cutoffs_skipped"] else "",
        ) if x)
        result["feedback"] = (f"Ciclo {cycle.code}, {year}: {result['created']} periodos de pago y {result['cutoffs_created']} cortes "
                              "de asistencia generados." + (f" {existing} ya existían y no se modificaron." if existing else ""))
        return Response(result)


class CutoffStatusView(_View):
    """Cerrar / reabrir un CORTE INTERNO de asistencia (el periodo de pago no tiene estado propio)."""

    method_permissions = {"post": Perm.PAYROLL_MANAGE}
    target = AttendanceCutoff.Status.CLOSED

    def post(self, request, pk: int):
        with transaction.atomic():
            cutoff = get_object_or_404(AttendanceCutoff.objects.select_for_update().select_related("cycle", "pay_period"), pk=pk)
            if cutoff.status == self.target:
                return Response({"detail": f"El corte {cutoff.code} ya está {cutoff.get_status_display().lower()}."},
                                status=status.HTTP_400_BAD_REQUEST)
            if self.target == AttendanceCutoff.Status.CLOSED and cutoff.cutoff_end >= timezone.localdate():
                return Response({"detail": f"El corte {cutoff.code} cierra el {services.fmt(cutoff.cutoff_end)}: se cierra después de esa fecha."},
                                status=status.HTTP_400_BAD_REQUEST)
            cutoff = services.set_cutoff_status(cutoff, self.target, user=request.user, request=request)
        return Response({"cutoff": services.cutoff_dict(cutoff),
                         "feedback": f"Corte {cutoff.code} {'cerrado' if self.target == AttendanceCutoff.Status.CLOSED else 'reabierto'}."})


PAYROLL_COLUMNS = [
    ("employee_code", "ID corporativo"), ("full_name", "Empleado"), ("country", "País"), ("pay_period", "Periodo de pago"),
    ("payment_date", "Fecha de pago"), ("cutoff", "Corte de asistencia"), ("cutoff_window", "Ventana de asistencia"),
    ("scheduled_minutes", "Min. teóricos"), ("worked_minutes", "Min. reales"), ("worked_night_minutes", "Min. reales nocturnos"),
    ("night_premium_minutes", "Min. equivalentes de recargo"), ("variance_minutes", "Diferencia (min)"),
]


class PayPeriodHoursView(_View):
    """Motor de horas para planilla: el periodo de PAGO toma las horas de los CORTES de asistencia mapeados a él."""

    method_permissions = {"get": Perm.SCHEDULES_VIEW}

    def get(self, request, pk: int):
        period = get_object_or_404(PayPeriod.objects.select_related("cycle__country"), pk=pk)
        result = services.payroll_hours(period)
        if request.query_params.get("export") == "csv":
            windows = {c["code"]: f"{services.fmt(c['cutoff_start'])}–{services.fmt(c['cutoff_end'])}" for c in result["cutoffs"]}
            response = HttpResponse(content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = f'attachment; filename="horas_planilla_{period.cycle.code}_{period.code}.csv"'
            response.write("﻿")
            writer = csv.writer(response)
            writer.writerow([label for _, label in PAYROLL_COLUMNS])
            for r in result["rows"]:
                for part in r["cutoffs"]:
                    values = {**r, **part, "pay_period": period.code, "payment_date": period.payment_date.isoformat(),
                              "cutoff_window": windows[part["cutoff"]],
                              "variance_minutes": part["worked_minutes"] - part["scheduled_minutes"]}
                    writer.writerow([values[k] for k, _ in PAYROLL_COLUMNS])
            return response
        return Response(result, headers=NO_STORE)
