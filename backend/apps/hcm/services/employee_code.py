"""ID corporativo de empleado: {IdPrefix}-{AAAA}-{NNNNNN}-{D}   p.ej. SV-2026-000123-7

- La GENERACIÓN ocurre en SQL Server (core.usp_GenerateEmployeeCode) para que el
  correlativo sea atómico y participe en la transacción de alta del empleado.
- Este módulo replica el dígito verificador (Luhn sobre el payload alfanumérico,
  A=10..Z=35) para VALIDAR códigos en la API sin ir a la BD. Debe mantenerse
  idéntico a core.fn_ComputeCheckDigit (lo verifica tests/test_db_integration.py).
"""

import re
import string
from dataclasses import dataclass
from datetime import date

from django.db import connections, transaction

_ALLOWED = set(string.digits + string.ascii_uppercase)
EMPLOYEE_CODE_RE = re.compile(r"^(?P<prefix>[A-Z0-9]{1,20})-(?P<year>\d{4})-(?P<seq>\d{6})-(?P<check>\d)$")


def compute_check_digit(payload: str) -> int:
    """Dígito Luhn (mod 10) sobre `payload`; las letras ASCII se expanden a 10..35."""
    digits = "".join(str(int(ch, 36)) for ch in payload.upper() if ch in _ALLOWED)
    total = 0
    for position, ch in enumerate(reversed(digits)):
        d = int(ch)
        if position % 2 == 0:  # el dígito más a la derecha del payload se duplica
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10


def format_employee_code(prefix: str, year: int, sequence: int) -> str:
    if not 1 <= sequence <= 999_999:
        raise ValueError("El correlativo debe estar entre 1 y 999999")
    if not 1900 <= year <= 9999:
        raise ValueError("Año fuera de rango")
    prefix = prefix.strip().upper()
    seq = f"{sequence:06d}"
    return f"{prefix}-{year}-{seq}-{compute_check_digit(f'{prefix}{year}{seq}')}"


def is_valid_employee_code(code: str | None) -> bool:
    match = EMPLOYEE_CODE_RE.match(code or "")
    if not match:
        return False
    payload = f"{match['prefix']}{match['year']}{match['seq']}"
    return compute_check_digit(payload) == int(match["check"])


@dataclass(frozen=True, slots=True)
class GeneratedEmployeeCode:
    code: str
    sequence_value: int
    sequence_year: int


def generate_employee_code(country_id: int, hire_date: date | None = None, using: str = "default") -> GeneratedEmployeeCode:
    """Reserva el siguiente código dentro de la transacción ACTUAL.

    Debe llamarse dentro de `transaction.atomic()` (las peticiones HTTP ya lo
    están: ATOMIC_REQUESTS). Si la transacción hace ROLLBACK, el correlativo se
    libera (sin huecos). El bloqueo por (país, año) se mantiene hasta el COMMIT.
    """
    if not transaction.get_connection(using).in_atomic_block:
        raise RuntimeError("generate_employee_code requiere una transacción activa (transaction.atomic)")
    with connections[using].cursor() as cursor:
        cursor.execute("EXEC core.usp_GenerateEmployeeCode @CountryId = %s, @HireDate = %s", [country_id, hire_date])
        code, sequence_value, sequence_year = cursor.fetchone()
    return GeneratedEmployeeCode(code=code, sequence_value=sequence_value, sequence_year=sequence_year)
