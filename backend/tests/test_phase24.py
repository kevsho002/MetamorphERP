"""Fase 24: planilla alineada a los cortes internos de asistencia del ciclo predeterminado (del 25 al 9 y del 10 al 24;
el devengo sigue en la quincena 1–15 / 16–fin), realineación de cortes abiertos y adjuntos (evidencias) en las AP con
sus reglas de SQL Server y la bitácora de auditoría de la AP."""

import io
import zipfile
from datetime import date, datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, connection, transaction
from PIL import Image

from apps.payroll import services
from apps.personnel_actions.models import ActionAttachment, PersonnelAction
from apps.scheduling import services as sch
from apps.scheduling.models import AttendanceCutoff, PayCycle, PayPeriod, ScheduleAssignment, TimeRecord, TimeRecordDay

pytestmark = pytest.mark.django_db
PA = "/api/v1/personnel-actions"
DAY = {"days": {d: {"start": "08:00", "end": "17:00", "lunch_minutes": 60} for d in ("mon", "tue", "wed", "thu", "fri")}}


def _png(color=(200, 30, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buf, "PNG")
    return buf.getvalue()


def _docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"


# ================================================================== cortes internos 25–9 / 10–24
def test_default_cycle_counts_attendance_in_internal_cutoffs():
    cycle = PayCycle.objects.get(code="SV_QUINCENAL")
    assert (cycle.cutoff_start_day, cycle.cutoff_first_end_day) == (10, 24)
    q1 = PayPeriod.objects.get(cycle=cycle, code="2026-10-Q1")
    q2 = PayPeriod.objects.get(cycle=cycle, code="2026-10-Q2")
    # El devengo no cambia (1–15 y 16–31); la asistencia sí: del 25 al 9 y del 10 al 24.
    assert (q1.period_start, q1.period_end, q2.period_end) == (date(2026, 10, 1), date(2026, 10, 15), date(2026, 10, 31))
    assert services.windows_for(q1) == [(date(2026, 9, 25), date(2026, 10, 9))]
    assert services.windows_for(q2) == [(date(2026, 10, 10), date(2026, 10, 24))]
    # Continuidad de todo el ciclo: cada corte inicia el día siguiente al cierre del anterior.
    cuts = list(cycle.cutoffs.order_by("cutoff_start"))
    assert all((b.cutoff_start - a.cutoff_end).days == 1 for a, b in zip(cuts, cuts[1:]))
    # Un año nuevo se genera con la misma regla (cruza de mes: 25/12 al 09/01 se paga en la 1.ª quincena de enero).
    sch.generate_periods(cycle, 2027)
    jan = PayPeriod.objects.get(cycle=cycle, code="2027-01-Q1")
    assert services.windows_for(jan) == [(date(2026, 12, 25), date(2027, 1, 9))]


def test_payroll_hours_and_eligibility_follow_the_cutoff(make_employee):
    period = PayPeriod.objects.get(cycle__code="SV_QUINCENAL", code="2026-10-Q1")
    emp = make_employee("SV", hire_date=date(2026, 9, 1), base_salary=880, pay_frequency="BIWEEKLY")
    ScheduleAssignment.objects.create(employee=emp, definition=DAY, effective_start_date=date(2026, 9, 1))
    # Se retira el 28/09: no trabaja ningún día de la quincena 1–15/10, pero sí en el corte 25/09–09/10.
    gone = make_employee("SV", hire_date=date(2026, 9, 1), base_salary=880, pay_frequency="BIWEEKLY", termination_date=date(2026, 9, 28))
    ScheduleAssignment.objects.create(employee=gone, definition=DAY, effective_start_date=date(2026, 9, 1))
    for e, days in ((emp, (date(2026, 9, 25), date(2026, 10, 9), date(2026, 10, 12))), (gone, (date(2026, 9, 25),))):
        for d in days:
            start, end = datetime(d.year, d.month, d.day, 8), datetime(d.year, d.month, d.day, 17)
            rec = TimeRecord.objects.create(employee=e, kind="INTERVAL", start_at=start, end_at=end, occurrence_date=d, minutes=540, source="WEB_TIMER")
            TimeRecordDay.objects.create(record=rec, employee=e, occurrence_date=d, start_at=start, end_at=end, minutes=540)

    run = services.calculate(period)
    lines = {ln["code"]: ln for ln in services.employee_breakdown(run, emp.employee_code)["lines"]}
    # 25/09 (viernes) y 09/10 cuentan; el 12/10 (fuera del corte, ya en el siguiente) no.
    assert float(lines["HORAS_PAGADAS"]["quantity"]) == 16
    gone_lines = {ln["code"]: ln for ln in services.employee_breakdown(run, gone.employee_code)["lines"]}
    assert float(gone_lines["HORAS_PAGADAS"]["quantity"]) == 8


def test_realign_keeps_closed_cutoffs_and_makes_a_transition():
    cycle = PayCycle.objects.get(code="SV_MENSUAL")
    sch.generate_periods(cycle, 2026)
    first = cycle.cutoffs.order_by("cutoff_start").first()
    sch.set_cutoff_status(first, AttendanceCutoff.Status.CLOSED)
    PayCycle.objects.filter(pk=cycle.pk).update(cutoff_start_day=26)
    cycle.refresh_from_db()
    r = sch.realign_cutoffs(cycle)
    assert r["kept"] == 1 and r["created"] >= 11
    cuts = list(cycle.cutoffs.order_by("cutoff_start"))
    assert cuts[0].pk == first.pk and cuts[0].cutoff_end == first.cutoff_end  # el cerrado no se toca
    assert all((b.cutoff_start - a.cutoff_end).days == 1 for a, b in zip(cuts, cuts[1:]))
    assert cuts[2].cutoff_start.day == 26 and cuts[2].cutoff_end.day == 25  # del 26 al 25 tras la transición


# ================================================================== adjuntos de la AP
@pytest.fixture
def draft(api, hr_user, make_employee):
    emp = make_employee("SV", first_name="Adjunto", last_name="Prueba")
    api.force_login(hr_user)
    r = api.post(f"{PA}/", {"action_type": "AP_CAMBIO_ORGANIZACIONAL", "employee_code": emp.employee_code,
                            "effective_date": date.today().isoformat(), "justification": "Fase 24", "values": {"job_title": "Analista"}},
                 format="json")
    assert r.status_code == 201, r.json()
    return r.json()["action"]["folio"]


def _upload(api, folio, name, data, **extra):
    return api.post(f"{PA}/{folio}/attachments/", {"file": SimpleUploadedFile(name, data), **extra}, format="multipart")


def test_attachments_upload_validate_view_and_remove(api, hr_user, employee_user, draft, settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    api.force_login(hr_user)
    r = _upload(api, draft, "constancia.png", _png(), category="MEDICAL", description="Incapacidad")
    assert r.status_code == 201, r.json()
    body = r.json()["action"]
    assert body["attachments_current"] == 1 and body["attachments"][0]["category"] == "MEDICAL"
    assert _upload(api, draft, "carta.pdf", PDF).status_code == 201
    assert _upload(api, draft, "detalle.docx", _docx()).status_code == 201
    # Contenido falso, duplicado, extensión no permitida.
    assert _upload(api, draft, "falso.pdf", b"MZ\x90\x00 no es un pdf").json()["code"] == "invalid_content"
    assert _upload(api, draft, "falso.docx", b"PK\x03\x04roto").json()["code"] == "invalid_content"
    assert _upload(api, draft, "otra.png", _png()).json()["code"] == "duplicate"
    assert _upload(api, draft, "script.exe", b"MZ").json()["code"] == "invalid_extension"

    detail = api.get(f"{PA}/{draft}/").json()
    assert detail["can_attach"] and len(detail["attachments"]) == 3
    pdf = next(a for a in detail["attachments"] if a["kind"] == "PDF")
    res = api.get(pdf["url"])
    assert res.status_code == 200 and b"".join(res.streaming_content).startswith(b"%PDF") and res["Content-Disposition"].startswith("inline")
    doc = next(a for a in detail["attachments"] if a["kind"] == "DOCUMENT")
    assert api.get(doc["url"])["Content-Disposition"].startswith("attachment")
    # Un colaborador sin permiso de AP no los ve.
    api.force_login(employee_user)
    assert api.get(pdf["url"]).status_code in (403, 404)

    # Retirar exige motivo; queda en la lista (retirado) y en la bitácora de auditoría de la AP.
    api.force_login(hr_user)
    assert api.post(f"{PA}/attachments/{doc['id']}/remove/", {"reason": ""}, format="json").json()["code"] == "reason_required"
    r = api.post(f"{PA}/attachments/{doc['id']}/remove/", {"reason": "Archivo equivocado"}, format="json")
    assert r.status_code == 200 and r.json()["action"]["attachments_current"] == 2
    audit = [e["action"] for e in r.json()["action"]["audit"]]
    assert audit[0] == "personnel_action_created" and audit.count("personnel_action_attachment_added") == 3
    assert "personnel_action_attachment_removed" in audit

    # Una AP resuelta o anulada queda congelada (API y SQL Server).
    api.post(f"{PA}/{draft}/cancel/", {"reason": "Fase 24"}, format="json")
    r = _upload(api, draft, "tarde.png", _png((1, 2, 3)))
    assert r.status_code == 409 and r.json()["code"] == "closed"
    att = ActionAttachment.objects.filter(action__folio=draft, removed_at__isnull=True).first()
    assert api.post(f"{PA}/attachments/{att.pk}/remove/", {"reason": "x"}, format="json").status_code == 409


SQL_RULES = {
    "50110": "DELETE FROM pa.pa_action_attachment WHERE id = %(id)s",
    "50112": "UPDATE pa.pa_action_attachment SET sha256_hash = REPLICATE('0', 64) WHERE id = %(id)s",
    "50113": "UPDATE pa.pa_action_attachment SET removed_at = NULL, removed_reason = N'' WHERE id = %(id)s",  # el retiro no se revierte
    "50111": ("INSERT INTO pa.pa_action_attachment (action_id, category, description, kind, original_name, storage_path, mime_type,"
              " size_bytes, sha256_hash, status_at_upload, uploaded_at, uploaded_by_username, removed_by_username, removed_reason)"
              " VALUES (%(action)s, 'OTHER', '', 'PDF', 'x.pdf', 'x', 'application/pdf', 1, REPLICATE('1', 64), 'DRAFT', SYSDATETIME(),"
              " 'x', '', '')"),
}


@pytest.mark.parametrize("code", list(SQL_RULES))
def test_attachment_sql_rules(api, hr_user, draft, settings, tmp_path, code):
    settings.PRIVATE_MEDIA_ROOT = tmp_path
    api.force_login(hr_user)
    assert _upload(api, draft, "a.png", _png()).status_code == 201
    att = ActionAttachment.objects.get(action__folio=draft)
    with connection.cursor() as c:
        c.execute("SELECT Folio, Kind, IsCurrent FROM pa.vw_PaActionAttachment WHERE AttachmentId = %s", [att.pk])
        assert tuple(c.fetchone()) == (draft, "IMAGE", True)
    if code == "50111":
        PersonnelAction.objects.filter(folio=draft).update(status="CANCELLED")
    if code == "50113":
        assert api.post(f"{PA}/attachments/{att.pk}/remove/", {"reason": "Equivocado"}, format="json").status_code == 200
    with pytest.raises(DatabaseError) as exc, transaction.atomic(), connection.cursor() as c:
        c.execute(SQL_RULES[code].replace("%(id)s", str(att.pk)).replace("%(action)s", str(att.action_id)))
    assert code in str(exc.value)


# ================================================================== anuncios (SPA)
def test_announcements_route_is_served_by_the_spa(client):
    r = client.get("/announcements")
    assert r.status_code in (200, 302)
