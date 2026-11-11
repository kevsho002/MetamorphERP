"""Elimina imágenes del almacenamiento privado que no tienen registro en hcm.DigitalFileDocument.

Puede quedar un archivo huérfano si la transacción del request se revierte DESPUÉS
de guardarlo (caso raro). Por seguridad solo se borran archivos con más de
--min-age-minutes de antigüedad (evita tocar cargas en curso).

    python manage.py purge_orphan_media            # informa sin borrar
    python manage.py purge_orphan_media --delete   # borra
"""

import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.hcm.models import DigitalFileDocument


class Command(BaseCommand):
    help = "Detecta (y opcionalmente elimina) imágenes huérfanas del expediente digital."

    def add_arguments(self, parser):
        parser.add_argument("--delete", action="store_true", help="Elimina los archivos huérfanos encontrados.")
        parser.add_argument("--min-age-minutes", type=int, default=60)

    def handle(self, *args, delete: bool, min_age_minutes: int, **options):
        root = Path(settings.PRIVATE_MEDIA_ROOT)
        base = root / "employees"
        if not base.is_dir():
            self.stdout.write("No hay archivos en el almacenamiento privado.")
            return
        known = {p.replace("\\", "/") for p in DigitalFileDocument.objects.values_list("storage_path", flat=True)}
        limit = time.time() - min_age_minutes * 60
        orphans = [
            path
            for path in base.rglob("*")
            if path.is_file() and path.relative_to(root).as_posix() not in known and path.stat().st_mtime < limit
        ]
        for path in orphans:
            rel = path.relative_to(root).as_posix()
            if delete:
                path.unlink()
                self.stdout.write(f"eliminado  {rel}")
            else:
                self.stdout.write(f"huérfano   {rel}")
        verb = "eliminados" if delete else "encontrados (use --delete para borrarlos)"
        self.stdout.write(self.style.SUCCESS(f"Archivos huérfanos {verb}: {len(orphans)}"))
