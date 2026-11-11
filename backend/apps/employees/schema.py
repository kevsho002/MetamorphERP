"""Plantillas JSON por país: estructura, validación y resolución a una especificación de campos.

Estructura de `EmployeeTemplate.schema`:

{
  "core_fields": {                      # campos de hcm.Employee que el país ajusta
    "national_id_type":   {"default": "DUI", "choices": ["DUI", "PASAPORTE"]},
    "national_id_number": {"patterns_by_type": {"DUI": {"pattern": "^\\d{8}-\\d$", "example": "01234567-8"}}},
    "cost_center":        {"required": true},
    "work_email":         {"recommended": true}
  },
  "attributes": {                       # atributos dinámicos (EAV) que el país usa
    "tax_id":                 {"label": "NIT", "required": true, "pattern": "...", "example": "..."},
    "pension_fund":           {"label": "AFP", "required": true, "choices": ["CONFIA", "CRECER"]}
  },
  "rules": {"min_age": 18, "min_base_salary": "408.80", "max_future_hire_days": 90},
  "layout": {                           # (Fase 5, opcional) pestañas y secciones del expediente/formulario
    "tabs": [{"id": "personal", "label": "Datos personales",
              "sections": [{"id": "identity", "title": "Identificación", "fields": ["first_name", "last_name"]}]}]
  },
  "documents": {                        # (Fase 5, opcional) documentos del expediente que exige el país
    "NATIONAL_ID": {"label": "DUI", "required": true}
  }
}

Si falta `layout` se usa un diseño por defecto (datos personales / laborales / del país).
Los campos de la plantilla que el layout no ubique se agregan al final («Otros datos»): nada se oculta.

Reglas por campo (todas opcionales): label, required, recommended (si falta => advertencia),
default, pattern, example, pattern_message, patterns_by_type (solo national_id_number),
choices, min, max, min_length, max_length, transform (upper | lower | strip_spaces), help.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from apps.employees.models import AttributeDefinition, DataType

# --------------------------------------------------------------------- campos base
# Campos de hcm.Employee. `locked` = NOT NULL en BD: ninguna plantilla puede volverlos opcionales.


@dataclass(frozen=True)
class CoreField:
    label: str
    data_type: str
    required: bool = False
    locked: bool = False
    max_length: int | None = None
    choices: tuple[str, ...] = ()
    default: str | None = None


CORE_FIELDS: dict[str, CoreField] = {
    "first_name": CoreField("Primer nombre", DataType.STRING, True, True, 100),
    "middle_name": CoreField("Segundo nombre", DataType.STRING, max_length=100),
    "last_name": CoreField("Primer apellido", DataType.STRING, True, True, 100),
    "second_last_name": CoreField("Segundo apellido", DataType.STRING, max_length=100),
    "national_id_type": CoreField("Tipo de documento de identidad", DataType.STRING, True, True, 20),
    "national_id_number": CoreField("Número de documento de identidad", DataType.STRING, True, True, 30),
    "birth_date": CoreField("Fecha de nacimiento", DataType.DATE, True, True),
    "gender": CoreField("Género", DataType.CHOICE, choices=("M", "F", "X")),
    "work_email": CoreField("Correo laboral", DataType.EMAIL, max_length=254),
    "personal_email": CoreField("Correo personal", DataType.EMAIL, max_length=254),
    "phone_number": CoreField("Teléfono", DataType.STRING, max_length=30),
    "hire_date": CoreField("Fecha de ingreso", DataType.DATE, True, True),
    "base_salary": CoreField("Salario base", DataType.DECIMAL, True, True),
    "pay_frequency": CoreField(
        "Frecuencia de pago", DataType.CHOICE, choices=("MONTHLY", "BIWEEKLY", "WEEKLY"), default="MONTHLY"
    ),
    "cost_center": CoreField("Centro de costos", DataType.STRING, max_length=20),
}

FIELD_RULE_KEYS = {
    "label",
    "required",
    "recommended",
    "default",
    "pattern",
    "example",
    "pattern_message",
    "patterns_by_type",
    "choices",
    "min",
    "max",
    "min_length",
    "max_length",
    "transform",
    "help",
}
TEMPLATE_RULE_KEYS = {"min_age", "max_age", "min_base_salary", "max_base_salary", "max_future_hire_days"}
TRANSFORMS = {"upper", "lower", "strip_spaces"}
TOP_LEVEL_KEYS = {"core_fields", "attributes", "rules", "layout", "documents"}
DOCUMENT_RULE_KEYS = {"label", "required", "help"}
_LAYOUT_ID = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

# Diseño por defecto del expediente (si la plantilla no define `layout`).
DEFAULT_CORE_TABS: list[dict] = [
    {
        "id": "personal",
        "label": "Datos personales",
        "sections": [
            {"id": "identity", "title": "Identificación",
             "fields": ["first_name", "middle_name", "last_name", "second_last_name", "birth_date", "gender"]},
            {"id": "id_document", "title": "Documento de identidad", "fields": ["national_id_type", "national_id_number"]},
            {"id": "contact", "title": "Contacto", "fields": ["work_email", "personal_email", "phone_number"]},
        ],
    },
    {
        "id": "employment",
        "label": "Datos laborales",
        "sections": [
            {"id": "hiring", "title": "Contratación y compensación",
             "fields": ["hire_date", "cost_center", "base_salary", "pay_frequency"]},
        ],
    },
]

# Sinónimos aceptados para opciones de campos base (formulario y archivos en español).
CHOICE_SYNONYMS = {
    "gender": {
        "MASCULINO": "M", "HOMBRE": "M", "H": "M", "MALE": "M",
        "FEMENINO": "F", "MUJER": "F", "FEMALE": "F",
        "OTRO": "X", "NO BINARIO": "X", "NO ESPECIFICADO": "X",
    },
    "pay_frequency": {"MENSUAL": "MONTHLY", "QUINCENAL": "BIWEEKLY", "CATORCENAL": "BIWEEKLY", "SEMANAL": "WEEKLY"},
}


# --------------------------------------------------------------------- especificación resuelta
@dataclass
class FieldSpec:
    key: str
    label: str
    kind: str  # "core" | "attribute"
    data_type: str
    required: bool = False
    recommended: bool = False
    default: Any = None
    pattern: re.Pattern | None = None
    example: str | None = None
    pattern_message: str | None = None
    patterns_by_type: dict[str, dict] = field(default_factory=dict)
    choices: tuple[str, ...] = ()
    min: Decimal | None = None
    max: Decimal | None = None
    min_length: int | None = None
    max_length: int | None = None
    transform: str | None = None
    help: str | None = None
    attribute: AttributeDefinition | None = None

    def as_dict(self) -> dict:
        """Forma serializable: el frontend la usa para construir el formulario dinámico."""
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "data_type": self.data_type,
            "required": self.required,
            "recommended": self.recommended,
            "default": self.default,
            "pattern": self.pattern.pattern if self.pattern else None,
            "example": self.example,
            "pattern_message": self.pattern_message,
            "patterns_by_type": self.patterns_by_type or None,
            "choices": list(self.choices) or None,
            "min": str(self.min) if self.min is not None else None,
            "max": str(self.max) if self.max is not None else None,
            "min_length": self.min_length,
            "max_length": self.max_length,
            "help": self.help,
            "transform": self.transform,
        }


@dataclass
class TemplateSpec:
    template_id: int | None
    name: str
    country_code: str
    effective_date: date
    fields: dict[str, FieldSpec]
    rules: dict[str, Any]
    layout: list[dict] = field(default_factory=list)  # pestañas resueltas (todas las claves existen)
    documents_config: dict[str, dict] = field(default_factory=dict)

    @property
    def core(self) -> dict[str, FieldSpec]:
        return {k: f for k, f in self.fields.items() if f.kind == "core"}

    @property
    def attributes(self) -> dict[str, FieldSpec]:
        return {k: f for k, f in self.fields.items() if f.kind == "attribute"}

    def describe(self) -> str:
        return f"«{self.name}» (vigente desde {self.effective_date:%d/%m/%Y})"

    def as_dict(self) -> dict:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "country": self.country_code,
            "effective_date": self.effective_date.isoformat(),
            "fields": [f.as_dict() for f in self.fields.values()],
            "rules": {k: (str(v) if isinstance(v, Decimal) else v) for k, v in self.rules.items()},
            "layout": self.layout,
        }


# --------------------------------------------------------------------- validación de la plantilla
def _check_rules(path: str, rules: Any, data_type: str, errors: list[str]) -> None:
    if not isinstance(rules, dict):
        errors.append(f"{path}: debe ser un objeto JSON con reglas (por ejemplo {{\"required\": true}}).")
        return
    for key in rules:
        if key not in FIELD_RULE_KEYS:
            errors.append(f"{path}: regla desconocida «{key}». Reglas válidas: {', '.join(sorted(FIELD_RULE_KEYS))}.")
    for flag in ("required", "recommended"):
        if flag in rules and not isinstance(rules[flag], bool):
            errors.append(f"{path}.{flag}: debe ser true o false.")
    for key in ("pattern",):
        if key in rules:
            try:
                re.compile(rules[key])
            except (re.error, TypeError) as exc:
                errors.append(f"{path}.pattern: expresión regular inválida ({exc}).")
    if "patterns_by_type" in rules:
        if not path.endswith("national_id_number"):
            errors.append(f"{path}.patterns_by_type: solo se admite en core_fields.national_id_number.")
        elif not isinstance(rules["patterns_by_type"], dict):
            errors.append(f"{path}.patterns_by_type: debe ser un objeto {{TIPO: {{pattern, example}}}}.")
        else:
            for id_type, spec in rules["patterns_by_type"].items():
                try:
                    re.compile(spec["pattern"])
                except (KeyError, TypeError, re.error) as exc:
                    errors.append(f"{path}.patterns_by_type.{id_type}: requiere un «pattern» válido ({exc}).")
    if "choices" in rules:
        choices = rules["choices"]
        if not isinstance(choices, list) or not choices or not all(isinstance(c, str) and c.strip() for c in choices):
            errors.append(f"{path}.choices: debe ser una lista no vacía de textos.")
    elif data_type == DataType.CHOICE and not path.startswith("core_fields"):
        errors.append(f"{path}: el atributo es de tipo «Lista de opciones» y requiere «choices».")
    for key in ("min", "max"):
        if key in rules:
            try:
                Decimal(str(rules[key]))
            except InvalidOperation:
                errors.append(f"{path}.{key}: debe ser numérico.")
    for key in ("min_length", "max_length"):
        if key in rules and (not isinstance(rules[key], int) or rules[key] < 0):
            errors.append(f"{path}.{key}: debe ser un entero >= 0.")
    if "transform" in rules and rules["transform"] not in TRANSFORMS:
        errors.append(f"{path}.transform: valores válidos {', '.join(sorted(TRANSFORMS))}.")


def validate_template_schema(schema: Any) -> None:
    """Lanza ValidationError con TODOS los problemas encontrados (pensado para el admin)."""
    errors: list[str] = []
    if not isinstance(schema, dict):
        raise ValidationError({"schema": "La plantilla debe ser un objeto JSON."})
    for key in schema:
        if key not in TOP_LEVEL_KEYS:
            errors.append(f"Clave desconocida «{key}». Claves válidas: {', '.join(sorted(TOP_LEVEL_KEYS))}.")

    core = schema.get("core_fields", {})
    if not isinstance(core, dict):
        errors.append("core_fields: debe ser un objeto.")
        core = {}
    for name, rules in core.items():
        base = CORE_FIELDS.get(name)
        if base is None:
            errors.append(f"core_fields.{name}: no es un campo de hcm.Employee. Válidos: {', '.join(CORE_FIELDS)}.")
            continue
        _check_rules(f"core_fields.{name}", rules, base.data_type, errors)
        if isinstance(rules, dict) and base.locked and rules.get("required") is False:
            errors.append(f"core_fields.{name}: es obligatorio en la base de datos; no puede marcarse required=false.")

    attributes = schema.get("attributes", {})
    if not isinstance(attributes, dict):
        errors.append("attributes: debe ser un objeto {código: reglas}.")
        attributes = {}
    known = {a.code: a for a in AttributeDefinition.objects.filter(code__in=list(attributes))}
    for code, rules in attributes.items():
        definition = known.get(code)
        if definition is None:
            errors.append(f"attributes.{code}: no existe en el catálogo de atributos dinámicos.")
            continue
        if not definition.is_active:
            errors.append(f"attributes.{code}: el atributo está inactivo en el catálogo.")
        _check_rules(f"attributes.{code}", rules, definition.data_type, errors)

    rules = schema.get("rules", {})
    if not isinstance(rules, dict):
        errors.append("rules: debe ser un objeto.")
        rules = {}
    for key, value in rules.items():
        if key not in TEMPLATE_RULE_KEYS:
            errors.append(f"rules.{key}: regla desconocida. Válidas: {', '.join(sorted(TEMPLATE_RULE_KEYS))}.")
            continue
        try:
            Decimal(str(value))
        except InvalidOperation:
            errors.append(f"rules.{key}: debe ser numérico.")

    _check_layout(schema.get("layout"), set(CORE_FIELDS), set(attributes), errors)
    _check_documents(schema.get("documents"), errors)

    if errors:
        raise ValidationError({"schema": errors})


def _check_layout(layout: Any, core_keys: set[str], attribute_keys: set[str], errors: list[str]) -> None:
    if layout is None:
        return
    if not isinstance(layout, dict) or not isinstance(layout.get("tabs"), list) or not layout["tabs"]:
        errors.append('layout: debe ser {"tabs": [{"id", "label", "sections": [{"id", "title", "fields": [...]}]}]}.')
        return
    unknown = set(layout) - {"tabs"}
    if unknown:
        errors.append(f"layout: claves desconocidas {', '.join(sorted(unknown))}.")
    valid_keys = core_keys | attribute_keys
    seen_fields: set[str] = set()
    seen_ids: set[tuple[str, str]] = set()
    for t_index, tab in enumerate(layout["tabs"]):
        path = f"layout.tabs[{t_index}]"
        if not isinstance(tab, dict):
            errors.append(f"{path}: debe ser un objeto.")
            continue
        for key in sorted(set(tab) - {"id", "label", "sections", "description"}):
            errors.append(f"{path}: clave desconocida «{key}».")
        if not isinstance(tab.get("id"), str) or not _LAYOUT_ID.match(tab["id"]):
            errors.append(f"{path}.id: use minúsculas, dígitos y guion bajo (máx. 40), iniciando con letra.")
        elif ("tab", tab["id"]) in seen_ids:
            errors.append(f"{path}.id: «{tab['id']}» está repetido.")
        else:
            seen_ids.add(("tab", tab["id"]))
        if not isinstance(tab.get("label"), str) or not tab["label"].strip():
            errors.append(f"{path}.label: requerido.")
        sections = tab.get("sections")
        if not isinstance(sections, list) or not sections:
            errors.append(f"{path}.sections: debe ser una lista no vacía.")
            continue
        for s_index, section in enumerate(sections):
            spath = f"{path}.sections[{s_index}]"
            if not isinstance(section, dict):
                errors.append(f"{spath}: debe ser un objeto.")
                continue
            for key in sorted(set(section) - {"id", "title", "description", "fields"}):
                errors.append(f"{spath}: clave desconocida «{key}».")
            if not isinstance(section.get("id"), str) or not _LAYOUT_ID.match(section["id"]):
                errors.append(f"{spath}.id: use minúsculas, dígitos y guion bajo, iniciando con letra.")
            elif ("section", section["id"]) in seen_ids:
                errors.append(f"{spath}.id: «{section['id']}» está repetido.")
            else:
                seen_ids.add(("section", section["id"]))
            if not isinstance(section.get("title"), str) or not section["title"].strip():
                errors.append(f"{spath}.title: requerido.")
            fields = section.get("fields")
            if not isinstance(fields, list) or not fields or not all(isinstance(f, str) for f in fields):
                errors.append(f"{spath}.fields: debe ser una lista no vacía de claves de campo.")
                continue
            for key in fields:
                if key not in valid_keys:
                    errors.append(f"{spath}.fields: «{key}» no es un campo base ni un atributo de esta plantilla.")
                elif key in seen_fields:
                    errors.append(f"{spath}.fields: «{key}» ya está ubicado en otra sección.")
                seen_fields.add(key)


def _check_documents(documents: Any, errors: list[str]) -> None:
    if documents is None:
        return
    if not isinstance(documents, dict):
        errors.append('documents: debe ser un objeto {CÓDIGO_DOCUMENTO: {"required": true, "label": "..."}}.')
        return
    from apps.hcm.models import DocumentType

    known = {d.code: d for d in DocumentType.objects.filter(code__in=list(documents))}
    for code, rules in documents.items():
        path = f"documents.{code}"
        if code not in known:
            errors.append(f"{path}: no existe en el catálogo de tipos de documento (hcm.catDocumentType).")
            continue
        if code == DocumentType.PROFILE_PHOTO:
            errors.append(f"{path}: la fotografía de perfil se gestiona aparte; no se configura como documento.")
        if not isinstance(rules, dict):
            errors.append(f"{path}: debe ser un objeto con label / required / help.")
            continue
        for key in sorted(set(rules) - DOCUMENT_RULE_KEYS):
            errors.append(f"{path}: regla desconocida «{key}». Válidas: {', '.join(sorted(DOCUMENT_RULE_KEYS))}.")
        if "required" in rules and not isinstance(rules["required"], bool):
            errors.append(f"{path}.required: debe ser true o false.")
        for key in ("label", "help"):
            if key in rules and (not isinstance(rules[key], str) or not rules[key].strip()):
                errors.append(f"{path}.{key}: debe ser un texto no vacío.")


# --------------------------------------------------------------------- resolución
def _apply_rules(spec: FieldSpec, rules: dict) -> FieldSpec:
    if "label" in rules:
        spec.label = rules["label"]
    if "required" in rules:
        spec.required = rules["required"] or spec.required
    spec.recommended = bool(rules.get("recommended", spec.recommended))
    spec.default = rules.get("default", spec.default)
    if "pattern" in rules:
        spec.pattern = re.compile(rules["pattern"])
    spec.example = rules.get("example", spec.example)
    spec.pattern_message = rules.get("pattern_message", spec.pattern_message)
    spec.patterns_by_type = {k.upper(): v for k, v in rules.get("patterns_by_type", {}).items()}
    if "choices" in rules:
        spec.choices = tuple(c.strip() for c in rules["choices"])
    for key in ("min", "max"):
        if key in rules:
            setattr(spec, key, Decimal(str(rules[key])))
    if "min_length" in rules:
        spec.min_length = rules["min_length"]
    if "max_length" in rules:
        spec.max_length = min(rules["max_length"], spec.max_length or rules["max_length"])
    spec.transform = rules.get("transform", spec.transform)
    spec.help = rules.get("help", spec.help)
    return spec


def resolve_template(template) -> TemplateSpec:
    """Combina los campos base de hcm.Employee con las reglas del país -> TemplateSpec."""
    schema = template.schema or {}
    fields: dict[str, FieldSpec] = {}
    core_rules = schema.get("core_fields", {})
    for key, base in CORE_FIELDS.items():
        spec = FieldSpec(
            key=key,
            label=base.label,
            kind="core",
            data_type=base.data_type,
            required=base.required,
            max_length=base.max_length,
            choices=base.choices,
            default=base.default,
        )
        fields[key] = _apply_rules(spec, core_rules.get(key, {}))

    attr_rules = schema.get("attributes", {})
    definitions = {a.code: a for a in AttributeDefinition.objects.filter(code__in=list(attr_rules), is_active=True)}
    for code, rules in attr_rules.items():
        definition = definitions.get(code)
        if definition is None:
            continue  # atributo desactivado después de crear la plantilla: se ignora
        spec = FieldSpec(
            key=code, label=definition.name, kind="attribute", data_type=definition.data_type, max_length=500,
            attribute=definition, help=definition.description or None,
        )
        fields[code] = _apply_rules(spec, rules)

    rules = {k: (Decimal(str(v)) if k.endswith("salary") else int(v)) for k, v in schema.get("rules", {}).items()}
    return TemplateSpec(
        template_id=template.pk,
        name=template.name,
        country_code=template.country.country_code,
        effective_date=template.effective_date,
        fields=fields,
        rules=rules,
        layout=resolve_layout(schema.get("layout"), fields, template.country.country_name),
        documents_config=schema.get("documents") or {},
    )


def resolve_layout(layout: dict | None, fields: dict[str, FieldSpec], country_name: str) -> list[dict]:
    """Pestañas -> secciones -> claves de campo, solo con campos que existen en la plantilla.

    Sin `layout` en la plantilla: diseño por defecto + una pestaña con los atributos del país.
    Lo que el layout no ubique se agrega en «Otros datos» (ningún dato queda oculto).
    """
    if layout and isinstance(layout.get("tabs"), list):
        tabs_src = layout["tabs"]
    else:
        attributes = [k for k, f in fields.items() if f.kind == "attribute"]
        tabs_src = [*DEFAULT_CORE_TABS]
        if attributes:
            tabs_src.append({
                "id": "country",
                "label": f"Datos de {country_name}",
                "sections": [{
                    "id": "country_attributes",
                    "title": "Requeridos por la plantilla del país",
                    "description": "Seguridad social, previsión, datos bancarios y otros campos que define el país.",
                    "fields": attributes,
                }],
            })
    placed: set[str] = set()
    tabs: list[dict] = []
    for tab in tabs_src:
        sections = []
        for section in tab.get("sections", []):
            keys = [k for k in section.get("fields", []) if k in fields and k not in placed]
            placed.update(keys)
            if keys:
                sections.append({
                    "id": section["id"], "title": section["title"],
                    "description": section.get("description"), "fields": keys,
                })
        if sections:
            tabs.append({"id": tab["id"], "label": tab["label"], "description": tab.get("description"), "sections": sections})
    leftover = [k for k in fields if k not in placed]
    if leftover:
        extra = {"id": "other_fields", "title": "Otros datos", "description": None, "fields": leftover}
        if tabs:
            tabs[-1]["sections"].append(extra)
        else:
            tabs.append({"id": "other", "label": "Otros datos", "description": None, "sections": [extra]})
    return tabs


# --------------------------------------------------------------------- conversión de valores
class FieldValueError(Exception):
    """Valor inválido: el mensaje ya está redactado para el usuario final."""

    def __init__(self, message: str, code: str = "invalid_value"):
        super().__init__(message)
        self.message = message
        self.code = code


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y")
_TRUE = {"TRUE", "1", "SI", "SÍ", "S", "X", "YES", "Y", "VERDADERO"}
_FALSE = {"FALSE", "0", "NO", "N", "FALSO"}


def _fold(text: str) -> str:
    """Mayúsculas y sin tildes: «Confía» == «CONFIA»."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().upper().strip()


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _as_text(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # Excel entrega 12345678.0
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    return " ".join(str(value).split())


def parse_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _as_text(value)
    if text.endswith(" 00:00:00"):
        text = text[:-9]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise FieldValueError(f"«{text}» no es una fecha válida; use AAAA-MM-DD (p. ej. 2026-03-01) o DD/MM/AAAA.", "invalid_date")


def parse_decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise FieldValueError(f"«{value}» no es un número.", "invalid_number")
    if isinstance(value, (int, Decimal)):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    text = _as_text(value).replace(" ", "").replace("$", "")
    if "," in text and "." in text:
        text = text.replace(",", "")  # 1,234.56
    elif text.count(",") == 1 and len(text.split(",")[1]) <= 2:
        text = text.replace(",", ".")  # 1234,56
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise FieldValueError(f"«{_as_text(value)}» no es un número válido.", "invalid_number") from None
    if not number.is_finite():
        raise FieldValueError(f"«{_as_text(value)}» no es un número válido.", "invalid_number")
    return number


def coerce_value(spec: FieldSpec, raw: Any) -> tuple[Any, str]:
    """Convierte y valida un valor NO vacío según el campo. Devuelve (valor Python, texto canónico).

    Lanza FieldValueError con un mensaje en lenguaje natural.
    """
    label = f"«{spec.label}»"
    dt = spec.data_type
    if dt == DataType.DATE:
        parsed = parse_date(raw)
        return parsed, parsed.isoformat()
    if dt in (DataType.DECIMAL, DataType.INTEGER):
        number = parse_decimal(raw)
        if dt == DataType.INTEGER and number != number.to_integral_value():
            raise FieldValueError(f"{label} debe ser un número entero; se recibió «{_as_text(raw)}».", "invalid_number")
        if spec.min is not None and number < spec.min:
            raise FieldValueError(f"{label} debe ser mayor o igual a {spec.min}; se recibió {number}.", "out_of_range")
        if spec.max is not None and number > spec.max:
            raise FieldValueError(f"{label} debe ser menor o igual a {spec.max}; se recibió {number}.", "out_of_range")
        if dt == DataType.INTEGER:
            number = int(number)
            return number, str(number)
        return number, format(number.normalize(), "f")
    if dt == DataType.BOOLEAN:
        text = _as_text(raw).upper() if not isinstance(raw, bool) else ("TRUE" if raw else "FALSE")
        if text in _TRUE:
            return True, "true"
        if text in _FALSE:
            return False, "false"
        raise FieldValueError(f"{label} debe ser Sí o No; se recibió «{_as_text(raw)}».", "invalid_boolean")

    text = _as_text(raw)
    if spec.transform == "upper" or dt == DataType.CHOICE:
        text = text.upper()
    elif spec.transform == "lower" or dt == DataType.EMAIL:
        text = text.lower()
    if spec.transform == "strip_spaces":
        text = text.replace(" ", "")

    if dt == DataType.CHOICE or spec.choices:
        options = {_fold(c): c for c in spec.choices}  # sin distinguir mayúsculas ni tildes
        candidate = _fold(CHOICE_SYNONYMS.get(spec.key, {}).get(_fold(text), text))
        if candidate not in options:
            raise FieldValueError(
                f"{label} tiene un valor no permitido «{text}». Opciones válidas: {', '.join(spec.choices)}.",
                "invalid_choice",
            )
        text = options[candidate]
    if dt == DataType.EMAIL:
        try:
            validate_email(text)
        except ValidationError:
            raise FieldValueError(f"{label} «{text}» no es un correo electrónico válido.", "invalid_email") from None
    if spec.max_length is not None and len(text) > spec.max_length:
        raise FieldValueError(
            f"{label} admite como máximo {spec.max_length} caracteres; se recibieron {len(text)}.", "too_long"
        )
    if spec.min_length is not None and len(text) < spec.min_length:
        raise FieldValueError(f"{label} requiere al menos {spec.min_length} caracteres; se recibieron {len(text)}.", "too_short")
    if spec.pattern is not None and not spec.pattern.fullmatch(text):
        raise FieldValueError(format_pattern_error(spec.label, text, spec.example, spec.pattern_message, raw), "invalid_format")
    return text, text


def format_pattern_error(label: str, text: str, example: str | None, custom: str | None, raw: Any = None) -> str:
    message = f"«{label}» con valor «{text}» no tiene el formato esperado"
    message += f" ({custom})" if custom else ""
    message += f"; ejemplo válido: {example}." if example else "."
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        message += " La celda es numérica: Excel pudo eliminar ceros a la izquierda o guiones; formatee la columna como Texto."
    return message
