"""Fase 23 — Paleta de colores DUAL: global (por defecto, la fija el Administrador) y personal (cada usuario, opcional).

La paleta efectiva = la personal si el usuario eligió una; si no, la global (respaldo de fábrica: Azul corporativo).
La comparten el portal React (`src/app/appearance.js`, mismas paletas) y el Django Admin (plantilla
`admin/base_site.html` con el procesador de contexto `admin_theme`).
"""

from __future__ import annotations

import math

PALETTES = {
    "NAVY": {"label": "Azul corporativo", "primary": "#1f3a5f", "accent": "#2f7dd1"},
    "TEAL": {"label": "Verde azulado", "primary": "#0f4c5c", "accent": "#0f9b8e"},
    "WINE": {"label": "Vino", "primary": "#5b1a32", "accent": "#b23a63"},
    "GRAPHITE": {"label": "Grafito", "primary": "#25282d", "accent": "#5b7cfa"},
    "FOREST": {"label": "Bosque", "primary": "#1f4d2b", "accent": "#3a9d5d"},
}
FACTORY = "NAVY"


def _rgb(hex_color: str) -> tuple[int, int, int] | None:
    h = (hex_color or "").lstrip("#")
    if len(h) != 6:
        return None
    try:
        n = int(h, 16)
    except ValueError:
        return None
    return (n >> 16) & 255, (n >> 8) & 255, n & 255


def shade(hex_color: str, factor: float) -> str:
    """factor < 0 oscurece; > 0 aclara (hacia el blanco). Igual que `shade` de appearance.js."""
    rgb = _rgb(hex_color)
    if rgb is None:
        return hex_color

    def f(c):
        v = c * (1 + factor) if factor < 0 else c + (255 - c) * factor
        return max(0, min(255, math.floor(v + 0.5)))  # mismo redondeo que Math.round de JavaScript

    return "#" + "".join(f"{f(c):02x}" for c in rgb)


def colors(palette: str | None, accent: str | None = "") -> dict:
    if palette == "CUSTOM" and _rgb(accent or ""):
        return {"primary": shade(accent, -0.55), "accent": accent}
    p = PALETTES.get(palette or "", PALETTES[FACTORY])
    return {"primary": p["primary"], "accent": p["accent"]}


def personal(user):
    if not getattr(user, "is_authenticated", False):
        return None
    from apps.system.models import UserPreference

    return UserPreference.objects.filter(user=user).first()


def effective(user) -> dict:
    """Paleta y tema efectivos del usuario (personal sobre global)."""
    from apps.system import policy

    s = policy.current()
    pref = personal(user)
    source = "personal" if pref and pref.palette else "global"
    palette, accent = (pref.palette, pref.accent) if source == "personal" else (s.brand_palette, s.brand_accent)
    c = colors(palette, accent)
    return {
        "source": source, "palette": palette, "accent_custom": accent, **c,
        "primary_dark": shade(c["primary"], -0.35), "accent_dark": shade(c["accent"], 0.25),
        "accent_soft": shade(c["accent"], 0.85), "accent_soft_dark": shade(c["accent"], -0.6),
        "theme": pref.theme if pref else "system",
    }


def admin_theme(request):
    """Procesador de contexto: solo para /admin/ (paleta y modo del usuario en el panel de Django)."""
    if not request.path.startswith("/admin"):
        return {}
    try:
        return {"metamorph_theme": effective(request.user)}
    except Exception:  # noqa: BLE001 — sin tablas (antes de migrar) el admin usa sus colores de fábrica
        return {}
