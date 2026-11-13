"""Fase 23 — Activos gráficos oficiales de la marca y su distribución contextual.

Originales (fuente de verdad) en `logos/` de la raíz del repositorio:

* `favicon_logo.png`     silueta de la mariposa: favicons, íconos de la app, avatares reducidos y el menú contraído.
* `app_header_logo.PNG`  logotipo con letras BLANCAS para fondos oscuros: barra superior del ERP y del Django Admin.
* `doc_header_logo.png`  logotipo con contraste para fondos BLANCOS: cabecera de documentos y reportes (PDF e impresos).

`python manage.py brand_assets` genera las versiones optimizadas (recortadas, redimensionadas; el logotipo de la barra
se limpia de motas semitransparentes del recorte de fondo) en:

* `frontend/public/brand/`        las sirve Vite / WhiteNoise en `/brand/…` (SPA)
* `apps/system/static/brand/`     Django Admin (`{% static 'brand/…' %}`)
* `apps/system/static/brand/doc_header_logo_pdf.png`  la que incrusta el generador de PDF
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings

REPO = Path(settings.BASE_DIR).parent
SOURCE = REPO / "logos"
STATIC_BRAND = Path(__file__).resolve().parent / "static" / "brand"
PUBLIC_BRAND = REPO / "frontend" / "public" / "brand"
PDF_LOGO = STATIC_BRAND / "doc_header_logo_pdf.png"


def _source(name: str) -> Path:
    for p in SOURCE.iterdir():
        if p.name.lower() == name.lower():
            return p
    raise FileNotFoundError(SOURCE / name)


def clean_alpha(im, threshold: int = 120):
    """Quita el «polvo» semitransparente del recorte de fondo (umbral + apertura morfológica) y recorta al contenido."""
    from PIL import ImageChops, ImageFilter

    a = im.getchannel("A")
    hi = a.getextrema()[1] or 255
    a2 = a.point(lambda v: 0 if v < threshold else min(255, int((v - threshold) * 255 / max(1, hi - threshold))))
    mask = a2.point(lambda v: 255 if v > 40 else 0).filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(7))
    im.putalpha(ImageChops.multiply(a2, mask))
    return im


def build(stdout=None) -> list[Path]:
    from PIL import Image

    def log(msg):
        if stdout:
            stdout.write(msg)

    written: list[Path] = []
    for d in (STATIC_BRAND, PUBLIC_BRAND):
        d.mkdir(parents=True, exist_ok=True)

    def save(im, name, *dirs, **kw):
        for d in dirs:
            p = d / name
            im.save(p, optimize=True, **kw)
            written.append(p)
            log(f"  {p.relative_to(REPO)} {im.size[0]}×{im.size[1]}\n")

    # Barra superior (fondo oscuro)
    app = clean_alpha(Image.open(_source("app_header_logo.png")).convert("RGBA"))
    app = app.crop(app.getchannel("A").getbbox())
    for h, name in ((96, "app_header_logo.png"), (48, "app_header_logo_sm.png")):
        small = app.resize((round(app.width * h / app.height), h), Image.LANCZOS)
        small.putalpha(small.getchannel("A").point(lambda v: 0 if v < 12 else v))  # sin halos casi invisibles del reescalado
        save(small, name, STATIC_BRAND, PUBLIC_BRAND)

    # Documentos (fondo blanco)
    doc = Image.open(_source("doc_header_logo.png")).convert("RGBA")
    doc = doc.crop(doc.getchannel("A").getbbox())
    save(doc.resize((round(doc.width * 120 / doc.height), 120), Image.LANCZOS), "doc_header_logo.png", STATIC_BRAND, PUBLIC_BRAND)
    flat = Image.new("RGB", doc.size, (255, 255, 255))
    flat.paste(doc, mask=doc.getchannel("A"))
    save(flat.resize((round(doc.width * 110 / doc.height), 110), Image.LANCZOS), PDF_LOGO.name, STATIC_BRAND)

    # Mariposa: favicons, ícono de la app y avatar reducido
    fav = Image.open(_source("favicon_logo.png")).convert("RGBA")
    fav = fav.crop(fav.getchannel("A").getbbox())
    side = max(fav.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(fav, ((side - fav.width) // 2, (side - fav.height) // 2))
    for size, name in ((32, "favicon-32.png"), (64, "favicon-64.png"), (180, "apple-touch-icon.png"), (192, "icon-192.png")):
        save(square.resize((size, size), Image.LANCZOS), name, STATIC_BRAND, PUBLIC_BRAND)
    ico = square.resize((64, 64), Image.LANCZOS)
    for d in (STATIC_BRAND, PUBLIC_BRAND):
        p = d / "favicon.ico"
        ico.save(p, sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
        written.append(p)
        log(f"  {p.relative_to(REPO)} ico\n")
    return written
