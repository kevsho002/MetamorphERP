from django.core.management.base import BaseCommand

from apps.system import brand


class Command(BaseCommand):
    help = "Fase 23: genera los logos optimizados (favicon, barra superior, cabecera de documentos) desde logos/."

    def handle(self, *args, **options):
        files = brand.build(self.stdout)
        self.stdout.write(self.style.SUCCESS(f"{len(files)} archivos de marca generados."))
