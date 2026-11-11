"""Fase 14: avatar de la barra superior (foto propia sin hcm.view) y datos que usa el menú de estados."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from tests.test_digital_file import image_bytes, private_media  # noqa: F401  (fixture autouse reexportada)
from tests.test_employees import EMPLOYEES

pytestmark = pytest.mark.django_db

ME = "/api/v1/auth/me/"
MY_PHOTO = "/api/v1/auth/me/photo/"


def test_me_without_photo_or_employee(api, admin_user, employee_user):
    api.force_login(admin_user)
    assert api.get(ME).json()["photo_url"] is None
    assert api.get(MY_PHOTO).status_code == 404
    api.force_login(employee_user)
    assert api.get(ME).json()["photo_url"] is None
    assert api.get(MY_PHOTO).status_code == 404


def test_employee_sees_own_photo_without_hcm_view(api, hr_user, employee_user):
    code = employee_user.employee.employee_code
    api.force_login(hr_user)
    r = api.post(f"{EMPLOYEES}{code}/photo/", {"file": SimpleUploadedFile("yo.png", image_bytes())}, format="multipart")
    assert r.status_code == 201, r.json()

    api.force_login(employee_user)
    url = api.get(ME).json()["photo_url"]
    assert url and url.startswith(MY_PHOTO + "?v=")
    img = api.get(url)
    assert img.status_code == 200 and img["Content-Type"].startswith("image/")
    assert img["X-Content-Type-Options"] == "nosniff"
    # La foto de otros sigue exigiendo hcm.view.
    assert api.get(f"{EMPLOYEES}{code}/photo/").status_code == 403


def test_my_photo_requires_login(api):
    assert api.get(MY_PHOTO).status_code in (401, 403)
