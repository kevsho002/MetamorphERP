"""Fase 21 — Calendario de feriados y generación automática de Holiday Segments.

Un Holiday Segment es el CONTENEDOR de un feriado laborado: se genera cuando un colaborador registra tiempo (Web Timer u
otros registros) en una fecha feriada de su país. Cubre el bloque programado del turno de ese día o, si no estaba
programado, el tramo realmente trabajado. La planilla paga esas horas como salario regular + el recargo del feriado
(pago doble). Se regenera de forma idempotente (al conciliar la asistencia, al calcular la planilla o con
`manage.py holiday_segments`), y no interviene en la adherencia ni en la asistencia de WFM.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from apps.hcm.models import Employee
from apps.holidays.models import Holiday, HolidaySegment
from apps.system.audit import Category, record


class HolidayError(Exception):
    def __init__(self, message: str, code: str = "invalid", status: int = 400):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


def fmt(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


def holidays_between(country_ids, lo: date, hi: date) -> dict[tuple[int, date], Holiday]:
    qs = Holiday.objects.filter(is_active=True, country_id__in=set(country_ids), date__range=(lo, hi))
    return {(h.country_id, h.date): h for h in qs}


def holiday_on(country_id: int, d: date) -> Holiday | None:
    return Holiday.objects.filter(is_active=True, country_id=country_id, date=d).first()


def _employed(e: Employee, d: date) -> bool:
    return e.hire_date <= d and (e.termination_date is None or d <= e.termination_date)


@transaction.atomic
def generate_segments(employees, lo: date, hi: date, *, user=None, request=None, audit: bool = True) -> dict:
    """Crea / actualiza / quita los Holiday Segments de los colaboradores en [lo, hi]. Idempotente."""
    from apps.scheduling.models import TimeRecordDay
    from apps.scheduling.services import NightRules, ScheduleBook

    employees = list(employees)
    out = {"created": 0, "updated": 0, "removed": 0, "holidays": 0}
    if not employees:
        return out
    hols = holidays_between({e.country_id for e in employees}, lo, hi)
    out["holidays"] = len({h.pk for h in hols.values()})
    if not hols:
        return out
    dates = sorted({d for _, d in hols})
    ids = [e.pk for e in employees]
    worked = defaultdict(lambda: {"seconds": 0, "night": 0, "start": None, "end": None})
    for t in TimeRecordDay.objects.filter(employee_id__in=ids, occurrence_date__in=dates):
        w = worked[(t.employee_id, t.occurrence_date)]
        w["seconds"] += t.minutes * 60
        w["night"] += t.night_minutes * 60
        if t.start_at and t.end_at:
            w["start"] = min(filter(None, [w["start"], t.start_at]))
            w["end"] = max(filter(None, [w["end"], t.end_at]))
    rules = NightRules({e.country_id for e in employees})
    book = ScheduleBook(ids, min(dates) - timedelta(days=1), max(dates))
    existing = {(s.holiday_id, s.employee_id): s for s in HolidaySegment.objects.filter(employee_id__in=ids, holiday__in=set(hols.values()))}
    keep = set()
    for e in employees:
        lookup = rules.lookup(e.country_id)
        for d in dates:
            h = hols.get((e.country_id, d))
            if h is None or not _employed(e, d):
                continue
            w = worked.get((e.pk, d))
            if not w or w["seconds"] <= 0:
                continue
            blocks = [i for i in book.instances(e.pk, d, d, lookup) if i.shift_date == d]
            scheduled = sum(i.net_minutes for i in blocks) * 60
            if blocks:
                start, end = min(i.start for i in blocks), max(i.end for i in blocks)
            elif w["start"] and w["end"]:
                start, end = w["start"], w["end"]
            else:  # registro por horas sin tramo: el contenedor parte del inicio del día
                start = datetime.combine(d, time(0, 0))
                end = start + timedelta(seconds=w["seconds"])
            fields = {"shift_date": d, "start_at": start, "end_at": end, "scheduled_seconds": scheduled,
                      "worked_seconds": w["seconds"], "night_seconds": min(w["night"], w["seconds"]), "premium_percent": h.premium_percent}
            seg = existing.get((h.pk, e.pk))
            keep.add((h.pk, e.pk))
            if seg is None:
                HolidaySegment.objects.create(holiday=h, employee=e, **fields)
                out["created"] += 1
            elif any(getattr(seg, k) != v for k, v in fields.items()):
                for k, v in fields.items():
                    setattr(seg, k, v)
                seg.save()
                out["updated"] += 1
    stale = [s.pk for key, s in existing.items() if key not in keep]
    if stale:
        out["removed"] = HolidaySegment.objects.filter(pk__in=stale).delete()[0]
    if audit and (out["created"] or out["updated"] or out["removed"]):
        record("holiday_segments_generated", Category.WFM,
               f"Holiday Segments del {fmt(lo)} al {fmt(hi)}: {out['created']} nuevos, {out['updated']} actualizados, "
               f"{out['removed']} retirados.", request=request, actor=user, details=out)
    return out


def segment_seconds(employee_ids, lo: date, hi: date) -> dict[tuple[int, date], HolidaySegment]:
    return {(s.employee_id, s.shift_date): s for s in HolidaySegment.objects.filter(employee_id__in=list(employee_ids),
                                                                                   shift_date__range=(lo, hi)).select_related("holiday")}


# ================================================================ calendario
def holiday_dict(h: Holiday, segments: int | None = None) -> dict:
    return {"id": h.pk, "country": h.country_id, "date": h.date, "weekday": h.date.weekday(), "name": h.name, "kind": h.kind,
            "kind_label": h.get_kind_display(), "premium_percent": h.premium_percent, "legal_reference": h.legal_reference,
            "is_active": h.is_active, "segments": segments}


def segment_dict(s: HolidaySegment) -> dict:
    return {"id": s.pk, "holiday": s.holiday.name, "date": s.shift_date, "employee_code": s.employee.employee_code,
            "full_name": s.employee.full_name, "start_at": s.start_at, "end_at": s.end_at, "scheduled_seconds": s.scheduled_seconds,
            "worked_seconds": s.worked_seconds, "night_seconds": s.night_seconds, "premium_percent": s.premium_percent,
            "updated_at": s.updated_at}


def save_holiday(data: dict, *, holiday: Holiday | None = None, user=None, request=None) -> Holiday:
    from apps.common.models import Country
    from apps.personnel_actions.services import parse_date

    h = holiday or Holiday()
    if holiday is None:
        country = Country.objects.filter(Q(country_code=str(data.get("country") or "").upper()) | Q(pk=data.get("country_id") or 0)).first()
        if country is None:
            raise HolidayError("Indique el país del feriado.", "required")
        h.country_id = country.pk
    if "date" in data:
        d = parse_date(data.get("date"))
        if d is None:
            raise HolidayError("Fecha inválida (AAAA-MM-DD).", "invalid_date")
        if holiday is not None and d != holiday.date and holiday.segments.exists():
            raise HolidayError("El feriado ya generó Holiday Segments: no se cambia su fecha (desactívelo y cree otro).", "in_use", 409)
        h.date = d
    if "name" in data:
        h.name = str(data.get("name") or "").strip()[:120]
    if not h.name:
        raise HolidayError("Escriba el nombre del feriado.", "required")
    if "kind" in data:
        if data["kind"] not in Holiday.Kind.values:
            raise HolidayError("Tipo inválido.", "invalid_kind")
        h.kind = data["kind"]
    if "premium_percent" in data:
        try:
            pct = Decimal(str(data["premium_percent"]))
        except Exception:
            raise HolidayError("Recargo inválido.", "invalid") from None
        if not 0 <= pct <= 300:
            raise HolidayError("El recargo va de 0 % a 300 %.", "invalid")
        h.premium_percent = pct
    if "legal_reference" in data:
        h.legal_reference = str(data.get("legal_reference") or "")[:200]
    if "is_active" in data:
        h.is_active = bool(data["is_active"])
    if Holiday.objects.filter(country_id=h.country_id, date=h.date).exclude(pk=h.pk).exists():
        raise HolidayError(f"Ya hay un feriado el {fmt(h.date)} para ese país.", "duplicate", 409)
    if holiday is None and getattr(user, "pk", None):
        h.created_by = user
    h.save()
    record("holiday_saved", Category.PAYROLL, f"Feriado {h.name} ({fmt(h.date)}) {'actualizado' if holiday else 'registrado'}.",
           request=request, actor=user, target_type="Holiday", target_id=str(h.pk), details={"date": h.date.isoformat(), "kind": h.kind})
    return h


def copy_year(country_code: str, from_year: int, to_year: int, *, user=None, request=None) -> list[dict]:
    """Fase 23: copia los feriados de un año a otro (dbo.usp_HolidayCopyYear; Semana Santa con la Pascua del destino)."""
    from django.db import connection

    from apps.common.models import Country

    country = Country.objects.filter(country_code=str(country_code or "").upper()).first()
    if country is None:
        raise HolidayError("Indique el país.", "required")
    if not (2000 <= from_year <= 2100 and 2000 <= to_year <= 2100) or from_year == to_year:
        raise HolidayError("Años inválidos (el destino debe ser distinto del origen).", "invalid")
    with connection.cursor() as c:
        c.execute("EXEC dbo.usp_HolidayCopyYear @CountryId = %s, @FromYear = %s, @ToYear = %s, @UserId = %s",
                  [country.pk, from_year, to_year, getattr(user, "pk", None)])
        rows = [{"id": r[0], "date": r[1], "name": r[2]} for r in c.fetchall()] if c.description else []
    record("holiday_year_copied", Category.PAYROLL,
           f"{len(rows)} feriado(s) de {country.country_code} copiados de {from_year} a {to_year}.", request=request, actor=user,
           target_type="Holiday", target_id=country.country_code, details={"from": from_year, "to": to_year, "created": len(rows)})
    return rows


def delete_holiday(h: Holiday, *, user=None, request=None) -> None:
    if h.segments.exists():
        raise HolidayError("El feriado ya generó Holiday Segments: desactívelo en lugar de eliminarlo.", "in_use", 409)
    record("holiday_deleted", Category.PAYROLL, f"Feriado {h.name} ({fmt(h.date)}) eliminado.", request=request, actor=user,
           target_type="Holiday", target_id=str(h.pk))
    h.delete()
