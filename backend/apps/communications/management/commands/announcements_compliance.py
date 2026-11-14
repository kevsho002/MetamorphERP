"""Reporte automático de cumplimiento del acuse de recibo (programar a diario, p. ej. 06:00).

    python manage.py announcements_compliance [--date AAAA-MM-DD]
"""

from datetime import date

from django.core.management.base import BaseCommand

from apps.communications.services import run_daily


class Command(BaseCommand):
    help = "Fotos diarias y de vencimiento del cumplimiento de los comunicados con acuse de recibo obligatorio."

    def add_arguments(self, parser):
        parser.add_argument("--date", type=date.fromisoformat, default=None)

    def handle(self, *args, date=None, **options):
        out = run_daily(date)
        for row in out:
            self.stdout.write(f"{row['trigger']:<8} #{row['announcement']} {row['title'][:60]} · {row['compliance_pct']} % · "
                              f"{row['pending']} pendiente(s)")
        self.stdout.write(self.style.SUCCESS(f"{len(out)} foto(s) de cumplimiento."))
