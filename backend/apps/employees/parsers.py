"""Lectura de archivos de carga masiva: CSV, Excel (.xlsx) y JSON -> lista de filas (dict).

Cada fila conserva el número con el que el usuario la ve (fila de la hoja de
cálculo, contando el encabezado como fila 1; o posición del registro en JSON).
Los problemas del archivo completo se lanzan como FileFormatError con un mensaje
en lenguaje natural; las observaciones no bloqueantes van a `notes`.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import PurePath
from typing import Any

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000


class FileFormatError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class ParsedFile:
    source_format: str  # CSV | XLSX | JSON
    file_name: str
    sha256: str
    rows: list[tuple[int, dict]]  # (número de fila visible, datos)
    notes: list[str] = field(default_factory=list)
    row_label: str = "Fila"


def detect_format(file_name: str, content_type: str | None = None) -> str:
    suffix = PurePath(file_name or "").suffix.lower()
    if suffix in {".csv", ".txt"}:
        return "CSV"
    if suffix in {".xlsx", ".xlsm"}:
        return "XLSX"
    if suffix == ".json":
        return "JSON"
    if suffix == ".xls":
        raise FileFormatError("El formato .xls (Excel 97-2003) no está soportado; guarde el archivo como .xlsx o .csv.")
    if suffix:  # extensión conocida pero no admitida: no se adivina por el content-type del navegador
        raise FileFormatError(
            f"No se reconoce el tipo de archivo «{file_name}». Formatos admitidos: CSV (.csv), Excel (.xlsx) y JSON (.json)."
        )
    ct = (content_type or "").lower()
    if "json" in ct:
        return "JSON"
    if "spreadsheetml" in ct:
        return "XLSX"
    if "csv" in ct or ct.startswith("text/"):
        return "CSV"
    raise FileFormatError(
        f"No se reconoce el tipo de archivo «{file_name}». Formatos admitidos: CSV (.csv), Excel (.xlsx) y JSON (.json)."
    )


def parse_upload(data: bytes, file_name: str, content_type: str | None = None) -> ParsedFile:
    if not data:
        raise FileFormatError("El archivo está vacío.")
    if len(data) > MAX_FILE_BYTES:
        raise FileFormatError(
            f"El archivo pesa {len(data) / 1_048_576:.1f} MB; el máximo es {MAX_FILE_BYTES // 1_048_576} MB. Divídalo en varios lotes."
        )
    fmt = detect_format(file_name, content_type)
    parsed = {"CSV": _parse_csv, "XLSX": _parse_xlsx, "JSON": _parse_json}[fmt](data)
    parsed.file_name = file_name
    parsed.sha256 = hashlib.sha256(data).hexdigest()
    _check_size(parsed)
    return parsed


def parse_records(records: Any, file_name: str = "formulario.json") -> ParsedFile:
    """Filas enviadas directamente en el cuerpo JSON de la petición."""
    payload = json.dumps(records, default=str, sort_keys=True).encode()
    parsed = _rows_from_json(records)
    parsed.file_name = file_name
    parsed.sha256 = hashlib.sha256(payload).hexdigest()
    _check_size(parsed)
    return parsed


def _check_size(parsed: ParsedFile) -> None:
    if not parsed.rows:
        raise FileFormatError("El archivo no contiene filas de datos (solo encabezado o filas vacías).")
    if len(parsed.rows) > MAX_ROWS:
        raise FileFormatError(f"El archivo tiene {len(parsed.rows)} filas; el máximo por lote es {MAX_ROWS}.")


def _clean_header(headers: list[Any], notes: list[str]) -> list[str | None]:
    result: list[str | None] = []
    seen: dict[str, int] = {}
    for position, header in enumerate(headers, start=1):
        text = str(header).strip() if header is not None else ""
        if not text:
            result.append(None)
            continue
        key = text.lower()
        if key in seen:
            raise FileFormatError(
                f"El encabezado «{text}» está repetido (columnas {seen[key]} y {position}); cada columna debe tener un nombre único."
            )
        seen[key] = position
        result.append(text)
    if not any(result):
        raise FileFormatError("La primera fila debe contener los nombres de las columnas (por ejemplo: country, first_name, ...).")
    return result


def _is_empty_row(values) -> bool:
    return all(v is None or (isinstance(v, str) and not v.strip()) for v in values)


# --------------------------------------------------------------------- CSV
def _parse_csv(data: bytes) -> ParsedFile:
    notes: list[str] = []
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
        notes.append("El archivo no está en UTF-8; se leyó como Windows-1252 (ANSI). Revise tildes y eñes en el reporte.")
    first_line = text.split("\n", 1)[0]
    delimiter = max([",", ";", "\t", "|"], key=first_line.count)
    if first_line.count(delimiter) == 0:
        delimiter = ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        header = _clean_header(next(reader), notes)
    except StopIteration:
        raise FileFormatError("El archivo CSV está vacío.") from None
    rows: list[tuple[int, dict]] = []
    try:
        for values in reader:
            line = reader.line_num
            if _is_empty_row(values):
                continue
            if len(values) > len(header):
                notes.append(f"La fila {line} tiene más valores ({len(values)}) que columnas ({len(header)}); los sobrantes se ignoraron.")
            rows.append((line, {h: v for h, v in zip(header, values) if h is not None}))
    except csv.Error as exc:
        raise FileFormatError(f"El CSV está mal formado cerca de la fila {reader.line_num}: {exc}.") from None
    if delimiter != ",":
        notes.append(f"Se detectó «{'TAB' if delimiter == chr(9) else delimiter}» como separador de columnas.")
    return ParsedFile("CSV", "", "", rows, notes)


# --------------------------------------------------------------------- Excel
def _excel_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.date() if value.time() == time(0) else value
    return value


def _parse_xlsx(data: bytes) -> ParsedFile:
    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException

    notes: list[str] = []
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (InvalidFileException, KeyError, OSError, ValueError) as exc:
        raise FileFormatError(f"No se pudo abrir el archivo Excel (¿está dañado o protegido con contraseña?): {exc}.") from None
    try:
        sheet = workbook.worksheets[0]
        if len(workbook.worksheets) > 1:
            notes.append(f"El libro tiene {len(workbook.worksheets)} hojas; solo se procesó la primera («{sheet.title}»).")
        iterator = sheet.iter_rows(values_only=True)
        header, header_row = None, 0
        for index, values in enumerate(iterator, start=1):
            if not _is_empty_row(values):
                header, header_row = _clean_header(list(values), notes), index
                break
        if header is None:
            raise FileFormatError("La primera hoja del Excel está vacía.")
        rows: list[tuple[int, dict]] = []
        for index, values in enumerate(iterator, start=header_row + 1):
            if _is_empty_row(values):
                continue
            rows.append((index, {h: _excel_value(v) for h, v in zip(header, values) if h is not None}))
            if len(rows) > MAX_ROWS:
                break
    finally:
        workbook.close()
    return ParsedFile("XLSX", "", "", rows, notes)


# --------------------------------------------------------------------- JSON
def _parse_json(data: bytes) -> ParsedFile:
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FileFormatError(f"El JSON no es válido: {exc}.") from None
    return _rows_from_json(payload)


def _rows_from_json(payload: Any) -> ParsedFile:
    records = payload.get("rows", payload.get("employees")) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise FileFormatError('El JSON debe ser una lista de empleados o un objeto {"rows": [...]}.')
    rows = []
    for index, record in enumerate(records, start=1):
        rows.append((index, record))  # un registro no-objeto lo reporta el validador
    return ParsedFile("JSON", "", "", rows, [], row_label="Registro")


def json_safe(value: Any) -> Any:
    """Convierte lo leído del archivo en algo guardable en un JSONField."""
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value
