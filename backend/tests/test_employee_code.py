import pytest

from apps.hcm.services.employee_code import compute_check_digit, format_employee_code, is_valid_employee_code


def test_luhn_on_pure_digits_matches_reference():
    # Ejemplo canónico de Luhn: 7992739871 -> dígito 3
    assert compute_check_digit("7992739871") == 3


def test_letters_are_expanded_like_iban():
    # "SV" -> "2831", por lo que ambos payloads deben producir el mismo dígito
    assert compute_check_digit("SV2026000001") == compute_check_digit("28312026000001")


def test_format_matches_values_produced_by_sql_server():
    # Valores observados al ejecutar core.usp_GenerateEmployeeCode en SQL Server 2025
    assert format_employee_code("SV", 2026, 1) == "SV-2026-000001-7"
    assert format_employee_code("SV", 2026, 2) == "SV-2026-000002-5"
    assert format_employee_code("MX", 2027, 1) == "MX-2027-000001-4"


def test_prefix_is_normalized():
    assert format_employee_code(" sv ", 2026, 1) == "SV-2026-000001-7"


@pytest.mark.parametrize("code", ["SV-2026-000001-7", "MX-2027-000001-4"])
def test_valid_codes(code):
    assert is_valid_employee_code(code)


@pytest.mark.parametrize(
    "code",
    [
        "SV-2026-000001-8",  # dígito verificador incorrecto
        "GT-2026-000001-7",  # prefijo alterado
        "SV-2026-000010-7",  # transposición en el correlativo
        "SV-2026-1-7",  # correlativo sin padding
        "",
        None,
        "sv-2026-000001-7",  # minúsculas no son canónicas
    ],
)
def test_invalid_codes(code):
    assert not is_valid_employee_code(code)


@pytest.mark.parametrize("seq", [0, 1_000_000])
def test_sequence_out_of_range(seq):
    with pytest.raises(ValueError):
        format_employee_code("SV", 2026, seq)
