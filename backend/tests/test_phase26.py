"""Fase 26: datos de prueba de la demostración y archivo de accesos por rol."""

from datetime import date

import pytest
from django.contrib.auth import authenticate
from django.core.management import call_command

from apps.accounts.models import CustomUser
from apps.adherence.models import ScheduleSegment
from apps.communications.models import Announcement
from apps.hcm.models import DigitalFileDocument, Employee
from apps.operations.models import Brand, Client, LineOfBusiness, OperationalLeader, SubLineOfBusiness
from apps.personnel_actions.models import PersonnelAction
from apps.roster.models import RosterAssignment
from apps.scheduling.models import ScheduleAssignment
from apps.system.demo_data import DEMO_DOMAIN, DEMO_USER_PREFIX

pytestmark = pytest.mark.django_db(transaction=False)


@pytest.fixture
def seeded(settings, tmp_path):
    settings.PRIVATE_MEDIA_ROOT = tmp_path / "private_media"
    out = tmp_path / "accesos_prueba.txt"
    call_command("demo_data", output=str(out))
    return out


def _passwords(text: str) -> dict[str, str]:
    rows = {}
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0].startswith(DEMO_USER_PREFIX) and len(parts) >= 3:
            rows[parts[0]] = parts[1]
    return rows


def test_demo_data_builds_a_complete_operation(seeded):
    demo = Employee.objects.filter(work_email__endswith=f"@{DEMO_DOMAIN}")
    assert demo.count() == 28
    assert Client.objects.filter(code__in=["NOVA", "AURA", "VERTEX"]).count() == 3
    assert Brand.objects.count() >= 5 and LineOfBusiness.objects.count() >= 3 and SubLineOfBusiness.objects.count() >= 7
    # Cadena de mando completa y cada agente con su Team Manager en el roster
    assert OperationalLeader.objects.filter(employee__in=demo).count() == 8
    agents = demo.filter(user_account__role="EMPLOYEE")
    assert agents.count() == 16
    for emp in agents:
        codes = set(RosterAssignment.objects.current().filter(employee=emp).values_list("attribute__code", flat=True))
        assert {"client", "brand", "line_of_business", "sub_line_of_business", "team_manager", "job_title"} <= codes
        # Fase 27: ciclo de ingreso completo en el roster
        assert {"training_wave", "training_start_date", "nesting_start_date", "nesting_end_date", "operations_start_date"} <= codes
    # Fase 27: cada agente bajo SU Team Manager con la cadena completa, y General IDs por cuenta
    from apps.general_ids.models import EmployeeGeneralId
    from apps.operations.hierarchy import agent_hierarchy

    tree = agent_hierarchy(list(agents.values_list("pk", flat=True)), date.today())
    assert len(tree) == 16 and all(all(chain.values()) for chain in tree.values())
    assert len({chain["TEAM_MANAGER"]["employee_code"] for chain in tree.values()}) == 4
    gids = EmployeeGeneralId.objects.filter(employee__in=demo)
    assert gids.filter(id_type__code="PAYROLL_TOOL_ID").count() == 28
    acd = gids.filter(id_type__code="ACD_ID")
    assert acd.count() == 16 and not acd.filter(client__isnull=True).exists()
    # Primera AP de horario aprobada y horario vigente para todos
    assert PersonnelAction.objects.filter(employee__in=demo, is_initial=True, status="APPROVED").count() == 28
    assert ScheduleAssignment.objects.filter(employee__in=demo).count() == 28
    # Grilla del corte 10–24 de noviembre: breaks y almuerzo en cada día laboral de los agentes
    segs = ScheduleSegment.objects.filter(employee__in=agents, shift_date__range=(date(2026, 11, 10), date(2026, 11, 24)))
    assert segs.filter(activity__code="MEAL").count() == 16 * 11
    assert segs.filter(activity__code="BREAK").count() >= 16 * 11 * 2
    assert segs.filter(activity__code__in=["COACHING", "TRAINING", "MEETING"]).exists()
    # Expediente completo: documentos obligatorios y fotografía
    docs = DigitalFileDocument.objects.filter(digital_file__employee__in=demo, is_current=True)
    assert docs.filter(document_type__code="NATIONAL_ID").count() == 28
    assert docs.filter(document_type__code="PROFILE_PHOTO").count() == 28
    assert Announcement.objects.filter(status="PUBLISHED").count() >= 8


def test_access_file_lists_working_credentials_per_role(seeded):
    text = seeded.read_text(encoding="utf-8")
    for label in ("Recursos Humanos", "Workforce Management", "Agente Tier 1", "Supervisor de cuenta", "Team Manager"):
        assert label in text
    creds = _passwords(text)
    assert len(creds) == 28
    roles = {u.role for u in CustomUser.objects.filter(username__in=creds)}
    assert roles == {"HR", "WFM", "EMPLOYEE"}  # nunca crea administradores de prueba
    for username, password in list(creds.items())[:4]:
        user = authenticate(username=username, password=password)
        assert user is not None and not user.must_change_password


def test_demo_data_is_idempotent_and_rotates_passwords(seeded, tmp_path):
    first = _passwords(seeded.read_text(encoding="utf-8"))
    before = (Employee.objects.count(), ScheduleSegment.objects.count(), Announcement.objects.count(), CustomUser.objects.count())
    again = tmp_path / "otra.txt"
    call_command("demo_data", output=str(again))
    assert before == (Employee.objects.count(), ScheduleSegment.objects.count(), Announcement.objects.count(), CustomUser.objects.count())
    second = _passwords(again.read_text(encoding="utf-8"))
    assert first.keys() == second.keys() and all(first[k] != second[k] for k in first)


def test_dry_run_writes_nothing(settings, tmp_path):
    out = tmp_path / "accesos.txt"
    call_command("demo_data", dry_run=True, output=str(out))
    assert not out.exists()
    assert not Employee.objects.filter(work_email__endswith=f"@{DEMO_DOMAIN}").exists()
