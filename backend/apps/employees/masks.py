"""Máscaras de entrada configurables en la plantilla JSON del país (Fase 7).

Una máscara describe cómo se escribe un dato con formato fijo, para que el usuario
solo teclee los caracteres significativos y el sistema inserte guiones, espacios, etc.:

    "########-#"            DUI de El Salvador      012345678  ->  01234567-8
    "####-####"             teléfono                71234567   ->  7123-4567
    ["########-#", "####-######-###-#"]   varias longitudes (se elige la que calza)

Marcadores: ``#`` dígito, ``@`` letra, ``*`` letra o dígito. Cualquier otro carácter es
literal. El frontend aplica la misma máscara mientras se escribe (lib/mask.js); el backend
la aplica al validar (formulario y cargas masivas), de modo que «012345678» y
«01234567-8» se guardan igual. La validación final sigue siendo `pattern`.
"""

from __future__ import annotations

from typing import Any

PLACEHOLDERS = {
    "#": lambda c: "0" <= c <= "9",
    "@": lambda c: c.isalpha(),
    "*": lambda c: ("0" <= c <= "9") or c.isalpha(),
}


def capacity(mask: str) -> int:
    return sum(1 for c in mask if c in PLACEHOLDERS)


def as_masks(value: Any) -> tuple[str, ...]:
    """Normaliza la regla `mask` (texto o lista) a una tupla ordenada por capacidad."""
    if not value:
        return ()
    masks = (value,) if isinstance(value, str) else tuple(value)
    return tuple(sorted(masks, key=capacity))


def mask_error(value: Any) -> str | None:
    """Mensaje si la regla `mask` es inválida (para validar la plantilla en /admin/)."""
    masks = [value] if isinstance(value, str) else value
    if not isinstance(masks, list) or not masks:
        return 'debe ser un texto (p. ej. "####-####") o una lista de textos.'
    for mask in masks:
        if not isinstance(mask, str) or not mask.strip():
            return "cada máscara debe ser un texto no vacío."
        if capacity(mask) == 0:
            return f"«{mask}» no tiene marcadores: use # (dígito), @ (letra) o * (letra o dígito)."
        if len(mask) > 60:
            return f"«{mask}» es demasiado larga (máx. 60 caracteres)."
    if len({capacity(m) for m in masks}) != len(masks):
        return "dos máscaras de la lista tienen la misma cantidad de marcadores; no se podría elegir entre ellas."
    return None


def apply_mask(masks: tuple[str, ...], text: str) -> str:
    """Formatea `text` con la primera máscara cuyos marcadores calcen exactamente.

    Si ninguna calza (longitud o tipo de carácter distintos) devuelve el texto tal cual:
    la regla `pattern` de la plantilla reportará el problema con su ejemplo.
    """
    if not masks or not text:
        return text
    for mask in masks:
        literals = {c for c in mask if c not in PLACEHOLDERS}
        significant = [c for c in text if c not in literals and not c.isspace()]
        if len(significant) != capacity(mask):
            continue
        out, index = [], 0
        for slot in mask:
            if slot in PLACEHOLDERS:
                char = significant[index]
                index += 1
                if not PLACEHOLDERS[slot](char):
                    break
                out.append(char)
            else:
                out.append(slot)
        else:
            return "".join(out)
    return text
