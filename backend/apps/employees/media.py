"""Validación segura de imágenes del expediente (PNG / JPG / JPEG).

Defensa en profundidad:
1. Extensión permitida (.png, .jpg, .jpeg) y tamaño máximo (parámetro del admin).
2. Firma binaria ("magic bytes"): el contenido debe ser realmente PNG o JPEG,
   y coincidir con la extensión (un .png que es JPEG se rechaza).
3. Decodificación completa con Pillow: detecta archivos truncados/corruptos y
   "bombas" de descompresión (límite de píxeles).
4. La BD vuelve a exigir MimeType IN ('image/png','image/jpeg') (script 095).

La fotografía de perfil se re-codifica (JPEG, orientación corregida, máx. 800 px):
así se eliminan metadatos EXIF/GPS. Los documentos oficiales se guardan con sus
bytes ORIGINALES (su SHA-256 prueba la integridad del respaldo).
"""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass
from pathlib import PurePath

from django.conf import settings
from PIL import Image, ImageOps, UnidentifiedImageError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"
ALLOWED = {
    ".png": ("PNG", "image/png"),
    ".jpg": ("JPEG", "image/jpeg"),
    ".jpeg": ("JPEG", "image/jpeg"),
}
EXTENSION_FOR_MIME = {"image/png": ".png", "image/jpeg": ".jpg"}


class ImageRejected(Exception):
    def __init__(self, message: str, code: str = "invalid_image"):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class InspectedImage:
    data: bytes
    mime_type: str
    extension: str
    width: int
    height: int
    original_name: str


def _sniff(data: bytes) -> str | None:
    if data.startswith(PNG_SIGNATURE):
        return "PNG"
    if data.startswith(JPEG_SIGNATURE):
        return "JPEG"
    return None


def _safe_name(name: str) -> str:
    """Solo el nombre (sin rutas) y sin caracteres de control; se guarda como metadato, nunca como ruta."""
    base = PurePath(name.replace("\\", "/")).name or "imagen"
    return "".join(ch for ch in base if ch.isprintable())[:255] or "imagen"


def inspect_image(upload, *, max_bytes: int) -> InspectedImage:
    name = _safe_name(getattr(upload, "name", "") or "")
    extension = PurePath(name).suffix.lower()
    if extension not in ALLOWED:
        raise ImageRejected(
            f"«{name}» no es un formato permitido. Use imágenes PNG, JPG o JPEG.", "invalid_extension"
        )
    size = getattr(upload, "size", None)
    if size is not None and size > max_bytes:
        raise ImageRejected(
            f"La imagen pesa {size / 1_048_576:.1f} MB; el máximo es {max_bytes // 1_048_576} MB.", "too_large"
        )
    data = upload.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ImageRejected(f"La imagen supera el máximo de {max_bytes // 1_048_576} MB.", "too_large")
    if not data:
        raise ImageRejected("El archivo está vacío.", "empty")

    expected_format, mime_type = ALLOWED[extension]
    sniffed = _sniff(data)
    if sniffed is None:
        raise ImageRejected(
            f"El contenido de «{name}» no es una imagen PNG ni JPEG (aunque la extensión lo indique).", "invalid_content"
        )
    if sniffed != expected_format:
        raise ImageRejected(
            f"«{name}» tiene extensión {extension} pero su contenido es {sniffed}. Renómbrelo con la extensión correcta.",
            "extension_mismatch",
        )

    max_pixels = settings.DOCUMENT_MAX_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as probe:
                width, height = probe.size
                if width * height > max_pixels:
                    raise ImageRejected(
                        f"La imagen mide {width}×{height} px; el máximo es {max_pixels // 1_000_000} megapíxeles.",
                        "too_many_pixels",
                    )
                probe.verify()  # estructura interna (CRC de PNG, marcadores JPEG)
            with Image.open(io.BytesIO(data)) as full:
                full.load()  # decodificación completa: detecta archivos truncados
    except ImageRejected:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageRejected("La imagen es demasiado grande para procesarla de forma segura.", "too_many_pixels") from None
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ImageRejected(f"La imagen «{name}» está dañada o incompleta ({exc.__class__.__name__}).", "corrupt") from None

    return InspectedImage(
        data=data, mime_type=mime_type, extension=EXTENSION_FOR_MIME[mime_type], width=width, height=height,
        original_name=name,
    )


def normalize_profile_photo(image: InspectedImage) -> InspectedImage:
    """Foto de perfil: orientación EXIF aplicada, RGB, máx. PROFILE_PHOTO_MAX_SIDE px, JPEG sin metadatos."""
    side = settings.PROFILE_PHOTO_MAX_SIDE
    with Image.open(io.BytesIO(image.data)) as src:
        img = ImageOps.exif_transpose(src)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.getchannel("A"))
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail((side, side), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=88, optimize=True)  # sin exif= -> sin metadatos
        width, height = img.size
    stem = PurePath(image.original_name).stem or "foto"
    return InspectedImage(
        data=out.getvalue(), mime_type="image/jpeg", extension=".jpg", width=width, height=height,
        original_name=f"{stem}.jpg",
    )
