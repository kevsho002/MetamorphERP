"""Motor de procesamiento batch de altas de empleados + reporte en lenguaje natural.

Flujo:
1. Validación de TODAS las filas (sin escribir), con control de duplicados en el archivo.
2. Agrupación por país (locación) y escritura en una transacción (savepoint) por país:
   * atomicidad COUNTRY (por defecto): si una fila de un país falla (validación o BD),
     NO se crea ningún empleado de ese país; los demás países no se ven afectados.
   * atomicidad ROW: cada fila es independiente (savepoint por fila).
   * dry_run: se ejecuta todo (incluida la reserva del ID corporativo) y se revierte,
     para comprobar también las reglas de la base de datos sin guardar nada.
3. Registro del lote (ImportBatch) y de cada fila (ImportBatchRow) con su retroalimentación.

El mismo motor atiende el formulario individual (`process_single`).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.employees.models import ImportBatch, ImportBatchRow
from apps.employees.parsers import ParsedFile, json_safe
from apps.personnel_actions.services import ActionError, create_initial_schedule_action
from apps.employees.services import create_employee, explain_database_error
from apps.employees.validation import Message, ValidatedRow, ValidationContext, validate_employee_payload
from apps.hcm.models import Employee

ERROR_LABELS = {
    "required": "campo obligatorio faltante",
    "invalid_format": "formato inválido (documentos / identificaciones)",
    "invalid_employee_code": "ID corporativo con formato inválido",
    "employee_code_country": "ID corporativo de otro país",
    "unknown_country": "país inexistente en el catálogo",
    "inactive_country": "país inactivo",
    "country_not_effective": "país dado de baja en el catálogo",
    "no_template": "sin plantilla vigente para el país",
    "duplicate_in_file": "documento duplicado dentro del archivo",
    "duplicate_employee": "empleado ya registrado",
    "invalid_date": "fecha inválida",
    "invalid_number": "número inválido",
    "invalid_choice": "valor fuera de la lista permitida",
    "invalid_email": "correo electrónico inválido",
    "invalid_boolean": "valor Sí/No inválido",
    "too_long": "texto demasiado largo",
    "too_short": "texto demasiado corto",
    "out_of_range": "valor fuera de rango",
    "min_age": "edad menor a la mínima del país",
    "max_age": "edad mayor a la máxima del país",
    "unknown_cost_center": "centro de costos inexistente",
    "inactive_cost_center": "centro de costos inactivo",
    "cost_center_country": "centro de costos de otro país",
    "invalid_row": "registro sin estructura de campos",
    "database": "rechazo de la base de datos",
}


class _RollbackCountry(Exception):
    """Interrumpe la transacción del país (atomicidad COUNTRY)."""


@dataclass
class RowOutcome:
    row: ValidatedRow
    status: str = ImportBatchRow.Status.ERROR
    employee: Employee | None = None
    employee_code: str = ""
    preview_code: str = ""
    blocked_by: list[int] = field(default_factory=list)


# --------------------------------------------------------------------- redacción
def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " y " + items[-1]


def _numbered(messages: list[Message]) -> str:
    if len(messages) == 1:
        return messages[0].message
    return " ".join(f"({i}) {m.message}" for i, m in enumerate(messages, start=1))


def row_feedback(outcome: RowOutcome, row_label: str | None = "Fila") -> str:
    row = outcome.row
    prefix = f"{row_label} {row.row_number} ({row.country_label}): " if row_label and row.row_number is not None else ""
    name = " ".join(str(row.core.get(k)) for k in ("first_name", "last_name") if row.core.get(k))
    template = f" con la plantilla {row.spec.describe()}" if row.spec else ""
    Status = ImportBatchRow.Status
    if outcome.status == Status.CREATED:
        text = f"se creó el empleado {outcome.employee_code}{' — ' + name if name else ''}{template}."
    elif outcome.status == Status.VALID:
        code = f" (recibiría un ID como {outcome.preview_code})" if outcome.preview_code else ""
        text = f"datos válidos{template}{code}; no se guardó porque es una validación previa."
    elif outcome.status == Status.NOT_APPLIED:
        rows = _join([str(n) for n in outcome.blocked_by]) if outcome.blocked_by else "otras filas"
        one = len(outcome.blocked_by) == 1
        text = (
            f"los datos son válidos, pero no se aplicó porque la carga es «todo o nada por país» y "
            f"{'la fila' if one else 'las filas'} {rows} de {row.country_label} {'tiene' if one else 'tienen'} errores. "
            f"{'Corríjala' if one else 'Corríjalas'} y vuelva a cargar las filas de ese país."
        )
    else:
        errors = row.errors
        text = f"no se creó el empleado por {len(errors)} error{'es' if len(errors) != 1 else ''}: {_numbered(errors)}"
    warnings = row.warnings
    if warnings:
        text += f" Advertencia{'s' if len(warnings) != 1 else ''}: {_numbered(warnings)}"
    text = prefix + text
    return text[0].upper() + text[1:]


def _by_country(outcomes: list[RowOutcome], status: str) -> str:
    counts = Counter(o.row.country_label for o in outcomes if o.status == status)
    return ", ".join(f"{country}: {n}" for country, n in sorted(counts.items()))


def batch_summary(batch: ImportBatch, outcomes: list[RowOutcome], notes: list[str]) -> str:
    Status = ImportBatchRow.Status
    total = len(outcomes)
    created = sum(o.status == Status.CREATED for o in outcomes)
    valid = sum(o.status == Status.VALID for o in outcomes)
    errors = [o for o in outcomes if o.status == Status.ERROR]
    not_applied = sum(o.status == Status.NOT_APPLIED for o in outcomes)
    with_warnings = sum(bool(o.row.warnings) and o.status in (Status.CREATED, Status.VALID) for o in outcomes)

    parts = [
        f"Lote #{batch.pk} — «{batch.file_name}» ({batch.get_source_format_display()}): {total} "
        f"fila{'s' if total != 1 else ''} procesada{'s' if total != 1 else ''}, modo «{batch.get_atomicity_display().lower()}»"
        f"{', solo validación' if batch.dry_run else ''}."
    ]
    if batch.dry_run:
        parts.append(
            f"Validación previa: {valid} fila{'s' if valid != 1 else ''} válida{'s' if valid != 1 else ''}"
            f"{f' ({with_warnings} con advertencias)' if with_warnings else ''} y {len(errors)} con errores. "
            "No se guardó ningún empleado."
        )
    elif created:
        parts.append(
            f"Se crearon {created} empleado{'s' if created != 1 else ''} ({_by_country(outcomes, Status.CREATED)})"
            f"{f', {with_warnings} con advertencias' if with_warnings else ''}."
        )
    else:
        parts.append("No se creó ningún empleado.")
    if errors:
        parts.append(f"{len(errors)} fila{'s' if len(errors) != 1 else ''} con errores ({_by_country(outcomes, Status.ERROR)}).")
        codes = Counter(m.code for o in errors for m in o.row.errors)
        top = ", ".join(f"{ERROR_LABELS.get(code, code)} ({n})" for code, n in codes.most_common(5))
        parts.append(f"Errores más frecuentes: {top}.")
    if not_applied:
        parts.append(
            f"{not_applied} fila{'s' if not_applied != 1 else ''} válida{'s' if not_applied != 1 else ''} no se "
            f"{'aplicaron' if not_applied != 1 else 'aplicó'} porque su país tenía errores y la carga es atómica por país "
            f"({_by_country(outcomes, Status.NOT_APPLIED)})."
        )
    if notes:
        parts.append("Observaciones del archivo: " + " ".join(notes))
    if errors and not batch.dry_run:
        parts.append("Revise el detalle por fila, corrija los errores y vuelva a cargar solo las filas que no se crearon.")
    elif not errors and not batch.dry_run and created:
        parts.append("Cada empleado recibió su ID corporativo y su expediente digital abierto.")
    return " ".join(parts)


# --------------------------------------------------------------------- motor
def _actor_name(user) -> str:
    return getattr(user, "username", None) or "sistema"


def _write_group(outcomes: list[RowOutcome], *, atomicity: str, dry_run: bool, actor: str, user=None) -> None:
    """Escribe las filas válidas de UN país. Debe llamarse dentro de una transacción."""
    Status = ImportBatchRow.Status
    try:
        with transaction.atomic():
            for outcome in outcomes:
                try:
                    with transaction.atomic():
                        employee = create_employee(outcome.row, actor)
                        # Fase 9: ningún colaborador queda activo sin su Primera AP de asignación de horario.
                        create_initial_schedule_action(employee, outcome.row.initial_schedule, user=user)
                except ActionError as exc:
                    outcome.row.error("schedule", f"Primera AP de horario: {exc.message}", "schedule")
                    outcome.status = Status.ERROR
                    if atomicity == ImportBatch.Atomicity.COUNTRY:
                        raise _RollbackCountry from exc
                    continue
                except DatabaseError as exc:
                    outcome.row.error("database", explain_database_error(exc))
                    outcome.status = Status.ERROR
                    if atomicity == ImportBatch.Atomicity.COUNTRY:
                        raise _RollbackCountry from exc
                    continue
                if dry_run:
                    outcome.status, outcome.preview_code = Status.VALID, employee.employee_code
                else:
                    outcome.status, outcome.employee, outcome.employee_code = Status.CREATED, employee, employee.employee_code
            if dry_run:
                transaction.set_rollback(True)  # se revierte el país completo (incluidos los correlativos)
    except _RollbackCountry:
        # Se revirtió el país completo: las filas ya escritas y las aún no procesadas quedan sin aplicar.
        failed = [o.row.row_number for o in outcomes if not o.row.ok]
        for outcome in outcomes:
            if outcome.row.ok:
                outcome.status, outcome.employee, outcome.employee_code = Status.NOT_APPLIED, None, ""
                outcome.blocked_by = failed


def run_batch(
    parsed: ParsedFile,
    *,
    user=None,
    atomicity: str = ImportBatch.Atomicity.COUNTRY,
    dry_run: bool = False,
    batch: ImportBatch | None = None,
) -> ImportBatch:
    """Procesa un archivo ya leído. Requiere transacción activa (las peticiones lo están)."""
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("run_batch requiere una transacción activa (transaction.atomic)")
    Status = ImportBatchRow.Status
    started = timezone.now()
    ctx = ValidationContext()
    actor = _actor_name(user)

    outcomes = [RowOutcome(validate_employee_payload(raw, ctx, number)) for number, raw in parsed.rows]

    # Columnas desconocidas: una observación por columna en el lote (no se repite en cada fila).
    notes = list(parsed.notes)
    unknown: dict[str, int] = defaultdict(int)
    for outcome in outcomes:
        kept = []
        for message in outcome.row.messages:
            if message.code == "unknown_field":
                unknown[message.field] += 1
            else:
                kept.append(message)
        outcome.row.messages = kept
    for column, count in unknown.items():
        notes.append(
            f"La columna «{column}» no corresponde a ningún campo de la plantilla del país y se ignoró "
            f"({count} fila{'s' if count != 1 else ''})."
        )

    # Escritura por país (locación)
    groups: dict[int | None, list[RowOutcome]] = defaultdict(list)
    for outcome in outcomes:
        groups[outcome.row.country.country_id if outcome.row.country else None].append(outcome)
    for country_id, group in groups.items():
        valid = [o for o in group if o.row.ok]
        failed = [o for o in group if not o.row.ok]
        if country_id is None or not valid:
            continue
        if atomicity == ImportBatch.Atomicity.COUNTRY and failed:
            for outcome in valid:
                outcome.status = Status.NOT_APPLIED
                outcome.blocked_by = [o.row.row_number for o in failed]
            continue
        _write_group(valid, atomicity=atomicity, dry_run=dry_run, actor=actor, user=user)

    # Registro del lote
    batch = batch or ImportBatch()
    batch.source_format = parsed.source_format
    batch.file_name = parsed.file_name[:255]
    batch.file_sha256 = parsed.sha256
    batch.atomicity = atomicity
    batch.dry_run = dry_run
    batch.created_by = user if getattr(user, "pk", None) else None
    batch.total_rows = len(outcomes)
    batch.created_rows = sum(o.status == Status.CREATED for o in outcomes)
    batch.error_rows = sum(o.status == Status.ERROR for o in outcomes)
    batch.skipped_rows = sum(o.status == Status.NOT_APPLIED for o in outcomes)
    batch.warning_rows = sum(bool(o.row.warnings) for o in outcomes)
    if dry_run:
        batch.status = ImportBatch.Status.DRY_RUN
    elif batch.created_rows == batch.total_rows:
        batch.status = ImportBatch.Status.COMPLETED
    elif batch.created_rows:
        batch.status = ImportBatch.Status.PARTIAL
    else:
        batch.status = ImportBatch.Status.FAILED
    batch.notes = notes
    batch.started_at = started
    batch.finished_at = timezone.now()
    batch.save()  # obtiene pk para el resumen
    batch.summary = batch_summary(batch, outcomes, notes)
    batch.save(update_fields=["summary"])

    ImportBatchRow.objects.bulk_create(
        [
            ImportBatchRow(
                batch=batch,
                row_number=o.row.row_number,
                status=o.status,
                country=o.row.country,
                template=o.row.template,
                employee=o.employee,
                employee_code=o.employee_code,
                errors=[m.as_dict() for m in o.row.errors],
                warnings=[m.as_dict() for m in o.row.warnings],
                feedback=row_feedback(o, parsed.row_label),
                raw_data=json_safe(o.row.raw) if isinstance(o.row.raw, dict) else {"valor": json_safe(o.row.raw)},
            )
            for o in outcomes
        ],
        batch_size=200,
    )
    return batch


def process_single(payload: dict, *, user=None, dry_run: bool = False, extra_checks=None) -> RowOutcome:
    """Formulario individual: mismas reglas que el batch, transacción propia (savepoint).

    `extra_checks(row)` agrega validaciones del flujo (p. ej. la cuenta de usuario vinculada)
    ANTES de escribir: si agrega errores, no se crea nada.
    """
    ctx = ValidationContext()
    outcome = RowOutcome(validate_employee_payload(payload, ctx))
    if extra_checks is not None:
        extra_checks(outcome.row)
    if outcome.row.ok:
        _write_group([outcome], atomicity=ImportBatch.Atomicity.ROW, dry_run=dry_run, actor=_actor_name(user), user=user)
    return outcome

