"""Fase 5: expediente digital dinámico (plantilla por fecha de efectividad), documentos e imágenes."""

import io
from datetime import date, timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from PIL import Image

from apps.employees.models import EmployeeTemplate
from apps.employees.schema import validate_template_schema
from apps.hcm.models import DigitalFileDocument
from apps.system.models import AuditEvent, PlatformSettings
from tests.test_employees import EMPLOYEES, sv_row

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def private_media(settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "private_media"
    return settings.PRIVATE_MEDIA_ROOT


def image_bytes(fmt="PNG", size=(120, 80), color=(20, 120, 200), exif=None) -> bytes:
    buffer = io.BytesIO()
    img = Image.new("RGB", size, color)
    kwargs = {"exif": exif} if exif is not None else {}
    img.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


def upload_doc(client, code, data: bytes, name="doc.png", **fields):
    return client.post(
        f"{EMPLOYEES}{code}/documents/",
        {"file": SimpleUploadedFile(name, data), **fields},
        format="multipart",
    )


@pytest.fixture
def hr_employee(api, hr_user):
    api.force_login(hr_user)
    r = api.post(EMPLOYEES, sv_row(tax_id="0614-010190-101-1"), format="json")
    assert r.status_code == 201, r.json()
    return api, r.json()["employee"]["employee_code"]


# --------------------------------------------------------------------- expediente dinámico
def test_dossier_follows_template_layout_and_documents(hr_employee):
    api, code = hr_employee
    r = api.get(f"{EMPLOYEES}{code}/digital-file/")
    body = r.json()
    assert r.status_code == 200 and r["Cache-Control"] == "no-store"
    assert body["basis"] == {"mode": "hire_date", "date": "2026-03-01"}
    assert body["template"]["is_hire_template"] is True
    tabs = {t["id"]: t for t in body["tabs"]}
    assert list(tabs) == ["personal", "employment", "social_security"]
    social = {s["id"]: s for s in tabs["social_security"]["sections"]}
    pension = {f["key"]: f for f in social["pension"]["fields"]}
    assert pension["pension_id"]["value"] == "123456789012" and pension["pension_id"]["label"] == "NUP (AFP)"
    assert pension["pension_id"]["recorded"]["template_effective_date"] == "2000-01-01"
    docs = {d["code"]: d for d in body["documents"]["items"]}
    assert docs["NATIONAL_ID"]["label"] == "DUI (ambas caras)" and docs["NATIONAL_ID"]["status"] == "MISSING"
    assert docs["TAX_ID"]["required"] is False  # la plantilla de SV lo vuelve opcional
    assert "PROFILE_PHOTO" not in docs
    assert body["documents"]["percent"] == 0 and body["photo"] is None
    assert body["permissions"] == {"can_upload": True, "can_view_sensitive": True, "can_manage_account": True}


def test_dossier_hides_sensitive_data_for_wfm(hr_employee, wfm_user):
    api, code = hr_employee
    api.force_login(wfm_user)
    body = api.get(f"{EMPLOYEES}{code}/digital-file/").json()
    fields = {f["key"]: f for t in body["tabs"] for s in t["sections"] for f in s["fields"]}
    assert fields["pension_id"]["restricted"] is True and fields["pension_id"]["value"] is None
    assert fields["base_salary"]["restricted"] is True and fields["base_salary"]["value"] is None
    assert fields["first_name"]["value"] == "Ana"
    assert body["permissions"]["can_upload"] is False and body["permissions"]["can_view_sensitive"] is False
    national = next(d for d in body["documents"]["items"] if d["code"] == "NATIONAL_ID")
    assert national["is_sensitive"] is True and national["viewable"] is False


def test_dossier_as_of_evaluates_the_template_effective_at_that_date(hr_employee, countries):
    api, code = hr_employee
    base = EmployeeTemplate.objects.get(country=countries["SV"])
    schema = {
        "core_fields": base.schema["core_fields"],
        "attributes": {"tax_id": {"label": "NIT"}, "dependents_count": {"required": True}},
        "layout": {"tabs": [{"id": "fiscal", "label": "Fiscal", "sections": [
            {"id": "fiscal_data", "title": "Datos fiscales", "fields": ["tax_id", "dependents_count"]}]}]},
        "documents": {"BANK_ACCOUNT": {"required": True, "label": "Certificación bancaria"}},
    }
    validate_template_schema(schema)
    EmployeeTemplate.objects.create(country=countries["SV"], name="SV 2030", effective_date=date(2030, 1, 1), schema=schema)

    body = api.get(f"{EMPLOYEES}{code}/digital-file/?as_of=2030-02-01").json()
    assert body["basis"]["mode"] == "as_of" and body["template"]["name"] == "SV 2030"
    assert body["template"]["is_hire_template"] is False
    assert body["tabs"][0]["id"] == "fiscal"
    assert {g["key"] for g in body["gaps"]} == {"dependents_count"}  # nuevo obligatorio aún sin dato
    # Los campos base no ubicados por el layout se agregan en «Otros datos» (nada se oculta).
    other = next(s for t in body["tabs"] for s in t["sections"] if s["id"] == "other_fields")
    assert "first_name" in [f["key"] for f in other["fields"]]
    # Atributos registrados con la versión anterior que la nueva no pide: pestaña «Otras versiones».
    historic = next(t for t in body["tabs"] if t["id"] == "historic")
    assert "pension_id" in [f["key"] for f in historic["sections"][0]["fields"]]
    bank = next(d for d in body["documents"]["items"] if d["code"] == "BANK_ACCOUNT")
    assert bank["required"] is True and bank["label"] == "Certificación bancaria"
    # Por defecto sigue mandando la plantilla de la fecha de ingreso.
    assert api.get(f"{EMPLOYEES}{code}/digital-file/").json()["template"]["name"] != "SV 2030"
    assert api.get(f"{EMPLOYEES}{code}/digital-file/?as_of=31-12-2030").status_code == 400


def test_template_layout_and_documents_are_validated():
    from django.core.exceptions import ValidationError

    bad = {
        "attributes": {},
        "layout": {"tabs": [{"id": "Mal ID", "label": "", "sections": [
            {"id": "a", "title": "A", "fields": ["first_name", "no_existe", "first_name"]}]}]},
        "documents": {"NO_EXISTE": {}, "PROFILE_PHOTO": {}, "NATIONAL_ID": {"required": "si", "extra": 1}},
    }
    with pytest.raises(ValidationError) as exc:
        validate_template_schema(bad)
    text = " ".join(exc.value.message_dict["schema"])
    for fragment in ["layout.tabs[0].id", "layout.tabs[0].label", "«no_existe» no es un campo", "«first_name» ya está ubicado",
                     "documents.NO_EXISTE", "fotografía de perfil", "documents.NATIONAL_ID.required", "regla desconocida «extra»"]:
        assert fragment in text, fragment


# --------------------------------------------------------------------- documentos
def test_upload_versions_hash_and_secure_download(hr_employee, wfm_user, private_media):
    api, code = hr_employee
    expiry = (timezone.localdate() + timedelta(days=400)).isoformat()
    r = upload_doc(api, code, image_bytes(), "dui frente.png", document_type="NATIONAL_ID", issue_date="2024-01-10", expiry_date=expiry)
    body = r.json()
    assert r.status_code == 201, body
    first = body["document"]
    assert first["version"] == 1 and first["mime_type"] == "image/png" and len(first["sha256"]) == 64
    assert first["width"] == 120 and first["height"] == 80 and first["original_name"] == "dui frente.png"
    assert "Se guardó «Documento de identidad» (versión 1)" in body["feedback"]
    stored = DigitalFileDocument.objects.get(pk=first["id"])
    assert (private_media / stored.storage_path).is_file() and "dui" not in stored.storage_path  # nombre aleatorio

    # Mismo archivo -> rechazado; archivo distinto -> versión 2 y la 1 queda en el historial.
    dup = upload_doc(api, code, image_bytes(), "otra.png", document_type="NATIONAL_ID", expiry_date=expiry)
    assert dup.status_code == 400 and dup.json()["code"] == "duplicate"
    r2 = upload_doc(api, code, image_bytes(color=(1, 2, 3)), "dui.png", document_type="NATIONAL_ID", expiry_date=expiry)
    assert r2.status_code == 201 and r2.json()["document"]["version"] == 2
    assert "Reemplaza a la versión anterior" in r2.json()["feedback"]
    history = api.get(f"{EMPLOYEES}{code}/documents/?type=NATIONAL_ID").json()["results"]
    assert [(d["version"], d["is_current"]) for d in history] == [(2, True), (1, False)]

    content = api.get(first["content_url"])
    assert content.status_code == 200 and content["Content-Type"] == "image/png"
    assert content["X-Content-Type-Options"] == "nosniff" and content["Cache-Control"] == "private, no-store"
    assert "inline" in content["Content-Disposition"] and b"".join(content.streaming_content).startswith(b"\x89PNG")
    assert AuditEvent.objects.filter(action="document_viewed", target_id=code).exists()
    assert AuditEvent.objects.filter(action="document_uploaded", target_id=code).count() == 2

    dossier = api.get(f"{EMPLOYEES}{code}/digital-file/").json()
    national = next(d for d in dossier["documents"]["items"] if d["code"] == "NATIONAL_ID")
    assert national["status"] == "OK" and national["versions"] == 2 and national["current"]["version"] == 2

    # WFM: documento sensible restringido (metadatos mínimos, sin contenido).
    api.force_login(wfm_user)
    assert api.get(first["content_url"]).status_code == 403
    restricted = api.get(f"{EMPLOYEES}{code}/documents/").json()["results"][0]
    assert restricted["viewable"] is False and "sha256" not in restricted and "original_name" not in restricted
    assert upload_doc(api, code, image_bytes(), document_type="RESUME").status_code == 403


@pytest.mark.parametrize(
    "name,data,fields,code",
    [
        ("cv.gif", b"GIF89a....", {}, "invalid_extension"),
        ("cv.png", b"esto no es una imagen", {}, "invalid_content"),
        ("cv.png", None, {}, "extension_mismatch"),  # JPEG con extensión .png
        ("cv.png", "truncated", {}, "corrupt"),
    ],
)
def test_upload_rejects_unsafe_or_invalid_images(hr_employee, name, data, fields, code):
    api, emp = hr_employee
    if data is None:
        data = image_bytes("JPEG")
    elif data == "truncated":
        data = image_bytes()[:60]
    r = upload_doc(api, emp, data, name, document_type="RESUME", **fields)
    assert r.status_code == 400 and r.json()["code"] == code, r.json()
    assert not DigitalFileDocument.objects.exists()


def test_upload_business_rules(hr_employee):
    api, code = hr_employee
    r = upload_doc(api, code, image_bytes(), document_type="BACKGROUND_CHECK")  # requiere vencimiento
    assert r.status_code == 400 and r.json()["errors"][0]["field"] == "expiry_date"
    r = upload_doc(api, code, image_bytes(), document_type="RESUME", issue_date="2999-01-01")
    assert r.json()["code"] == "future_issue"
    r = upload_doc(api, code, image_bytes(), document_type="NO_EXISTE")
    assert r.json()["errors"][0]["field"] == "document_type"
    PlatformSettings.objects.update_or_create(pk=1, defaults={"max_document_mb": 1})
    noise = Image.frombytes("RGB", (700, 700), bytes(range(256)) * (700 * 700 * 3 // 256) + bytes(700 * 700 * 3 % 256))
    buffer = io.BytesIO()
    noise.save(buffer, format="PNG", compress_level=0)
    r = upload_doc(api, code, buffer.getvalue(), "grande.png", document_type="RESUME")
    assert r.status_code == 400 and r.json()["code"] == "too_large"


def test_profile_photo_is_normalized_and_visible_to_wfm(hr_employee, wfm_user):
    api, code = hr_employee
    exif = Image.Exif()
    exif[0x010F] = "CamaraX"  # Make
    exif[0x0112] = 6  # Orientation: rotar 90°
    photo = image_bytes("JPEG", size=(1600, 1000), exif=exif.tobytes())
    r = api.post(f"{EMPLOYEES}{code}/photo/", {"file": SimpleUploadedFile("yo.jpeg", photo)}, format="multipart")
    assert r.status_code == 201, r.json()
    info = r.json()["photo"]
    assert (info["width"], info["height"]) == (500, 800)  # orientación aplicada y máx. 800 px
    api.force_login(wfm_user)
    img = api.get(info["url"])
    assert img.status_code == 200 and img["Content-Type"] == "image/jpeg"
    with Image.open(io.BytesIO(b"".join(img.streaming_content))) as stored:
        assert stored.size == (500, 800) and not stored.getexif()  # sin metadatos EXIF
    assert api.post(f"{EMPLOYEES}{code}/photo/", {"file": SimpleUploadedFile("x.png", image_bytes())}, format="multipart").status_code == 403
    assert api.get(f"{EMPLOYEES}{code}/digital-file/").json()["photo"]["version"] == 1


def test_digital_files_list_reports_completeness(hr_employee):
    api, code = hr_employee
    expiry = (timezone.localdate() + timedelta(days=400)).isoformat()
    upload_doc(api, code, image_bytes(), document_type="NATIONAL_ID", expiry_date=expiry)
    r = api.get("/api/v1/hcm/digital-files/?country=SV")
    row = next(e for e in r.json()["results"] if e["employee_code"] == code)
    docs = row["documents"]
    assert docs["required_total"] == 3 and docs["required_ok"] == 1  # DUI, contrato, CV
    assert "Contrato de trabajo" in docs["missing"] and row["photo_url"] is None


def test_database_rejects_non_image_mime_type(hr_employee):
    api, code = hr_employee
    upload_doc(api, code, image_bytes(), document_type="RESUME")
    with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("UPDATE hcm.DigitalFileDocument SET MimeType = N'application/pdf'")
