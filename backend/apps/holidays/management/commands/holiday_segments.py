from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.hcm.models import Employee
from apps.holidays.services import generate_segments
from apps.personnel_actions.services import parse_date


class Command(BaseCommand):
    help = "Genera / actualiza los Holiday Segments (feriados laborados) del rango (por defecto, los últimos 31 días)."

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="date_from")
        parser.add_argument("--to", dest="date_to")

    def handle(self, *args, **options):
        today = timezone.localdate()
        hi = parse_date(options.get("date_to")) or today
        lo = parse_date(options.get("date_from")) or hi - timedelta(days=31)
        employees = Employee.objects.filter(hire_date__lte=hi).filter(Q(termination_date__isnull=True) | Q(termination_date__gte=lo))
        out = generate_segments(employees, lo, hi)
        self.stdout.write(self.style.SUCCESS(f"Holiday Segments {lo}..{hi}: {out}"))
