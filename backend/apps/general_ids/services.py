"""Reglas de negocio de los General IDs (la API solo orquesta; el trigger SQL es la última barrera).

Validaciones de un registro (alta, corrección o cierre):
* tipo existente y activo (para altas); valor normalizado (transform) que cumple longitud y patrón;
* vigencia: «desde» obligatorio, «hasta» >= «desde»; dentro de la relación laboral
  (no antes del ingreso — advertencia — ni después de la terminación — error);
* nivel de registro: GLOBAL sin cliente/marca; CLIENT exige cliente (marca opcional y del cliente);
  BRAND exige marca;
* restricciones en cascada configuradas en el cliente / la marca:
    sin restricciones  -> aplica a todos;
    cliente habilitado -> aplica al cliente y a TODAS sus marcas;
    marca habilitada   -> aplica solo a esa marca (el cliente sin marca no basta);
* unicidad temporal: con «valor único», un valor no identifica a dos registros en fechas que se cruzan;
  sin «varios activos por empleado», un empleado no tiene dos IDs de ese tipo vigentes a la vez.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from django.db import transaction

from apps.general_ids.models import EmployeeGeneralId, GeneralIdType, ScopeLevel, Transform
from apps.hcm.models import Employee
from apps.operations.models import Brand, Client
from apps.system.audit import Category, record

FAR_FUTURE = date(9999, 12, 31)


def fmt(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "Now"


def parse_any_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    return None


@dataclass
class Check:
    errors: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    cleaned: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, field_name: str | None, message: str, code: str = "invalid") -> None:
        self.errors.append({"field": field_name, "message": message, "code": code})

    def warn(self, field_name: str | None, message: str, code: str = "warning") -> None:
        self.warnings.append({"field": field_name, "message": message, "code": code})

    def feedback(self, verb: str = "registrar") -> str:
        if self.errors:
            return f"No se puede {verb} el General ID: " + " ".join(e["message"] for e in self.errors)
        text = "Datos válidos."
        if self.warnings:
            text += " Advertencias: " + " ".join(w["message"] for w in self.warnings)
        return text


# --------------------------------------------------------------------- aplicabilidad (cascada)
def scope_summary(id_type: GeneralIdType) -> dict:
    clients = list(id_type.client_scopes.select_related("client").order_by("client__name"))
    brands = list(id_type.brand_scopes.select_related("brand__client").order_by("brand__name"))
    return {
        "all": not clients and not brands,
        "clients": [{"id": s.client_id, "code": s.client.code, "name": s.client.name} for s in clients],
        "brands": [
            {"id": s.brand_id, "code": s.brand.code, "name": s.brand.name, "client_id": s.brand.client_id} for s in brands
        ],
    }


def applicability_error(id_type: GeneralIdType, client: Client | None, brand: Brand | None) -> str | None:
    """None si el tipo aplica a (cliente, marca) según las restricciones en cascada."""
    client_ids = set(id_type.client_scopes.values_list("client_id", flat=True))
    brand_rows = list(id_type.brand_scopes.select_related("brand").values_list("brand_id", "brand__client_id"))
    if not client_ids and not brand_rows:
        return None
    brand_ids = {b for b, _ in brand_rows}
    if brand is not None:
        if brand.pk in brand_ids or brand.client_id in client_ids:
            return None
        return f"«{id_type.name}» no aplica a la marca «{brand.name}» (restricción configurada en el cliente / la marca)."
    if client is not None:
        if client.pk in client_ids:
            return None
        if any(c == client.pk for _, c in brand_rows):
            names = ", ".join(sorted(Brand.objects.filter(pk__in=brand_ids, client=client).values_list("name", flat=True)))
            return f"Para «{client.name}», «{id_type.name}» solo aplica a algunas marcas ({names}): indique la marca."
        return f"«{id_type.name}» no aplica al cliente «{client.name}» (restricción configurada en el cliente / la marca)."
    return f"«{id_type.name}» está restringido a clientes o marcas específicos: indique el cliente."


# --------------------------------------------------------------------- normalización del valor
def normalize_value(id_type: GeneralIdType, raw: Any) -> str:
    text = " ".join(str(raw or "").split())
    if id_type.transform == Transform.UPPER:
        text = text.upper()
    elif id_type.transform == Transform.LOWER:
        text = text.lower()
    return text


def _lookup(model, raw, label: str, check: Check, field_name: str):
    if raw in (None, ""):
        return None
    qs = model.objects.all()
    obj = qs.filter(pk=raw).first() if str(raw).isdigit() else None
    obj = obj or qs.filter(code__iexact=str(raw).strip()).first()
    if obj is None:
        check.error(field_name, f"No existe {label} «{raw}» en el catálogo.", "unknown")
    return obj


# --------------------------------------------------------------------- validación
def validate(employee: Employee, data: dict, *, instance: EmployeeGeneralId | None = None) -> Check:
    """Valida alta (instance=None) o corrección de `instance` (data = campos enviados, semántica PATCH)."""
    check = Check()
    base = {
        "id_type": instance.id_type_id if instance else None,
        "value": instance.value if instance else "",
        "client": instance.client_id if instance else None,
        "brand": instance.brand_id if instance else None,
        "effective_start": instance.effective_start if instance else None,
        "effective_end": instance.effective_end if instance else None,
        "notes": instance.notes if instance else "",
    }
    merged = {**base, **{k: v for k, v in data.items() if k in base}}

    # Tipo
    id_type = None
    if instance is not None and "id_type" in data and str(data["id_type"]) not in {str(instance.id_type_id), instance.id_type.code}:
        check.error("id_type", "El tipo de un General ID no se cambia: cierre este registro y cree uno nuevo.", "immutable")
        id_type = instance.id_type
    elif instance is not None:
        id_type = instance.id_type
    elif merged["id_type"] in (None, ""):
        check.error("id_type", "Seleccione el tipo de ID.", "required")
    else:
        id_type = _lookup_type(merged["id_type"], check)
        if id_type is not None and not id_type.is_active:
            check.error("id_type", f"El tipo «{id_type.name}» está inactivo: no admite registros nuevos.", "inactive")
        if id_type is not None and not id_type.tool.is_active:
            check.error("id_type", f"La herramienta «{id_type.tool.name}» está inactiva.", "inactive")

    # Valor
    value = ""
    if id_type is not None:
        value = normalize_value(id_type, merged["value"])
        if not value:
            check.error("value", "Indique el valor del ID.", "required")
        elif len(value) > id_type.max_length:
            check.error("value", f"El valor admite como máximo {id_type.max_length} caracteres; tiene {len(value)}.", "too_long")
        elif id_type.pattern and not re.fullmatch(id_type.pattern, value):
            hint = f" ({id_type.pattern_message})" if id_type.pattern_message else ""
            example = f" Ejemplo válido: {id_type.example}." if id_type.example else ""
            check.error("value", f"«{value}» no tiene el formato de {id_type.name}{hint}.{example}", "invalid_format")

    # Vigencia
    start = parse_any_date(merged["effective_start"])
    end = parse_any_date(merged["effective_end"])
    if merged["effective_start"] in (None, ""):
        check.error("effective_start", "Indique la fecha «vigente desde».", "required")
    elif start is None:
        check.error("effective_start", "Fecha «vigente desde» inválida; use AAAA-MM-DD.", "invalid_date")
    if merged["effective_end"] not in (None, "") and end is None:
        check.error("effective_end", "Fecha «vigente hasta» inválida; use AAAA-MM-DD o déjela vacía (Now).", "invalid_date")
    if start and end and end < start:
        check.error("effective_end", f"«Vigente hasta» ({fmt(end)}) es anterior a «vigente desde» ({fmt(start)}).", "invalid_range")
    if start and start < employee.hire_date:
        check.warn("effective_start", f"Inicia antes de la fecha de ingreso del empleado ({fmt(employee.hire_date)}).", "before_hire")
    if employee.termination_date and start and start > employee.termination_date:
        check.error(
            "effective_start", f"El empleado terminó el {fmt(employee.termination_date)}: no se registran IDs posteriores.", "terminated"
        )

    # Cliente / marca
    client = _lookup(Client, merged["client"], "el cliente", check, "client")
    brand = _lookup(Brand, merged["brand"], "la marca", check, "brand")
    if brand is not None:
        if client is None:
            client = brand.client
        elif brand.client_id != client.pk:
            check.error("brand", f"La marca «{brand.name}» pertenece a «{brand.client.name}», no a «{client.name}».", "hierarchy")
    if id_type is not None:
        if id_type.scope_level == ScopeLevel.GLOBAL and (client or brand):
            check.error("client", f"«{id_type.name}» es global: no se asocia a cliente ni marca.", "scope")
        elif id_type.scope_level == ScopeLevel.CLIENT and client is None:
            check.error("client", f"«{id_type.name}» se registra por cliente: indíquelo.", "required")
        elif id_type.scope_level == ScopeLevel.BRAND and brand is None:
            check.error("brand", f"«{id_type.name}» se registra por marca: indíquela.", "required")
        scope_errors = any(e["field"] in {"client", "brand"} for e in check.errors)
        if id_type.scope_level != ScopeLevel.GLOBAL and (client or brand) and not scope_errors:
            if problem := applicability_error(id_type, client, brand):
                check.error("brand" if brand else "client", problem, "not_applicable")
    for obj, label in ((client, "El cliente"), (brand, "La marca")):
        if obj is not None and not obj.is_active:
            check.warn("brand" if label == "La marca" else "client", f"{label} «{obj.name}» está inactivo en el catálogo.", "inactive")
    if client and client.country_id and client.country_id != employee.country_id:
        check.warn("client", f"«{client.name}» opera en {client.country}, distinto del país del empleado.", "country")

    # Unicidad temporal
    if id_type is not None and value and start and not check.errors:
        others = EmployeeGeneralId.objects.filter(id_type=id_type).overlapping(start, end)
        if instance is not None:
            others = others.exclude(pk=instance.pk)
        if id_type.unique_value:
            clash = others.filter(value__iexact=value).select_related("employee").first()
            if clash is not None:
                who = "este mismo empleado" if clash.employee_id == employee.pk else f"el empleado {clash.employee.employee_code}"
                check.error(
                    "value",
                    f"El {id_type.name} «{value}» ya pertenece a {who} del {fmt(clash.effective_start)} al "
                    f"{fmt(clash.effective_end)}: un valor solo puede identificar a un registro a la vez.",
                    "duplicate_value",
                )
        if not id_type.allow_multiple_active:
            mine = others.filter(employee=employee).first()
            if mine is not None:
                check.error(
                    "effective_start",
                    f"El empleado ya tiene el {id_type.name} «{mine.value}» vigente del {fmt(mine.effective_start)} al "
                    f"{fmt(mine.effective_end)}. Cierre ese registro (vigente hasta) antes de registrar otro.",
                    "overlap",
                )

    check.cleaned = {
        "id_type": id_type, "value": value, "client": client, "brand": brand,
        "effective_start": start, "effective_end": end, "notes": str(merged.get("notes") or "").strip()[:300],
    }
    return check


def _lookup_type(raw, check: Check) -> GeneralIdType | None:
    qs = GeneralIdType.objects.select_related("tool")
    obj = qs.filter(pk=raw).first() if str(raw).isdigit() else None
    obj = obj or qs.filter(code__iexact=str(raw).strip()).first()
    if obj is None:
        check.error("id_type", f"No existe el tipo de ID «{raw}».", "unknown")
    return obj


# --------------------------------------------------------------------- escritura
def _describe(g: EmployeeGeneralId) -> str:
    scope = f" ({g.brand.name if g.brand_id else g.client.name})" if g.client_id else ""
    return f"{g.id_type.name}{scope} = «{g.value}», {fmt(g.effective_start)} → {fmt(g.effective_end)}"


@transaction.atomic
def create(employee: Employee, check: Check, *, user, request=None) -> EmployeeGeneralId:
    c = check.cleaned
    Employee.objects.select_for_update().filter(pk=employee.pk).first()  # serializa altas concurrentes del empleado
    g = EmployeeGeneralId.objects.create(
        employee=employee, id_type=c["id_type"], value=c["value"], client=c["client"], brand=c["brand"],
        effective_start=c["effective_start"], effective_end=c["effective_end"], notes=c["notes"],
        created_by=user.username, updated_by=user.username,
    )
    record(
        "general_id_created", Category.GENERAL_IDS, f"General ID registrado para {employee.employee_code}: {_describe(g)}.",
        request=request, target=employee, details={"general_id": g.pk, "id_type": g.id_type.code, "value": g.value},
    )
    return g


@transaction.atomic
def update(g: EmployeeGeneralId, check: Check, *, user, request=None, action: str = "general_id_updated") -> EmployeeGeneralId:
    c = check.cleaned
    before = _describe(g)
    for attr in ("value", "client", "brand", "effective_start", "effective_end", "notes"):
        setattr(g, attr, c[attr])
    g.updated_by = user.username
    g.save()
    verb = "cerrado" if action == "general_id_closed" else "corregido"
    record(
        action, Category.GENERAL_IDS, f"General ID {verb} de {g.employee.employee_code}: {before} ⇒ {_describe(g)}.",
        request=request, target=g.employee, details={"general_id": g.pk, "id_type": g.id_type.code},
    )
    return g


def serialize(g: EmployeeGeneralId, on_date: date | None = None) -> dict:
    on_date = on_date or date.today()
    return {
        "id": g.pk,
        "id_type": g.id_type.code,
        "id_type_name": g.id_type.name,
        "tool": g.id_type.tool.code,
        "tool_name": g.id_type.tool.name,
        "value": g.value,
        "client": g.client.code if g.client_id else None,
        "client_name": g.client.name if g.client_id else None,
        "brand": g.brand.code if g.brand_id else None,
        "brand_name": g.brand.name if g.brand_id else None,
        "effective_start": g.effective_start,
        "effective_end": g.effective_end,
        "is_now": g.effective_end is None,
        "is_current": g.effective_start <= on_date <= (g.effective_end or FAR_FUTURE),
        "is_future": g.effective_start > on_date,
        "notes": g.notes,
        "created_at": g.created_at,
        "created_by": g.created_by,
        "updated_at": g.updated_at,
        "updated_by": g.updated_by,
    }
