"""Motor de horarios (funciones puras, sin base de datos).

Conceptos
---------
* **Turno (definición JSON)**: jornada por día de la semana::

      {
        "days": {
          "mon": {"start": "22:00", "end": "06:00", "lunch_minutes": 30},
          "tue": {...}, ..., "sat": null, "sun": null       # null / ausente = descanso
        },
        "lunch_allocation": "PROPORTIONAL"                   # opcional
      }

  `lunch_minutes` es SOLO la duración asignada al almuerzo (p. ej. 30 o 60). La hora exacta del
  almuerzo NO pertenece al turno base: la programa WFM en la operación. Por eso se rechazan claves
  como `lunch_start`. Si `end` <= `start`, la jornada cruza la medianoche.

* **Instancia de turno**: la jornada concreta de una fecha de turno (`shift_date`, el día en que inicia).
* **Fecha de ocurrencia**: el día calendario en que efectivamente transcurren las horas. Una jornada
  22:00–06:00 del lunes aporta 2 h al lunes y 6 h al martes; ambas porciones conservan la misma
  `shift_date` (trazabilidad: es UN turno, no dos).
* **Almuerzo en jornadas que cruzan medianoche**: como su hora no se conoce, la duración se reparte
  entre las fechas de ocurrencia según `lunch_allocation`:
    PROPORTIONAL     proporcional a los minutos de cada fecha (predeterminado);
    START_DAY        se descuenta en la fecha de inicio del turno (el excedente pasa al día siguiente);
    LONGEST_SEGMENT  se descuenta en la fecha con más minutos.
* **Nocturnidad**: ventana [inicio, fin) parametrizable por país (p. ej. 19:00–06:00); los minutos
  nocturnos de cada porción se calculan contra la regla vigente en su fecha de ocurrencia.
* **Bloques (Fase 10)**: un día puede tener VARIOS bloques (turno partido 08:00–12:00 + 14:00–18:00)::

      "mon": [{"start": "08:00", "end": "12:00"}, {"start": "14:00", "end": "18:00"}]

  Un objeto solo (formato anterior) equivale a un bloque. El almuerzo es opcional por bloque (0 si se
  omite); las reglas de almuerzo por país (`LunchRule`) indican desde cuántos minutos de jornada continua
  corresponde un almuerzo mínimo (advertencia u obligatorio). Ningún bloque puede traslaparse con otro de
  la semana (incluidos los que cruzan la medianoche).
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Callable, Iterable

DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_LABELS = {
    "mon": "lunes", "tue": "martes", "wed": "miércoles", "thu": "jueves",
    "fri": "viernes", "sat": "sábado", "sun": "domingo",
}
DAY_ALIASES = {
    "lunes": "mon", "martes": "tue", "miercoles": "wed", "miércoles": "wed", "jueves": "thu",
    "viernes": "fri", "sabado": "sat", "sábado": "sat", "domingo": "sun",
    "monday": "mon", "tuesday": "tue", "wednesday": "wed", "thursday": "thu", "friday": "fri",
    "saturday": "sat", "sunday": "sun",
}
LUNCH_ALLOCATIONS = {
    "PROPORTIONAL": "Proporcional a las horas de cada fecha",
    "START_DAY": "En la fecha de inicio del turno",
    "LONGEST_SEGMENT": "En la fecha con más horas",
}
DEFAULT_LUNCH_ALLOCATION = "PROPORTIONAL"
MAX_LUNCH_MINUTES = 240
DAY_ALLOWED_KEYS = {"start", "end", "lunch_minutes", "day_minutes", "night_minutes"}  # day/night: calculados (AP)
LUNCH_SCHEDULE_KEYS = {"lunch_start", "lunch_end", "lunch_time", "lunch_at", "lunch_from", "lunch_to", "break_start", "break_end"}
TOP_ALLOWED_KEYS = {"days", "lunch_allocation"}
_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)(?::00)?$")
MINUTES_PER_DAY = 1440
MAX_BLOCKS_PER_DAY = 4


class DefinitionError(Exception):
    """Errores de la definición JSON del turno: lista de {field, message}."""

    def __init__(self, errors: list[dict]):
        super().__init__("; ".join(e["message"] for e in errors))
        self.errors = errors


def parse_hhmm(value) -> time | None:
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    match = _HHMM.match(str(value or "").strip())
    if not match:
        return None
    return time(int(match.group(1)), int(match.group(2)))


def hhmm(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def minutes_of(t: time) -> int:
    return t.hour * 60 + t.minute


def fmt_minutes(total: int) -> str:
    sign = "-" if total < 0 else ""
    total = abs(int(total))
    return f"{sign}{total // 60}:{total % 60:02d}"


@dataclass(frozen=True)
class DaySpec:
    start: time
    end: time
    lunch_minutes: int = 0

    @property
    def crosses_midnight(self) -> bool:
        return minutes_of(self.end) <= minutes_of(self.start)

    @property
    def gross_minutes(self) -> int:
        diff = minutes_of(self.end) - minutes_of(self.start)
        return diff if diff > 0 else diff + MINUTES_PER_DAY

    @property
    def net_minutes(self) -> int:
        return self.gross_minutes - self.lunch_minutes

    def as_dict(self) -> dict:
        return {"start": hhmm(self.start), "end": hhmm(self.end), "lunch_minutes": self.lunch_minutes}


@dataclass(frozen=True)
class ShiftDefinition:
    days: dict  # day_key -> tuple[DaySpec, ...] (tupla vacía = descanso); bloques ordenados por hora de inicio
    lunch_allocation: str = DEFAULT_LUNCH_ALLOCATION

    def blocks(self, key: str) -> tuple:
        return self.days.get(key) or ()

    def blocks_for(self, d: date) -> tuple:
        return self.blocks(DAY_KEYS[d.weekday()])

    @property
    def weekly_net_minutes(self) -> int:
        return sum(b.net_minutes for blocks in self.days.values() for b in (blocks or ()))

    @property
    def working_days(self) -> int:
        return sum(1 for blocks in self.days.values() if blocks)

    @property
    def crosses_midnight(self) -> bool:
        return any(b.crosses_midnight for blocks in self.days.values() for b in (blocks or ()))

    @property
    def has_split_days(self) -> bool:
        return any(len(blocks or ()) > 1 for blocks in self.days.values())

    def as_json(self) -> dict:
        return {
            "days": {k: ([b.as_dict() for b in self.blocks(k)] or None) for k in DAY_KEYS},
            "lunch_allocation": self.lunch_allocation,
        }


def day_blocks_raw(spec) -> list | None:
    """Valor JSON de un día -> lista de bloques (None = descanso). Acepta un objeto (un bloque) o una lista."""
    if spec in (None, False, {}, [], "REST", "rest"):
        return None
    if isinstance(spec, dict):
        return [spec]
    if isinstance(spec, list):
        return spec
    return spec  # tipo inválido: lo reporta parse_definition


def _parse_block(spec, where: str, label: str, errors: list[dict]) -> DaySpec | None:
    if not isinstance(spec, dict):
        errors.append({"field": where, "message": f"{label}: cada bloque debe ser un objeto {{start, end, lunch_minutes}}."})
        return None
    lunch_schedule = sorted(set(spec) & LUNCH_SCHEDULE_KEYS)
    if lunch_schedule:
        errors.append({"field": f"{where}.{lunch_schedule[0]}", "message": (
            f"{label}: el horario solo define la DURACIÓN del almuerzo («lunch_minutes»); "
            "la hora exacta del almuerzo la programa WFM en la operación."
        )})
    for extra in sorted(set(spec) - DAY_ALLOWED_KEYS - LUNCH_SCHEDULE_KEYS):
        errors.append({"field": f"{where}.{extra}", "message": f"{label}: clave «{extra}» no reconocida (use start, end, lunch_minutes, day_minutes y night_minutes)."})
    start, end = parse_hhmm(spec.get("start")), parse_hhmm(spec.get("end"))
    if start is None:
        errors.append({"field": f"{where}.start", "message": f"{label}: la hora de entrada debe tener el formato HH:MM (24 h)."})
    if end is None:
        errors.append({"field": f"{where}.end", "message": f"{label}: la hora de salida debe tener el formato HH:MM (24 h)."})
    lunch = spec.get("lunch_minutes", 0)
    if lunch in (None, ""):
        lunch = 0  # el almuerzo NO es obligatorio: lo exige (o sugiere) la regla de almuerzo del país
    try:
        lunch_int = int(lunch)
        if isinstance(lunch, bool) or float(lunch) != lunch_int:
            raise ValueError
    except (TypeError, ValueError):
        errors.append({"field": f"{where}.lunch_minutes", "message": f"{label}: «lunch_minutes» debe ser un número entero de minutos (p. ej. 0, 30 o 60)."})
        return None
    if not 0 <= lunch_int <= MAX_LUNCH_MINUTES:
        errors.append({"field": f"{where}.lunch_minutes", "message": f"{label}: el almuerzo debe durar entre 0 y {MAX_LUNCH_MINUTES} minutos."})
        return None
    if start is None or end is None:
        return None
    if start == end:
        errors.append({"field": f"{where}.end", "message": f"{label}: la entrada y la salida no pueden ser la misma hora."})
        return None
    block = DaySpec(start, end, lunch_int)
    if lunch_int >= block.gross_minutes:
        errors.append({"field": f"{where}.lunch_minutes", "message": (
            f"{label}: el almuerzo ({lunch_int} min) no puede ser igual o mayor que la jornada ({fmt_minutes(block.gross_minutes)} h)."
        )})
        return None
    return block


def _block_label(key: str, index: int, count: int) -> str:
    return f"El {DAY_LABELS[key]}" + (f" (bloque {index + 1})" if count > 1 else "")


def parse_definition(raw) -> ShiftDefinition:
    """Valida y normaliza la definición JSON del horario. Lanza DefinitionError con todos los problemas."""
    errors: list[dict] = []
    if not isinstance(raw, dict):
        raise DefinitionError([{"field": "definition", "message": 'La definición del horario debe ser un objeto JSON con la clave "days".'}])
    for key in raw:
        if key not in TOP_ALLOWED_KEYS:
            errors.append({"field": f"definition.{key}", "message": f"Clave «{key}» no reconocida (use «days» y opcionalmente «lunch_allocation»)."})
    allocation = str(raw.get("lunch_allocation") or DEFAULT_LUNCH_ALLOCATION).strip().upper()
    if allocation not in LUNCH_ALLOCATIONS:
        errors.append({"field": "definition.lunch_allocation",
                       "message": f"«lunch_allocation» debe ser uno de: {', '.join(LUNCH_ALLOCATIONS)}."})
    days_raw = raw.get("days")
    if not isinstance(days_raw, dict):
        errors.append({"field": "definition.days", "message": 'Falta «days»: un objeto con la jornada por día de la semana (mon … sun).'})
        raise DefinitionError(errors)

    days: dict[str, tuple] = {k: () for k in DAY_KEYS}
    seen: set[str] = set()
    for raw_key, spec in days_raw.items():
        key = DAY_ALIASES.get(str(raw_key).strip().lower(), str(raw_key).strip().lower())
        where = f"definition.days.{raw_key}"
        if key not in DAY_KEYS:
            errors.append({"field": where, "message": f"«{raw_key}» no es un día de la semana (use mon, tue, wed, thu, fri, sat, sun)."})
            continue
        if key in seen:
            errors.append({"field": where, "message": f"El {DAY_LABELS[key]} está definido dos veces."})
            continue
        seen.add(key)
        blocks_raw = day_blocks_raw(spec)
        if blocks_raw is None:
            continue
        if not isinstance(blocks_raw, list):
            errors.append({"field": where, "message": (
                f"La jornada del {DAY_LABELS[key]} debe ser un objeto {{start, end, lunch_minutes}}, una lista de bloques o null (descanso)."
            )})
            continue
        if len(blocks_raw) > MAX_BLOCKS_PER_DAY:
            errors.append({"field": where, "message": f"El {DAY_LABELS[key]} admite como máximo {MAX_BLOCKS_PER_DAY} bloques."})
            continue
        single = isinstance(spec, dict)
        parsed = []
        for index, block_raw in enumerate(blocks_raw):
            block = _parse_block(block_raw, where if single else f"{where}.{index}", _block_label(key, index, len(blocks_raw)), errors)
            if block is not None:
                parsed.append(block)
        days[key] = tuple(sorted(parsed, key=lambda b: minutes_of(b.start)))

    if not errors and not any(days.values()):
        errors.append({"field": "definition.days", "message": "El horario debe tener al menos un día laboral."})

    # Ningún bloque puede pisar a otro (mismo día, o la jornada que cruza la medianoche contra el día siguiente).
    if not errors:
        conflict = first_block_overlap(days)
        if conflict:
            errors.append(conflict)
    if errors:
        raise DefinitionError(errors)
    return ShiftDefinition(days, allocation)


def first_block_overlap(days: dict) -> dict | None:
    week = 7 * MINUTES_PER_DAY
    intervals = []
    for index, key in enumerate(DAY_KEYS):
        blocks = days.get(key) or ()
        for bi, b in enumerate(blocks):
            s = index * MINUTES_PER_DAY + minutes_of(b.start)
            intervals.append((s, s + b.gross_minutes, key, bi, len(blocks), b))
    intervals.sort(key=lambda t: t[0])
    n = len(intervals)
    if n < 2:
        return None
    for i in range(n):
        a, b = intervals[i], intervals[(i + 1) % n]
        b_start = b[0] + (week if i + 1 == n else 0)
        if a[1] > b_start:
            return {"field": f"definition.days.{b[2]}.start", "message": (
                f"{_block_label(a[2], a[3], a[4])} ({hhmm(a[5].start)}–{hhmm(a[5].end)}) se traslapa con "
                f"{_block_label(b[2], b[3], b[4]).replace('El ', 'el ', 1)} ({hhmm(b[5].start)}–{hhmm(b[5].end)}): los bloques no pueden cruzarse."
            )}
    return None


# ---------------------------------------------------------------- nocturnidad
@dataclass(frozen=True)
class NightWindow:
    start: time
    end: time
    surcharge_percent: float = 0.0
    rule_id: int | None = None
    name: str = ""

    def intervals_on(self, d: date) -> list[tuple[datetime, datetime]]:
        day0 = datetime.combine(d, time())
        s, e = minutes_of(self.start), minutes_of(self.end)
        if s < e:
            return [(day0 + timedelta(minutes=s), day0 + timedelta(minutes=e))]
        # Cruza la medianoche (19:00–06:00): dentro de un día calendario son dos tramos.
        return [(day0, day0 + timedelta(minutes=e)), (day0 + timedelta(minutes=s), day0 + timedelta(days=1))]


NightLookup = Callable[[date], "NightWindow | None"]


def _overlap(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> int:
    start, end = max(a0, b0), min(a1, b1)
    return int((end - start).total_seconds() // 60) if end > start else 0


def night_minutes(start: datetime, end: datetime, window: NightWindow | None) -> int:
    """Minutos de [start, end) dentro de la ventana nocturna (el tramo debe estar dentro de un solo día)."""
    if window is None or end <= start:
        return 0
    return sum(_overlap(start, end, w0, w1) for w0, w1 in window.intervals_on(start.date()))


# ---------------------------------------------------------------- división por día de ocurrencia
@dataclass
class Segment:
    occurrence_date: date
    start: datetime | None
    end: datetime | None
    gross_minutes: int
    night_gross_minutes: int = 0
    lunch_minutes: int = 0
    night_rule_id: int | None = None
    surcharge_percent: float = 0.0

    @property
    def net_minutes(self) -> int:
        return self.gross_minutes - self.lunch_minutes

    @property
    def night_net_minutes(self) -> int:
        if not self.gross_minutes or not self.lunch_minutes:
            return self.night_gross_minutes
        # La hora del almuerzo no se conoce: se descuenta de la parte nocturna en la misma proporción.
        return round(self.night_gross_minutes * self.net_minutes / self.gross_minutes)

    def as_dict(self) -> dict:
        return {
            "occurrence_date": self.occurrence_date.isoformat(),
            "start": self.start.isoformat(timespec="minutes") if self.start else None,
            "end": self.end.isoformat(timespec="minutes") if self.end else None,
            "gross_minutes": self.gross_minutes,
            "lunch_minutes": self.lunch_minutes,
            "minutes": self.net_minutes,
            "night_minutes": self.night_net_minutes,
            "surcharge_percent": self.surcharge_percent,
        }


def split_by_calendar_day(start: datetime, end: datetime) -> list[tuple[date, datetime, datetime]]:
    """[start, end) partido en la medianoche: una porción por día calendario de ocurrencia."""
    if end <= start:
        raise ValueError("La salida debe ser posterior a la entrada.")
    parts = []
    cursor = start
    while cursor < end:
        midnight = datetime.combine(cursor.date() + timedelta(days=1), time())
        part_end = min(end, midnight)
        parts.append((cursor.date(), cursor, part_end))
        cursor = part_end
    return parts


def allocate_lunch(lengths: list[int], lunch: int, mode: str = DEFAULT_LUNCH_ALLOCATION) -> list[int]:
    """Reparte la duración del almuerzo entre las porciones del turno (nunca más que su duración)."""
    if not lengths:
        return []
    lunch = max(0, min(int(lunch), sum(lengths)))
    result = [0] * len(lengths)
    if not lunch:
        return result
    if mode == "PROPORTIONAL":
        total = sum(lengths)
        for i, length in enumerate(lengths):
            result[i] = min(length, (lunch * length) // total)
        remainder = lunch - sum(result)
        # Los minutos sobrantes del redondeo van a las porciones más largas.
        for i in sorted(range(len(lengths)), key=lambda j: (-lengths[j], j)):
            if not remainder:
                break
            take = min(remainder, lengths[i] - result[i])
            result[i] += take
            remainder -= take
        return result
    order = list(range(len(lengths)))
    if mode == "LONGEST_SEGMENT":
        order.sort(key=lambda j: (-lengths[j], j))
    remaining = lunch
    for i in order:
        take = min(remaining, lengths[i])
        result[i] = take
        remaining -= take
        if not remaining:
            break
    return result


def segments_for_interval(start: datetime, end: datetime, *, lunch_minutes: int = 0,
                          lunch_allocation: str = DEFAULT_LUNCH_ALLOCATION,
                          night_lookup: NightLookup | None = None) -> list[Segment]:
    parts = split_by_calendar_day(start, end)
    lengths = [int((e - s).total_seconds() // 60) for _, s, e in parts]
    lunches = allocate_lunch(lengths, lunch_minutes, lunch_allocation)
    segments = []
    for (d, s, e), length, lunch in zip(parts, lengths, lunches):
        window = night_lookup(d) if night_lookup else None
        segments.append(Segment(
            occurrence_date=d, start=s, end=e, gross_minutes=length, lunch_minutes=lunch,
            night_gross_minutes=night_minutes(s, e, window),
            night_rule_id=window.rule_id if window else None,
            surcharge_percent=float(window.surcharge_percent) if window else 0.0,
        ))
    return segments


@dataclass
class ShiftInstance:
    shift_date: date
    start: datetime
    end: datetime
    lunch_minutes: int
    segments: list[Segment] = field(default_factory=list)
    shift_code: str = ""
    shift_name: str = ""
    assignment_id: int | None = None
    block: int = 0
    mode: str = ""

    @property
    def net_minutes(self) -> int:
        return sum(s.net_minutes for s in self.segments)

    def as_dict(self) -> dict:
        return {
            "shift_date": self.shift_date.isoformat(),
            "shift_code": self.shift_code,
            "shift_name": self.shift_name,
            "assignment_id": self.assignment_id,
            "block": self.block,
            "mode": self.mode,
            "start": self.start.isoformat(timespec="minutes"),
            "end": self.end.isoformat(timespec="minutes"),
            "crosses_midnight": self.start.date() != self.end.date() and self.end != datetime.combine(self.end.date(), time()),
            "lunch_minutes": self.lunch_minutes,
            "minutes": self.net_minutes,
            "segments": [s.as_dict() for s in self.segments],
        }


def shift_instances(definition: ShiftDefinition, shift_date: date, *, night_lookup: NightLookup | None = None) -> list[ShiftInstance]:
    """Jornadas concretas (una por bloque) que INICIAN en `shift_date`."""
    out = []
    for index, spec in enumerate(definition.blocks_for(shift_date)):
        start = datetime.combine(shift_date, spec.start)
        end = start + timedelta(minutes=spec.gross_minutes)
        out.append(ShiftInstance(
            shift_date=shift_date, start=start, end=end, lunch_minutes=spec.lunch_minutes, block=index,
            segments=segments_for_interval(start, end, lunch_minutes=spec.lunch_minutes,
                                           lunch_allocation=definition.lunch_allocation, night_lookup=night_lookup),
        ))
    return out


def first_instance_collision(a: list[ShiftInstance], b: list[ShiftInstance]) -> tuple[ShiftInstance, ShiftInstance] | None:
    """Primer par de jornadas (de dos horarios distintos) que pide las mismas horas."""
    for x in a:
        for y in b:
            if x.start < y.end and y.start < x.end:
                return x, y
    return None


def date_range(start: date, end: date) -> Iterable[date]:
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


# ---------------------------------------------------------------- ciclos de pago y cortes
PERIOD_RULES = {
    "HALF_MONTH": "Quincenal (dos periodos por mes; admite cortes que cruzan de mes, p. ej. 10–24 y 25–9)",
    "MONTH": "Mensual (del día de inicio al día anterior del mes siguiente)",
    "FIXED_DAYS": "Bloques de N días desde una fecha ancla (semanal = 7, catorcenal = 14)",
}


@dataclass(frozen=True)
class CycleRule:
    period_rule: str
    first_half_end_day: int = 15
    length_days: int | None = None
    anchor_date: date | None = None
    cutoff_lag_days: int = 0
    payment_lag_days: int = 0
    period_start_day: int = 1  # día del mes en que inicia el primer periodo (1 = calendario; 10 = cortes BPO 10–24 / 25–9)


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _next_month(y: int, m: int) -> tuple[int, int]:
    return (y + 1, 1) if m == 12 else (y, m + 1)


def describe_rule(rule: CycleRule) -> str:
    """Texto legible de la regla (p. ej. «Del 10 al 24 y del 25 al 9 del mes siguiente»)."""
    a = rule.period_start_day or 1
    if rule.period_rule == "HALF_MONTH":
        b = rule.first_half_end_day
        second = "fin de mes" if a == 1 else f"{a - 1} del mes siguiente"
        return f"Del {a} al {b} y del {b + 1} al {second}"
    if rule.period_rule == "MONTH":
        return "Mes calendario" if a == 1 else f"Del {a} al {a - 1} del mes siguiente"
    if rule.period_rule == "FIXED_DAYS":
        return f"Bloques de {rule.length_days} días desde el {rule.anchor_date:%d/%m/%Y}" if rule.anchor_date else f"Bloques de {rule.length_days} días"
    return rule.period_rule


def _periods_between(rule: CycleRule, start: date, end: date) -> list[tuple[date, date, str]]:
    """Periodos (inicio, fin, etiqueta) que INICIAN dentro de [start, end].

    Quincenal / mensual con `period_start_day` > 1: los periodos cruzan de un mes al siguiente (cortes BPO).
    La etiqueta usa el mes en que INICIA el periodo (2026-11-Q2 = del 25/11 al 09/12).
    """
    out = []
    a = rule.period_start_day or 1
    if rule.period_rule == "MONTH":
        y, m = start.year, start.month
        while date(y, m, 1) <= end:
            ny, nm = _next_month(y, m)
            p_start = date(y, m, a)
            p_end = _month_end(y, m) if a == 1 else date(ny, nm, a) - timedelta(days=1)
            if start <= p_start <= end:
                out.append((p_start, p_end, f"{y}-{m:02d}"))
            y, m = ny, nm
    elif rule.period_rule == "HALF_MONTH":
        split = rule.first_half_end_day
        y, m = start.year, start.month
        while date(y, m, 1) <= end:
            ny, nm = _next_month(y, m)
            month_end = _month_end(y, m)
            mid = date(y, m, min(split, month_end.day - 1))
            q2_end = month_end if a == 1 else date(ny, nm, a) - timedelta(days=1)
            for p_start, p_end, half in ((date(y, m, a), mid, "Q1"), (mid + timedelta(days=1), q2_end, "Q2")):
                if start <= p_start <= end:
                    out.append((p_start, p_end, f"{y}-{m:02d}-{half}"))
            y, m = ny, nm
    elif rule.period_rule == "FIXED_DAYS":
        length, anchor = rule.length_days, rule.anchor_date
        offset = (start - anchor).days
        n = -(-offset // length) if offset > 0 else -((-offset) // length)
        p_start = anchor + timedelta(days=n * length)
        while p_start < start:
            p_start += timedelta(days=length)
        while p_start <= end:
            out.append((p_start, p_start + timedelta(days=length - 1), ""))
            p_start += timedelta(days=length)
    else:
        raise ValueError(f"Regla de periodo desconocida: {rule.period_rule}")
    return out


def generate_periods(rule: CycleRule, year: int) -> list[dict]:
    """Periodos de pago del año con su corte operativo interno.

    Corte interno: la asistencia de un periodo se cierra `cutoff_lag_days` días ANTES de que termine el
    periodo. La ventana de asistencia (cutoff_start–cutoff_end) va del día siguiente al corte anterior
    hasta el corte actual, de modo que las ventanas son contiguas y no se traslapan
    (p. ej. quincena 16–30 nov con corte 5 días antes: asistencia del 11 al 25 de noviembre).
    """
    first, last = date(year, 1, 1), date(year, 12, 31)
    previous = _periods_between(rule, first - timedelta(days=62), first - timedelta(days=1))
    periods = _periods_between(rule, first, last)
    prev_end = previous[-1][1] if previous else first - timedelta(days=1)
    lag = timedelta(days=rule.cutoff_lag_days)
    out = []
    week_counter = 0
    for p_start, p_end, label in periods:
        week_counter += 1
        out.append({
            "label": label or f"{p_start.year}-P{week_counter:02d}",
            "period_start": p_start,
            "period_end": p_end,
            "cutoff_start": prev_end - lag + timedelta(days=1),
            "cutoff_end": p_end - lag,
            "payment_date": p_end + timedelta(days=rule.payment_lag_days),
        })
        prev_end = p_end
    return out


# ---------------------------------------------------------------- horario atómico por día (formato AP)
REFERENCE_MONDAY = date(2001, 1, 1)  # lunes de referencia para calcular la jornada de cada día de la semana


def _block_breakdown(spec: DaySpec, index: int, day_index: int, allocation: str, window: NightWindow | None) -> dict:
    start = datetime.combine(REFERENCE_MONDAY + timedelta(days=day_index), spec.start)
    segments = segments_for_interval(start, start + timedelta(minutes=spec.gross_minutes), lunch_minutes=spec.lunch_minutes,
                                     lunch_allocation=allocation, night_lookup=(lambda _d: window) if window else None)
    night = sum(s.night_net_minutes for s in segments)
    return {**spec.as_dict(), "block": index, "day_minutes": spec.net_minutes - night, "night_minutes": night,
            "net_minutes": spec.net_minutes, "gross_minutes": spec.gross_minutes, "crosses_midnight": spec.crosses_midnight}


def day_breakdown(definition: ShiftDefinition, window: NightWindow | None) -> dict[str, dict | None]:
    """Por día de la semana: bloques (entrada, salida, almuerzo) y horas DIURNAS / NOCTURNAS programadas.

    Es el formato de una Acción de Personal: cada día se especifica de forma explícita y puede tener varios
    bloques (turno partido); los totales del día SUMAN todos sus bloques. Las horas nocturnas se calculan con la
    ventana de nocturnidad del país vigente a la fecha efectiva (todo el bloque, aunque cruce la medianoche).
    """
    out: dict[str, dict | None] = {}
    for index, key in enumerate(DAY_KEYS):
        blocks = definition.blocks(key)
        if not blocks:
            out[key] = None
            continue
        rows = [_block_breakdown(b, i, index, definition.lunch_allocation, window) for i, b in enumerate(blocks)]
        out[key] = {
            "blocks": rows,
            "start": rows[0]["start"], "end": rows[-1]["end"],
            "lunch_minutes": sum(r["lunch_minutes"] for r in rows),
            "day_minutes": sum(r["day_minutes"] for r in rows),
            "night_minutes": sum(r["night_minutes"] for r in rows),
            "net_minutes": sum(r["net_minutes"] for r in rows),
            "gross_minutes": sum(r["gross_minutes"] for r in rows),
            "crosses_midnight": any(r["crosses_midnight"] for r in rows),
        }
    return out


ANNOTATED_KEYS = ("start", "end", "lunch_minutes", "day_minutes", "night_minutes")


def annotated_json(definition: ShiftDefinition, window: NightWindow | None) -> dict:
    """JSON canónico del horario: cada día es una LISTA de bloques con day_minutes / night_minutes (o null)."""
    breakdown = day_breakdown(definition, window)
    return {
        "days": {k: ([{kk: b[kk] for kk in ANNOTATED_KEYS} for b in v["blocks"]] if v else None) for k, v in breakdown.items()},
        "lunch_allocation": definition.lunch_allocation,
    }


def check_declared_hours(raw: dict, breakdown: dict) -> list[dict]:
    """Si la AP declara horas diurnas / nocturnas por bloque, deben coincidir con el cálculo (regla vigente)."""
    errors = []
    days = (raw or {}).get("days") or {} if isinstance(raw, dict) else {}
    for raw_key, spec in days.items():
        key = DAY_ALIASES.get(str(raw_key).strip().lower(), str(raw_key).strip().lower())
        calc = breakdown.get(key)
        blocks_raw = day_blocks_raw(spec)
        if not calc or not isinstance(blocks_raw, list):
            continue
        by_start = {b["start"]: b for b in calc["blocks"]}
        for index, block_raw in enumerate(blocks_raw):
            start = parse_hhmm(block_raw.get("start")) if isinstance(block_raw, dict) else None
            calc_block = by_start.get(hhmm(start)) if start else None
            if not calc_block:
                continue
            where = f"definition.days.{raw_key}" + ("" if isinstance(spec, dict) else f".{index}")
            for name, label in (("day_minutes", "diurnas"), ("night_minutes", "nocturnas")):
                if block_raw.get(name) in (None, ""):
                    continue
                try:
                    declared = int(block_raw[name])
                except (TypeError, ValueError):
                    declared = None
                if declared != calc_block[name]:
                    errors.append({"field": f"{where}.{name}", "message": (
                        f"{_block_label(key, calc_block['block'], len(calc['blocks']))}: las horas {label} declaradas ({block_raw[name]} min) "
                        f"no coinciden con el cálculo según la regla de nocturnidad vigente "
                        f"({fmt_minutes(calc_block[name])} h = {calc_block[name]} min)."
                    )})
    return errors


# ---------------------------------------------------------------- reglas de almuerzo por país
LUNCH_ENFORCEMENT = {"WARN": "Advertencia (no bloquea)", "REQUIRE": "Obligatorio (bloquea la AP)"}


@dataclass(frozen=True)
class LunchRule:
    """A partir de `min_block_minutes` de jornada CONTINUA (bloque) corresponde al menos `lunch_minutes` de almuerzo."""

    min_block_minutes: int
    lunch_minutes: int
    enforcement: str = "WARN"
    name: str = ""
    rule_id: int | None = None


def lunch_rule_for(minutes: int, rules: Iterable[LunchRule]) -> LunchRule | None:
    """El tramo con el umbral más alto que la jornada alcanza."""
    best = None
    for r in rules:
        if r.min_block_minutes <= minutes and (best is None or r.min_block_minutes > best.min_block_minutes):
            best = r
    return best


def check_lunch(definition: ShiftDefinition, rules: Iterable[LunchRule]) -> tuple[list[dict], list[dict]]:
    """(errores, advertencias) de almuerzo. El almuerzo no es fijo: solo se exige / sugiere cuando un bloque
    continuo alcanza el umbral del país. Un turno partido (08–12 + 14–18) no necesita almuerzo: el corte
    entre bloques ya es el descanso."""
    rules = list(rules)
    errors, warnings = [], []
    if not rules:
        return errors, warnings
    for key in DAY_KEYS:
        blocks = definition.blocks(key)
        for index, b in enumerate(blocks):
            rule = lunch_rule_for(b.gross_minutes, rules)
            if rule is None or b.lunch_minutes >= rule.lunch_minutes:
                continue
            where = f"definition.days.{key}" + (f".{index}" if len(blocks) > 1 else "")
            message = (
                f"{_block_label(key, index, len(blocks))}: una jornada continua de {fmt_minutes(b.gross_minutes)} h "
                f"({hhmm(b.start)}–{hhmm(b.end)}) lleva al menos {rule.lunch_minutes} min de almuerzo según «{rule.name or 'regla de almuerzo'}»"
                f" (tiene {b.lunch_minutes} min)."
            )
            (errors if rule.enforcement == "REQUIRE" else warnings).append({"field": where, "message": message, "code": "lunch_rule"})
    return errors, warnings


_TEXT_DAYS = {"l": "mon", "m": "tue", "x": "wed", "mi": "wed", "j": "thu", "v": "fri", "s": "sat", "d": "sun",
              **{k: k for k in DAY_KEYS}, **DAY_ALIASES}
_TEXT_PART = re.compile(r"^\s*([A-Za-záéíóúÁÉÍÓÚ,\-]+)\s+(.+?)\s*$")
_TEXT_RANGE = re.compile(r"^\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})(?:\s+(\d{1,3}))?\s*$")
_TEXT_HELP = "Use DÍAS ENTRADA-SALIDA [ALMUERZO], p. ej. «L-V 08:00-17:00 60; S 08:00-12:00» o turno partido «L-V 08:00-12:00 + 14:00-18:00»."


def parse_schedule_text(text: str) -> dict:
    """Notación compacta para cargas masivas: «L-V 08:00-17:00 60; S 08:00-12:00».

    Días: L M X J V S D (o mon…sun / lunes…domingo), rangos «L-V» y listas «L,X,V». El número final de cada
    bloque son los minutos de almuerzo (opcional, 0 si se omite). Turno partido: varios bloques unidos con «+»
    («L-V 08:00-12:00 + 14:00-18:00») o el mismo día repetido en otra parte. Los días no mencionados son descanso.
    """
    days: dict[str, list] = {}
    parts = [p for p in re.split(r"[;\n]+", str(text or "")) if p.strip()]
    if not parts:
        raise DefinitionError([{"field": "definition", "message": "Indique el horario (p. ej. «L-V 08:00-17:00 60»)."}])
    for part in parts:
        match = _TEXT_PART.match(part)
        ranges = [_TEXT_RANGE.match(r) for r in match.group(2).split("+")] if match else [None]
        if not match or not all(ranges):
            raise DefinitionError([{"field": "definition", "message": f"No se entiende «{part.strip()}». {_TEXT_HELP}"}])
        keys: list[str] = []
        for item in match.group(1).lower().split(","):
            if "-" in item:
                a, b = (_TEXT_DAYS.get(x.strip()) for x in item.split("-", 1))
                if not a or not b:
                    raise DefinitionError([{"field": "definition", "message": f"Rango de días no válido: «{item}»."}])
                i, j = DAY_KEYS.index(a), DAY_KEYS.index(b)
                keys += [DAY_KEYS[(i + n) % 7] for n in range((j - i) % 7 + 1)]
            else:
                k = _TEXT_DAYS.get(item.strip())
                if not k:
                    raise DefinitionError([{"field": "definition", "message": f"Día no válido: «{item}» (use L M X J V S D)."}])
                keys.append(k)
        if len(set(keys)) != len(keys):
            raise DefinitionError([{"field": "definition", "message": f"Un día aparece dos veces en «{part.strip()}»."}])
        for k in keys:
            days.setdefault(k, []).extend(
                {"start": r.group(1), "end": r.group(2), "lunch_minutes": int(r.group(3) or 0)} for r in ranges
            )
    return {"days": {k: days.get(k) for k in DAY_KEYS}}


def coerce_schedule(value):
    """Acepta el JSON del horario (objeto o texto) o la notación compacta."""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{"):
            import json

            try:
                return json.loads(text)
            except ValueError:
                raise DefinitionError([{"field": "definition", "message": "El horario no es un JSON válido."}]) from None
        return parse_schedule_text(text)
    return value
