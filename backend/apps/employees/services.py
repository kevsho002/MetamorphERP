"""Escritura del alta: hcm.Employee + expediente digital + valores EAV, en una transacción.

`create_employee` asume una fila YA validada (validation.ValidatedRow sin errores)
y debe ejecutarse dentro de transaction.atomic(): el ID corporativo se reserva con
core.usp_GenerateEmployeeCode y vuelve al correlativo si la transacción se revierte.
"""

from __future__ import annotations

import logging

from django.db import DatabaseError, IntegrityError, transaction

from apps.employees.models import EmployeeAttributeValue
from apps.employees.validation import ValidatedRow
from apps.hcm.models import DigitalFile, Employee
from apps.hcm.services.employee_code import generate_employee_code

audit = logging.getLogger("apps.employees.audit")

_CORE_MODEL_FIELDS = (
    "first_name", "middle_name", "last_name", "second_last_name", "national_id_type", "national_id_number",
    "birth_date", "gender", "work_email", "personal_email", "phone_number", "hire_date", "base_salary", "pay_frequency",
)


def create_employee(row: ValidatedRow, actor: str) -> Employee:
    if not row.ok or row.country is None or row.template is None:
        raise ValueError("create_employee requiere una fila validada sin errores")
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("create_employee requiere una transacción activa (transaction.atomic)")

    code = generate_employee_code(row.country.country_id, row.core["hire_date"]).code
    values = {k: row.core[k] for k in _CORE_MODEL_FIELDS if row.core.get(k) not in (None, "")}
    employee = Employee.objects.create(
        employee_code=code, country=row.country, cost_center=row.cost_center, created_by=actor[:100], **values
    )
    DigitalFile.objects.create(employee=employee, created_by=actor[:100])  # expediente digital 1:1
    EmployeeAttributeValue.objects.bulk_create(
        [
            EmployeeAttributeValue(
                employee=employee, attribute=spec.attribute, value=canonical, template=row.template, updated_by=actor[:150]
            )
            for spec, canonical in row.attributes
        ]
    )
    audit.info("employee_created code=%s country=%s template=%s by=%s", code, row.country.country_code, row.template.pk, actor)
    return employee


# Restricciones de BD -> explicación para el usuario (por si algo escapa a la validación previa).
_CONSTRAINT_MESSAGES = {
    "UQ_Employee_NationalId": "Ya existe un empleado con ese documento de identidad en el país.",
    "UQ_Employee_EmployeeCode": "El ID corporativo generado ya existe (conflicto de concurrencia); vuelva a intentar.",
    "FK_Employee_CostCenter_Country": "El centro de costos no pertenece al país del empleado.",
    "CK_Employee_Gender": "El género debe ser M, F o X.",
    "CK_Employee_BaseSalary": "El salario base no puede ser negativo.",
    "CK_Employee_EmployeeCode_Format": "El ID corporativo generado no cumple el formato.",
    "uq_employee_attribute_value": "Un atributo dinámico está repetido para el empleado.",
}


def explain_database_error(exc: DatabaseError) -> str:
    text = str(exc)
    for constraint, message in _CONSTRAINT_MESSAGES.items():
        if constraint in text:
            return f"{message} (restricción {constraint})"
    if "50001" in text or "secuencia" in text.lower():
        return "No se pudo generar el ID corporativo: se agotó el correlativo del país para ese año o el país no es válido."
    kind = "integridad" if isinstance(exc, IntegrityError) else "base de datos"
    return f"La base de datos rechazó el registro por una regla de {kind}: {text.splitlines()[0][:300]}"

