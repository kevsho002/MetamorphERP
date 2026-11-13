"""Fase 22 — Campos dinámicos de las AP: hora, actividad de la grilla y dato del roster / expediente.

* TIME      «HH:MM» o «HH:MM:SS» (24 h); se guarda normalizado «HH:MM:SS».
* ACTIVITY  código de una actividad de la grilla (sub-segmento del Time Utilization). `choices` del campo filtra por
            prefijos de código (p. ej. ["HRP_"] para permisos con goce) y excluye con «!CÓDIGO»; las opciones se leen
            del catálogo vivo.
* ROSTER    la CLAVE del campo es el código de un atributo del roster (cliente, marca, Team Manager, puesto…) o la
            seudo-clave «cost_center» (centro de costos del expediente). Las opciones salen del catálogo del roster.
"""

from __future__ import annotations

from datetime import time

from apps.personnel_actions.models import ActionAttribute, DataType

COST_CENTER_KEY = "cost_center"


def parse_time(raw) -> time | None:
    text = str(raw or "").strip()
    try:
        parts = [int(x) for x in text.split(":")]
        if len(parts) not in (2, 3):
            return None
        return time(*parts)
    except (TypeError, ValueError):
        return None


def _activity_prefixes(attr: ActionAttribute) -> list[str]:
    return [str(x).upper() for x in (attr.choices or []) if isinstance(x, str) and x.strip() and not x.startswith("!")]


def _activity_excluded(attr: ActionAttribute) -> list[str]:
    return [str(x)[1:].upper() for x in (attr.choices or []) if isinstance(x, str) and x.startswith("!")]


def activity_queryset(attr: ActionAttribute):
    from apps.adherence.models import ActivityType

    qs = ActivityType.objects.filter(is_active=True, system_role="").order_by("name")
    prefixes = _activity_prefixes(attr)
    if prefixes:
        from django.db.models import Q

        cond = Q()
        for p in prefixes:
            cond |= Q(code__startswith=p) if p.endswith("_") else Q(code=p)
        qs = qs.filter(cond)
    excluded = _activity_excluded(attr)
    return qs.exclude(code__in=excluded) if excluded else qs


def roster_attribute(code: str):
    from apps.roster.models import RosterAttribute

    return RosterAttribute.objects.filter(code=code, is_active=True).select_related("dimension").first()


def options_for(attr: ActionAttribute) -> list[dict]:
    """Opciones que ve el formulario (CHOICE fijas; ACTIVITY y ROSTER desde los catálogos vivos)."""
    if attr.data_type == DataType.ACTIVITY:
        return [{"value": a.code, "label": a.name, "paid": a.is_paid} for a in activity_queryset(attr)]
    if attr.data_type == DataType.ROSTER:
        if attr.key == COST_CENTER_KEY:
            from apps.common.models import CostCenter

            return [{"value": c.code, "label": f"{c.code} · {c.name}", "country": c.country.country_code}
                    for c in CostCenter.objects.filter(is_active=True).select_related("country").order_by("code")]
        ra = roster_attribute(attr.key)
        if ra is None:
            return []
        if ra.data_type == "CHOICE":
            return [{"value": c, "label": c} for c in ra.choices]
        if ra.data_type == "DIMENSION":
            from apps.roster.models import RosterDimensionItem

            items = RosterDimensionItem.objects.filter(dimension_id=ra.dimension_id, is_active=True).select_related("country", "parent")
            return [{"value": i.code, "label": i.name + (f" ({i.parent.name})" if i.parent_id else ""),
                     "country": i.country.country_code if i.country_id else None,
                     "parent": i.parent.code if i.parent_id else None} for i in items.order_by("name")]
        return []
    return attr.option_list()


def input_kind(attr: ActionAttribute) -> str | None:
    """Para ROSTER: cómo se captura (select | text | date)."""
    if attr.data_type != DataType.ROSTER:
        return None
    if attr.key == COST_CENTER_KEY:
        return "select"
    ra = roster_attribute(attr.key)
    if ra is None:
        return "text"
    return {"DIMENSION": "select", "CHOICE": "select", "DATE": "date", "BOOLEAN": "boolean"}.get(ra.data_type, "text")


def coerce(attr: ActionAttribute, raw, *, employee, where: str, check):
    """Valor canónico (texto) de TIME / ACTIVITY / ROSTER, o None con el error agregado en `check`."""
    text = str(raw).strip()
    if attr.data_type == DataType.TIME:
        t = parse_time(text)
        if t is None:
            check.error(where, f"«{attr.label}»: hora inválida (HH:MM o HH:MM:SS, 24 h).")
            return None
        return t.strftime("%H:%M:%S")
    if attr.data_type == DataType.ACTIVITY:
        a = activity_queryset(attr).filter(code=text.upper()).first()
        if a is None:
            check.error(where, f"«{attr.label}»: «{text}» no es una actividad permitida para este tipo de AP.", "invalid_choice")
            return None
        return a.code
    if attr.data_type == DataType.ROSTER:
        if attr.key == COST_CENTER_KEY:
            from apps.common.models import CostCenter

            c = CostCenter.objects.filter(code__iexact=text, is_active=True).first()
            if c is None:
                check.error(where, f"«{attr.label}»: el centro de costos «{text}» no existe o está inactivo.", "invalid_choice")
                return None
            if employee is not None and c.country_id != employee.country_id:
                check.error(where, f"«{attr.label}»: el centro de costos {c.code} es de otro país.", "wrong_country")
                return None
            return c.code
        ra = roster_attribute(attr.key)
        if ra is None:
            check.error(where, f"«{attr.label}»: «{attr.key}» no es un atributo activo del roster. Corríjalo en /admin/.", "config")
            return None
        from apps.roster.services import RosterValueError, coerce as roster_coerce

        try:
            canonical, _item, _label = roster_coerce(ra, text, country_id=employee.country_id if employee else None)
        except RosterValueError as exc:
            check.error(where, f"«{attr.label}»: {exc.message}", exc.code)
            return None
        return canonical
    return raw


def display(attr: ActionAttribute, value) -> str:
    if value in (None, ""):
        return "—"
    if attr.data_type == DataType.TIME:
        return str(value)[:8]
    if attr.data_type == DataType.ACTIVITY:
        from apps.adherence.models import ActivityType

        a = ActivityType.objects.filter(code=value).first()
        return a.name if a else str(value)
    if attr.data_type == DataType.ROSTER:
        option = next((o for o in options_for(attr) if o["value"] == value), None)
        return option["label"] if option else str(value)
    return str(value)
