"""Validación de UNA fila/formulario de alta de empleado contra la plantilla de su país.

La usan el formulario individual (API) y el motor batch: mismas reglas, mismos
mensajes. Cada problema es un `Message` (nivel, código, campo, texto en español
listo para mostrarse al usuario). Nada aquí escribe en la base de datos.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.utils import timezone

from apps.common.models import CostCenter, Country
from apps.employees.models import EmployeeTemplate
from apps.employees.schema import (
    CORE_FIELDS,
    FieldSpec,
    FieldValueError,
    TemplateSpec,
    coerce_value,
    format_pattern_error,
    is_blank,
    parse_date,
    resolve_template,
)
from apps.hcm.models import Employee
from apps.hcm.services.employee_code import EMPLOYEE_CODE_RE, is_valid_employee_code

ERROR = "error"
WARNING = "warning"
DEFAULT_MAX_FUTURE_HIRE_DAYS = 90

# Encabezados aceptados (se normalizan: minúsculas, sin tildes, espacios -> "_").
KEY_ALIASES = {
    "pais": "country", "country_code": "country", "codigo_pais": "country", "cod_pais": "country",
    "primer_nombre": "first_name", "nombre": "first_name", "nombres": "first_name",
    "segundo_nombre": "middle_name",
    "primer_apellido": "last_name", "apellido": "last_name", "apellidos": "last_name",
    "segundo_apellido": "second_last_name",
    "tipo_documento": "national_id_type", "tipo_de_documento": "national_id_type", "tipo_identificacion": "national_id_type",
    "numero_documento": "national_id_number", "numero_de_documento": "national_id_number", "documento": "national_id_number",
    "documento_identidad": "national_id_number", "numero_identificacion": "national_id_number",
    "fecha_nacimiento": "birth_date", "fecha_de_nacimiento": "birth_date",
    "genero": "gender", "sexo": "gender",
    "correo_laboral": "work_email", "email_laboral": "work_email", "email": "work_email", "correo": "work_email",
    "correo_personal": "personal_email", "email_personal": "personal_email",
    "telefono": "phone_number", "celular": "phone_number",
    "fecha_ingreso": "hire_date", "fecha_de_ingreso": "hire_date", "fecha_contratacion": "hire_date",
    "salario_base": "base_salary", "salario": "base_salary", "sueldo": "base_salary",
    "frecuencia_pago": "pay_frequency", "frecuencia_de_pago": "pay_frequency",
    "centro_costos": "cost_center", "centro_de_costos": "cost_center", "cost_center_code": "cost_center",
    "id_corporativo": "employee_code", "codigo_empleado": "employee_code", "codigo_de_empleado": "employee_code",
}
SPECIAL_KEYS = {"country", "employee_code"}
_ATTR_PREFIXES = ("attr_", "atributo_", "attributes_", "attributes.")


def normalize_key(key: Any) -> str:
    text = unicodedata.normalize("NFKD", str(key)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


@dataclass
class Message:
    level: str
    code: str
    message: str
    field: str | None = None

    def as_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "field": self.field, "message": self.message}


@dataclass
class ValidatedRow:
    row_number: int | None
    raw: dict
    country: Country | None = None
    template: EmployeeTemplate | None = None
    spec: TemplateSpec | None = None
    core: dict[str, Any] = field(default_factory=dict)
    attributes: list[tuple[FieldSpec, str]] = field(default_factory=list)
    cost_center: CostCenter | None = None
    messages: list[Message] = field(default_factory=list)

    @property
    def errors(self) -> list[Message]:
        return [m for m in self.messages if m.level == ERROR]

    @property
    def warnings(self) -> list[Message]:
        return [m for m in self.messages if m.level == WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def country_label(self) -> str:
        return self.country.country_name if self.country else "país no identificado"

    def has_field_error(self, field_name: str) -> bool:
        return any(m.field == field_name for m in self.errors)

    def error(self, code: str, message: str, field_name: str | None = None) -> None:
        self.messages.append(Message(ERROR, code, message, field_name))

    def warn(self, code: str, message: str, field_name: str | None = None) -> None:
        self.messages.append(Message(WARNING, code, message, field_name))


class ValidationContext:
    """Caché por lote (catálogos) + control de duplicados dentro del mismo archivo."""

    def __init__(self):
        self.today = timezone.localdate()
        self._countries = list(Country.objects.all())
        self._country_index: dict[str, Country] = {}
        for c in self._countries:
            for key in (c.country_code, c.country_name, str(c.country_id), c.id_prefix):
                self._country_index[normalize_key(key)] = c
        self._template_cache: dict[tuple[int, date], EmployeeTemplate | None] = {}
        self._spec_cache: dict[int, TemplateSpec] = {}
        self._cost_centers = {cc.code.upper(): cc for cc in CostCenter.objects.select_related("country")}
        self.seen_national_ids: dict[tuple, int | None] = {}
        self.seen_emails: dict[str, int | None] = {}
        self._base_spec: dict[str, FieldSpec] | None = None

    @property
    def valid_country_codes(self) -> str:
        return ", ".join(c.country_code for c in self._countries if c.is_active)

    def country(self, value: Any) -> Country | None:
        return self._country_index.get(normalize_key(value))

    def template_for(self, country: Country, on_date: date) -> EmployeeTemplate | None:
        key = (country.country_id, on_date)
        if key not in self._template_cache:
            template = EmployeeTemplate.objects.select_related("country").effective_for(country, on_date)
            self._template_cache[key] = template
        return self._template_cache[key]

    def spec_for(self, template: EmployeeTemplate) -> TemplateSpec:
        if template.pk not in self._spec_cache:
            self._spec_cache[template.pk] = resolve_template(template)
        return self._spec_cache[template.pk]

    def cost_center(self, code: str) -> CostCenter | None:
        return self._cost_centers.get(code.upper())

    def base_spec(self) -> dict[str, FieldSpec]:
        """Campos base sin reglas de país (para seguir validando si no hay plantilla)."""
        if self._base_spec is None:
            self._base_spec = {
                k: FieldSpec(key=k, label=b.label, kind="core", data_type=b.data_type, required=b.required,
                             max_length=b.max_length, choices=b.choices, default=b.default)
                for k, b in CORE_FIELDS.items()
            }
        return self._base_spec


# --------------------------------------------------------------------- lectura de claves
def _split_payload(raw: dict) -> tuple[dict[str, Any], dict[str, tuple[str, Any]]]:
    """Separa campos base/especiales (por alias) de candidatos a atributo dinámico."""
    known: dict[str, Any] = {}
    others: dict[str, tuple[str, Any]] = {}
    for original_key, value in raw.items():
        if original_key is None or (isinstance(original_key, str) and not original_key.strip()):
            continue
        if isinstance(value, dict) and normalize_key(original_key) in {"attributes", "atributos"}:
            for k, v in value.items():
                others[normalize_key(k)] = (f"attributes.{k}", v)
            continue
        nk = normalize_key(original_key)
        mapped = KEY_ALIASES.get(nk, nk)
        if mapped in CORE_FIELDS or mapped in SPECIAL_KEYS:
            if mapped not in known or is_blank(known[mapped]):
                known[mapped] = value
            continue
        for prefix in _ATTR_PREFIXES:
            if nk.startswith(prefix.replace(".", "_")):
                nk = nk[len(prefix):]
                break
        others[nk] = (str(original_key), value)
    return known, others


def _label(country: Country | None) -> str:
    return country.country_name if country else "el país"


# --------------------------------------------------------------------- validación principal
def validate_employee_payload(
    raw: dict, ctx: ValidationContext, row_number: int | None = None, existing: Employee | None = None
) -> ValidatedRow:
    """Valida un alta (existing=None) o la edición de `existing` (payload ya combinado con sus datos actuales)."""
    row = ValidatedRow(row_number=row_number, raw=raw)
    if not isinstance(raw, dict):
        row.error("invalid_row", "El registro no es un objeto con campos (clave: valor).")
        return row
    known, others = _split_payload(raw)

    # 1. País (core.catCountry)
    country_raw = known.get("country")
    if is_blank(country_raw):
        row.error(
            "required", f"Falta el país (columna «country» o «pais»). Valores válidos: {ctx.valid_country_codes}.", "country"
        )
    else:
        row.country = ctx.country(country_raw)
        if row.country is None:
            row.error(
                "unknown_country",
                f"El país «{country_raw}» no existe en el catálogo de países (core.catCountry). "
                f"Valores válidos: {ctx.valid_country_codes}.",
                "country",
            )

    # 2. Fecha de ingreso: decide la plantilla vigente
    hire_date = None
    if is_blank(known.get("hire_date")):
        row.error("required", "Falta la «Fecha de ingreso»: es obligatoria para elegir la plantilla vigente del país.", "hire_date")
    else:
        try:
            hire_date = parse_date(known["hire_date"])
        except FieldValueError as exc:
            row.error(exc.code, f"«Fecha de ingreso»: {exc.message}", "hire_date")

    # 3. País vigente + plantilla por fecha de efectividad
    if row.country and hire_date:
        c = row.country
        if not c.is_active:
            row.error("inactive_country", f"El país {c.country_name} está inactivo en el catálogo; no admite altas.", "country")
        elif hire_date < c.effective_start_date or (c.effective_end_date and hire_date > c.effective_end_date):
            row.error(
                "country_not_effective",
                f"{c.country_name} no está vigente en el catálogo a la fecha de ingreso {hire_date:%d/%m/%Y}.",
                "country",
            )
        row.template = ctx.template_for(c, hire_date)
        if row.template is None:
            row.error(
                "no_template",
                f"No existe una plantilla activa de {c.country_name} vigente al {hire_date:%d/%m/%Y} (fecha de ingreso). "
                "Un administrador debe crearla en /admin/ › Plantillas de empleado por país.",
                "country",
            )
        else:
            row.spec = ctx.spec_for(row.template)

    # Sin plantilla (país o fecha inválidos) se validan igual los campos base para reportar todo de una vez.
    fields = row.spec.fields if row.spec else ctx.base_spec()
    if hire_date:
        row.core["hire_date"] = hire_date
    template_desc = f" exigido por la plantilla {row.spec.describe()} de {row.country.country_name}" if row.spec else ""

    # 4. Campos (base + atributos dinámicos del país)
    consumed: set[str] = set()
    label_index = {}
    if row.spec:
        for spec in row.spec.attributes.values():
            label_index[normalize_key(spec.label)] = spec.key
    for key, spec in fields.items():
        if key == "hire_date":
            continue  # ya validada en el paso 2
        if spec.kind == "core":
            raw_value = known.get(key)
        else:
            candidates = [key] + [lbl for lbl, code in label_index.items() if code == key]
            raw_value, source = None, None
            for cand in candidates:
                if cand in others and not is_blank(others[cand][1]):
                    source = cand
                    raw_value = others[cand][1]
                    break
                if cand in others:
                    consumed.add(cand)
            if source:
                consumed.add(source)
        if is_blank(raw_value):
            if spec.default is not None:
                raw_value = spec.default
            elif spec.required:
                row.error("required", f"Falta el campo obligatorio «{spec.label}»{template_desc}.", key)
                continue
            else:
                if spec.recommended:
                    row.warn(
                        "recommended_missing",
                        f"No se indicó «{spec.label}», recomendado para {_label(row.country)}; puede completarse después.",
                        key,
                    )
                continue
        try:
            value, canonical = coerce_value(spec, raw_value)
        except FieldValueError as exc:
            row.error(exc.code, exc.message, key)
            continue
        if spec.kind == "core":
            row.core[key] = value
        else:
            row.attributes.append((spec, canonical))

    # Campos no reconocidos
    if row.spec:
        for nk, (original, value) in others.items():
            if nk not in consumed and not is_blank(value):
                row.warn(
                    "unknown_field",
                    f"La columna «{original}» no corresponde a ningún campo de la plantilla de {row.country.country_name}; se ignoró.",
                    original,
                )

    _check_national_id(row, fields, ctx)
    if existing is None:
        _check_employee_code(row, known.get("employee_code"))
    _check_dates_and_salary(row, ctx)
    _check_cost_center(row, ctx)
    _check_duplicates(row, ctx, existing)
    return row


def _check_national_id(row: ValidatedRow, fields: dict[str, FieldSpec], ctx: ValidationContext) -> None:
    id_type, number = row.core.get("national_id_type"), row.core.get("national_id_number")
    if not id_type or not number:
        return
    id_type = id_type.upper()
    row.core["national_id_type"] = id_type
    spec = fields["national_id_number"]
    rule = spec.patterns_by_type.get(id_type)
    if rule and not re.fullmatch(rule["pattern"], number):
        row.error(
            "invalid_format",
            format_pattern_error(f"{spec.label} ({id_type})", number, rule.get("example"), rule.get("message")),
            "national_id_number",
        )


def _check_employee_code(row: ValidatedRow, value: Any) -> None:
    """El ID corporativo lo GENERA el sistema; si el archivo trae uno, se valida y se explica."""
    if is_blank(value):
        return
    code = str(value).strip().upper()
    match = EMPLOYEE_CODE_RE.match(code)
    if not match:
        row.error(
            "invalid_employee_code",
            f"El ID corporativo «{code}» no tiene el formato {{PAÍS}}-AAAA-NNNNNN-D (ejemplo: SV-2026-000123-7). "
            "Para altas nuevas deje la columna vacía: el sistema lo genera.",
            "employee_code",
        )
        return
    if not is_valid_employee_code(code):
        row.error(
            "invalid_employee_code",
            f"El ID corporativo «{code}» tiene un dígito verificador incorrecto (posible error de digitación).",
            "employee_code",
        )
        return
    if row.country and match["prefix"] != row.country.id_prefix.upper():
        row.error(
            "employee_code_country",
            f"El ID corporativo «{code}» corresponde al prefijo {match['prefix']}, no a {row.country.country_name} "
            f"({row.country.id_prefix}).",
            "employee_code",
        )
        return
    existing = Employee.objects.filter(employee_code=code).first()
    if existing:
        row.error(
            "duplicate_employee",
            f"El empleado {code} ({existing.full_name}) ya existe; esta carga solo crea empleados nuevos.",
            "employee_code",
        )
        return
    row.warn(
        "employee_code_ignored",
        f"Se ignoró el ID corporativo «{code}»: el sistema asigna el siguiente correlativo del país al crear el empleado.",
        "employee_code",
    )


def _check_dates_and_salary(row: ValidatedRow, ctx: ValidationContext) -> None:
    rules = row.spec.rules if row.spec else {}
    birth, hire = row.core.get("birth_date"), row.core.get("hire_date")
    if birth and birth > ctx.today:
        row.error("invalid_date", f"La fecha de nacimiento {birth:%d/%m/%Y} está en el futuro.", "birth_date")
    elif birth and hire:
        age = hire.year - birth.year - ((hire.month, hire.day) < (birth.month, birth.day))
        if age < 0:
            row.error("invalid_date", "La fecha de ingreso es anterior a la fecha de nacimiento.", "hire_date")
        elif "min_age" in rules and age < rules["min_age"]:
            row.error(
                "min_age",
                f"A la fecha de ingreso la persona tendría {age} años; {row.country_label} exige al menos {rules['min_age']}.",
                "birth_date",
            )
        elif "max_age" in rules and age > rules["max_age"]:
            row.error(
                "max_age",
                f"A la fecha de ingreso la persona tendría {age} años; el máximo configurado para {row.country_label} es {rules['max_age']}.",
                "birth_date",
            )
    if hire:
        limit = rules.get("max_future_hire_days", DEFAULT_MAX_FUTURE_HIRE_DAYS)
        if hire > ctx.today + timedelta(days=limit):
            row.warn(
                "future_hire_date",
                f"La fecha de ingreso {hire:%d/%m/%Y} está a más de {limit} días en el futuro; verifique que sea correcta.",
                "hire_date",
            )

    salary = row.core.get("base_salary")
    if salary is not None:
        currency = row.country.currency_code if row.country else ""
        if salary < 0:
            row.error("out_of_range", f"El salario base no puede ser negativo ({salary}).", "base_salary")
            return
        rounded = salary.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if rounded != salary:
            row.warn("rounded", f"El salario base {salary} se redondeó a {rounded} (2 decimales).", "base_salary")
        if rounded >= Decimal("1e16"):
            row.error("out_of_range", f"El salario base {salary} excede el máximo admitido.", "base_salary")
            return
        row.core["base_salary"] = rounded
        if "min_base_salary" in rules and rounded < rules["min_base_salary"]:
            row.warn(
                "below_min_salary",
                f"El salario base {rounded} {currency} es menor que el mínimo de referencia de {row.country_label} "
                f"({rules['min_base_salary']} {currency}); confirme si es jornada parcial.",
                "base_salary",
            )
        if "max_base_salary" in rules and rounded > rules["max_base_salary"]:
            row.warn(
                "above_max_salary",
                f"El salario base {rounded} {currency} supera el umbral de revisión de {row.country_label} "
                f"({rules['max_base_salary']} {currency}).",
                "base_salary",
            )


def _check_cost_center(row: ValidatedRow, ctx: ValidationContext) -> None:
    code = row.core.pop("cost_center", None)
    if not code:
        return
    cc = ctx.cost_center(code)
    if cc is None:
        row.error("unknown_cost_center", f"El centro de costos «{code}» no existe en el catálogo.", "cost_center")
    elif not cc.is_active:
        row.error("inactive_cost_center", f"El centro de costos {cc.code} está inactivo.", "cost_center")
    elif row.country and cc.country_id != row.country.country_id:
        row.error(
            "cost_center_country",
            f"El centro de costos {cc.code} pertenece a {cc.country.country_name}, no a {row.country.country_name}: "
            "cada empleado debe usar un centro de costos de su propio país.",
            "cost_center",
        )
    else:
        row.cost_center = cc


def _row_ref(row_number: int | None) -> str:
    return f"la fila {row_number}" if row_number is not None else "otro registro de esta carga"


def _check_duplicates(row: ValidatedRow, ctx: ValidationContext, existing: Employee | None = None) -> None:
    others = Employee.objects.exclude(pk=existing.pk) if existing else Employee.objects
    id_type, number = row.core.get("national_id_type"), row.core.get("national_id_number")
    if row.country and id_type and number:
        key = (row.country.country_id, id_type, number.upper())
        label = f"{id_type} {number}"
        if key in ctx.seen_national_ids:
            row.error(
                "duplicate_in_file",
                f"El documento {label} está repetido: ya aparece en {_row_ref(ctx.seen_national_ids[key])} del archivo.",
                "national_id_number",
            )
        else:
            ctx.seen_national_ids[key] = row.row_number
            duplicate = others.filter(
                country=row.country, national_id_type=id_type, national_id_number=number
            ).only("employee_code").first()
            if duplicate:
                row.error(
                    "duplicate_employee",
                    f"Ya existe un empleado en {row.country.country_name} con el documento {label} "
                    f"(ID corporativo {duplicate.employee_code}).",
                    "national_id_number",
                )
    email = row.core.get("work_email")
    if email:
        if email in ctx.seen_emails:
            row.warn("duplicate_email", f"El correo laboral {email} se repite en {_row_ref(ctx.seen_emails[email])}.", "work_email")
        else:
            ctx.seen_emails[email] = row.row_number
            if others.filter(work_email__iexact=email).exists():
                row.warn("duplicate_email", f"El correo laboral {email} ya está asignado a otro empleado.", "work_email")
