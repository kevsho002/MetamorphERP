from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError

from apps.acd.models import AgentMembership
from apps.adherence.attendance import reconcile
from apps.adherence.services import MAX_EMPLOYEES, now_local
from apps.hcm.models import Employee
from apps.scheduling.services import parse_any_date


class Command(BaseCommand):
    help = ("Fase 19: concilia la asistencia de una fecha de turno (por defecto, ayer): inserta el Lateness de quien inició sesión "
            "ACD tarde y marca Unjustified Absence (con Legal Benefit Lunch) a quien no se presentó. Idempotente; ejecútelo a diario.")

    def add_arguments(self, parser):
        parser.add_argument("--date", help="Fecha de turno AAAA-MM-DD (por defecto, ayer).")
        parser.add_argument("--group", default="", help="Código de la Management Unit (grupo ACD); vacío = todos los agentes activos.")

    def handle(self, *args, **options):
        d = parse_any_date(options["date"]) if options["date"] else now_local().date() - timedelta(days=1)
        if d is None:
            raise CommandError("Fecha inválida: use AAAA-MM-DD.")
        members = AgentMembership.objects.filter(is_active=True)
        if options["group"]:
            members = members.filter(group__code=options["group"].upper())
        employees = list(Employee.objects.filter(pk__in=members.values_list("employee_id", flat=True)).order_by("employee_code"))
        total = {"lateness": 0, "absences": 0, "on_leave": 0, "inactive": 0}
        for i in range(0, len(employees), MAX_EMPLOYEES):
            out = reconcile(employees[i:i + MAX_EMPLOYEES], d)
            for k in total:
                total[k] += out[k]
        self.stdout.write(self.style.SUCCESS(
            f"Asistencia del {d:%d/%m/%Y}: {total['lateness']} lateness y {total['absences']} ausencias nuevas "
            f"({len(employees)} agentes; {total['on_leave']} con permiso y {total['inactive']} inactivos separados)."))
