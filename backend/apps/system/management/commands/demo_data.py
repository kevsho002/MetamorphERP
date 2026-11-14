"""Fase 26 — Genera los datos de prueba de la demostración y el archivo de accesos por rol.

    python manage.py demo_data                 # genera (o completa) los datos y escribe accesos_prueba.txt
    python manage.py demo_data --dry-run       # valida todo y revierte (no escribe nada ni el archivo)
    python manage.py demo_data --output RUTA   # otra ubicación para el archivo de accesos
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.system.demo_data import DemoError, DemoSeeder, default_access_path, write_access_file


class _DryRun(Exception):
    pass


class Command(BaseCommand):
    help = "Genera datos de prueba (catálogo, colaboradores, jerarquía, horarios, grilla, comunicados) y accesos_prueba.txt."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Valida y revierte todo (no escribe el archivo de accesos).")
        parser.add_argument("--output", default="", help="Ruta del archivo de accesos (por defecto, accesos_prueba.txt en la raíz).")
        parser.add_argument("--login-url", default="http://localhost:5173/login", help="URL de ingreso que se anota en el archivo.")
        parser.add_argument("--skip-documents", action="store_true", help="No genera las imágenes del expediente.")

    def handle(self, *args, **opts):
        seeder = DemoSeeder(stdout=self.stdout)
        try:
            if opts["dry_run"]:
                try:
                    with transaction.atomic():
                        result = seeder.run(documents=False)
                        raise _DryRun
                except _DryRun:
                    pass
            else:
                result = seeder.run(documents=not opts["skip_documents"])
        except DemoError as exc:
            raise CommandError(str(exc)) from None
        for key, n in result.counts.items():
            self.stdout.write(f"  {key}: {n}")
        for note in result.notes[:20]:
            self.stdout.write(self.style.WARNING(f"  · {note}"))
        if opts["dry_run"]:
            self.stdout.write(self.style.SUCCESS("Simulación correcta: se revirtió todo (no se escribió el archivo de accesos)."))
            return
        path = write_access_file(result, Path(opts["output"]) if opts["output"] else default_access_path(), login_url=opts["login_url"])
        self.stdout.write(self.style.SUCCESS(f"Datos de prueba listos. Accesos por rol: {path}"))
