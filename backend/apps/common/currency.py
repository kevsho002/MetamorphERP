"""Fase 22 — Monedas por país (core.catCountry.CurrencyCode): símbolo y nombre para boletas, cheques y montos en letras."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CURRENCIES = {
    "USD": {"symbol": "$", "words": "DÓLARES DE LOS ESTADOS UNIDOS DE AMÉRICA", "name": "Dólar estadounidense"},
    "GTQ": {"symbol": "Q", "words": "QUETZALES", "name": "Quetzal"},
    "MXN": {"symbol": "MX$", "words": "PESOS MEXICANOS", "name": "Peso mexicano"},
    "COP": {"symbol": "COL$", "words": "PESOS COLOMBIANOS", "name": "Peso colombiano"},
}


def symbol(code: str | None) -> str:
    return CURRENCIES.get((code or "USD").upper(), {}).get("symbol", code or "$")


def words_name(code: str | None) -> str:
    return CURRENCIES.get((code or "USD").upper(), {}).get("words", (code or "").upper())


def money(value, code: str | None = "USD") -> str:
    """1234.5, «GTQ» → «Q 1,234.50»."""
    if value in (None, ""):
        return "—"
    n = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    s = symbol(code)
    sep = " " if s[-1:].isalpha() else ""
    return f"{'-' if n < 0 else ''}{s}{sep}{abs(n):,.2f}"
