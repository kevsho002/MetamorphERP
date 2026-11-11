from django.core.management.base import BaseCommand

from apps.personnel_actions.services import apply_due_actions


class Command(BaseCommand):
    help = "Aplica las acciones de personal aprobadas cuya fecha efectiva ya llegó (p. ej. ajustes salariales futuros). Ejecútelo a diario."

    def handle(self, *args, **options):
        done = apply_due_actions()
        self.stdout.write(self.style.SUCCESS(f"AP aplicadas: {len(done)}" + (f" ({', '.join(done)})" if done else "")))
