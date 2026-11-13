"""Motor de adherencia (Fase 16), sin acceso a la base de datos.

Cruza tres líneas de tiempo en hora LOCAL de la operación (datetime sin tzinfo, precisión de segundos):

* PLAN: los CONTENEDORES del turno (bloques entrada-salida del horario que creó la AP) y, dentro de ellos, los
  SEGMENTOS DE ACTIVIDAD que inserta WFM (Break, Almuerzo, Capacitación, Coaching…). El tiempo de un contenedor
  que no cubre ningún segmento es de la actividad predeterminada (producción).
* REAL: los segmentos de estado del ACD / Web Timer (estado primario + auxiliar). Offline no cuenta como sesión.
* JUSTIFICACIONES: ventanas respaldadas por una AP aprobada (permiso, incapacidad, misión oficial…).

Cada instante se clasifica así:

    plan  real  justificado  →  resultado
    sí    sí    —               EN ADHERENCIA si el estado está permitido en la actividad (auxiliar PRIMARIO = trabajo
                                principal; SECUNDARIO = auxiliar pagado por diseño del segmento); si no, OUT OF ADHERENCE
                                (salvo que esté justificado). Dentro del contenedor el tiempo en estado pagado es válido
                                para pago; para facturación (billing) además debe estar en adherencia y la actividad ser
                                facturable.
    sí    no    no              OUT OF ADHERENCE (programado y sin sesión), salvo actividades que no exigen sesión
                                (Fase 19: permisos RRHH, fallas de sistema, Legal Benefit Lunch): EN ADHERENCIA
    no    sí    no              UNPAID EXCESS LOGIN (sesión fuera de los contenedores): no se paga
    —     —     sí              JUSTIFICADO: no penaliza; se paga si la justificación es pagada

Adherencia % = tiempo en adherencia / (tiempo programado − tiempo programado justificado).
Conformidad % = tiempo con sesión dentro del contenedor / tiempo programado.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, datetime

PRIMARY_ROLE = "PRIMARY"
SECONDARY_ROLE = "SECONDARY"
OUT_OF_ADHERENCE = "OUT_OF_ADHERENCE"
UNPAID_EXCESS = "UNPAID_EXCESS_LOGIN"


@dataclass(frozen=True)
class StatusRule:
    primary: str  # código del estado primario (ON_QUEUE, BREAK…)
    aux: str | None  # código del auxiliar; None = cualquier auxiliar (o ninguno) de ese estado
    role: str  # PRIMARY (trabajo principal) | SECONDARY (auxiliar secundario pagado según diseño)


@dataclass(frozen=True)
class Activity:
    code: str
    name: str = ""
    is_paid: bool = True
    is_billable: bool = False
    rules: tuple[StatusRule, ...] = ()
    requires_login: bool = True  # Fase 19: False = se cumple sin sesión (permiso, falla de sistema, almuerzo legal)

    def match(self, state: Actual) -> str | None:
        """Rol con el que el estado real cumple la actividad (la regla con auxiliar gana a la genérica), o None."""
        generic = None
        for r in self.rules:
            if r.primary != state.primary:
                continue
            if r.aux is None:
                generic = generic or r.role
            elif r.aux in (state.aux, state.aux_parent):
                return r.role
        return generic


@dataclass(frozen=True)
class Container:
    shift_date: date
    start: datetime
    end: datetime
    label: str = ""


@dataclass(frozen=True)
class PlannedSegment:
    shift_date: date
    start: datetime
    end: datetime
    activity: str
    ref: int | None = None


@dataclass(frozen=True)
class PlanBlock:
    shift_date: date
    start: datetime
    end: datetime
    activity: str
    source: str  # SEGMENT | CONTAINER (relleno con la actividad predeterminada)
    ref: int | None = None


@dataclass(frozen=True)
class Actual:
    start: datetime
    end: datetime
    primary: str
    aux: str | None = None
    aux_parent: str | None = None
    paid: bool = True
    label: str = ""
    ref: int | None = None


@dataclass(frozen=True)
class Justification:
    start: datetime
    end: datetime
    is_paid: bool = True
    ref: int | None = None
    label: str = ""


@dataclass
class Deviation:
    kind: str
    day: date
    start: datetime
    end: datetime
    expected: str | None  # código de actividad (None en exceso de login)
    actual: Actual | None  # None = sin sesión

    @property
    def seconds(self) -> int:
        return int((self.end - self.start).total_seconds())


@dataclass
class DayTotals:
    day: date
    scheduled: int = 0
    scheduled_paid: int = 0
    in_adherence: int = 0
    out_of_adherence: int = 0
    justified: int = 0
    justified_scheduled: int = 0
    logged: int = 0
    logged_in_container: int = 0
    paid_valid: int = 0
    billable: int = 0
    primary_work: int = 0
    secondary_paid: int = 0
    unpaid_excess: int = 0

    @property
    def adherence_pct(self) -> float | None:
        base = self.scheduled - self.justified_scheduled
        return round(self.in_adherence * 100 / base, 2) if base > 0 else None

    @property
    def conformance_pct(self) -> float | None:
        return round(self.logged_in_container * 100 / self.scheduled, 2) if self.scheduled > 0 else None

    def as_dict(self) -> dict:
        out = {k: getattr(self, k) for k in (
            "scheduled", "scheduled_paid", "in_adherence", "out_of_adherence", "justified", "justified_scheduled", "logged",
            "logged_in_container", "paid_valid", "billable", "primary_work", "secondary_paid", "unpaid_excess")}
        return {"date": self.day.isoformat(), **out, "adherence_pct": self.adherence_pct, "conformance_pct": self.conformance_pct}


@dataclass
class Result:
    days: dict[date, DayTotals] = field(default_factory=dict)
    deviations: list[Deviation] = field(default_factory=list)
    plan: list[PlanBlock] = field(default_factory=list)
    actuals: list[Actual] = field(default_factory=list)
    justifications: list[Justification] = field(default_factory=list)

    def day(self, d: date) -> DayTotals:
        if d not in self.days:
            self.days[d] = DayTotals(d)
        return self.days[d]


# ---------------------------------------------------------------- plan
class PlanError(ValueError):
    pass


def segment_container(seg_start: datetime, seg_end: datetime, containers: list[Container]) -> Container | None:
    """El contenedor que incluye por completo al segmento (o None)."""
    return next((c for c in containers if c.start <= seg_start and seg_end <= c.end), None)


def build_plan(containers: list[Container], segments: list[PlannedSegment], default_activity: str) -> list[PlanBlock]:
    """Línea de tiempo programada: segmentos de WFM y, en los huecos de cada contenedor, la actividad predeterminada.

    Los segmentos fuera de todo contenedor o traslapados se rechazan (el servicio ya lo valida al guardarlos)."""
    containers = sorted(containers, key=lambda c: c.start)
    segments = sorted(segments, key=lambda s: s.start)
    for a, b in zip(containers, containers[1:]):
        if b.start < a.end:
            raise PlanError(f"Los contenedores del {a.shift_date:%d/%m/%Y} y del {b.shift_date:%d/%m/%Y} se traslapan.")
    for a, b in zip(segments, segments[1:]):
        if b.start < a.end:
            raise PlanError(f"Segmentos traslapados: {a.start:%d/%m %H:%M} y {b.start:%d/%m %H:%M}.")
    plan: list[PlanBlock] = []
    for c in containers:
        cursor = c.start
        for s in (s for s in segments if c.start <= s.start < c.end):
            if s.end > c.end:
                raise PlanError(f"El segmento de {s.start:%H:%M} a {s.end:%H:%M} sale del contenedor del turno.")
            if s.start > cursor:
                plan.append(PlanBlock(c.shift_date, cursor, s.start, default_activity, "CONTAINER"))
            plan.append(PlanBlock(c.shift_date, s.start, s.end, s.activity, "SEGMENT", s.ref))
            cursor = s.end
        if cursor < c.end:
            plan.append(PlanBlock(c.shift_date, cursor, c.end, default_activity, "CONTAINER"))
    for s in segments:
        if segment_container(s.start, s.end, containers) is None:
            raise PlanError(f"El segmento de {s.start:%d/%m %H:%M} a {s.end:%H:%M} no está dentro de un contenedor del turno.")
    return plan


# ---------------------------------------------------------------- evaluación
class _Index:
    """Búsqueda del intervalo (no traslapado, ordenado) que contiene un instante."""

    def __init__(self, items, start=lambda x: x.start, end=lambda x: x.end):
        self.items = sorted(items, key=start)
        self.starts = [start(x) for x in self.items]
        self._end = end

    def at(self, t: datetime):
        i = bisect_right(self.starts, t) - 1
        if i >= 0 and t < self._end(self.items[i]):
            return self.items[i]
        return None


class _Coverage:
    """Varias ventanas que sí pueden traslaparse (justificaciones): devuelve una que cubra el instante."""

    def __init__(self, items):
        self.items = sorted(items, key=lambda x: x.start)

    def at(self, t: datetime):
        return next((j for j in self.items if j.start <= t < j.end), None)


def _same_state(a: Actual | None, b: Actual | None) -> bool:
    if a is None or b is None:
        return a is b
    return (a.primary, a.aux) == (b.primary, b.aux)


def evaluate(plan: list[PlanBlock], actuals: list[Actual], justifications: list[Justification],
             activities: dict[str, Activity], *, window_start: datetime, window_end: datetime,
             calendar_day=lambda t: t.date()) -> Result:
    """Clasifica cada tramo de [window_start, window_end) y acumula los totales por día del turno.

    El tiempo dentro de un contenedor se asigna a la FECHA DEL TURNO; el exceso de login fuera de contenedores, al
    día calendario en que ocurrió (`calendar_day`)."""
    actuals = [a for a in actuals if a.end > a.start]
    result = Result(plan=plan, actuals=actuals, justifications=list(justifications))
    plan_ix = _Index(plan)
    act_ix = _Index(actuals)
    just = _Coverage([j for j in justifications if j.end > j.start])
    points = {window_start, window_end}
    for x in (*plan, *actuals, *just.items):
        for t in (x.start, x.end):
            if window_start < t < window_end:
                points.add(t)
    ordered = sorted(points)
    for a, b in zip(ordered, ordered[1:]):
        secs = int((b - a).total_seconds())
        if secs <= 0:
            continue
        p = plan_ix.at(a)
        state = act_ix.at(a)
        j = just.at(a)
        if p is not None:
            activity = activities.get(p.activity) or Activity(p.activity)
            t = result.day(p.shift_date)
            t.scheduled += secs
            if activity.is_paid:
                t.scheduled_paid += secs
            role = activity.match(state) if state is not None else None
            if state is not None:
                t.logged += secs
                t.logged_in_container += secs
            if not activity.requires_login:
                # Fase 19: actividad que no exige sesión ACD (permiso RRHH, falla de sistema, Legal Benefit Lunch):
                # el tiempo se cumple con o sin sesión y se paga / factura según la actividad.
                t.in_adherence += secs
                if activity.is_paid or (state is not None and state.paid):
                    t.paid_valid += secs
                    if activity.is_billable:
                        t.billable += secs
            elif role is not None:
                t.in_adherence += secs
                paid = state.paid or role == SECONDARY_ROLE
                if paid:
                    t.paid_valid += secs
                    if activity.is_billable:
                        t.billable += secs
                    if role == PRIMARY_ROLE:
                        t.primary_work += secs
                    else:
                        t.secondary_paid += secs
            elif j is not None:
                t.justified += secs
                t.justified_scheduled += secs
                if j.is_paid or (state is not None and state.paid):
                    t.paid_valid += secs
            else:
                t.out_of_adherence += secs
                if state is not None and state.paid:
                    t.paid_valid += secs  # dentro del contenedor: válido para pago, no para facturación
                _add_deviation(result, OUT_OF_ADHERENCE, p.shift_date, a, b, p.activity, state)
        elif state is not None:
            t = result.day(calendar_day(a))
            t.logged += secs
            if j is not None:
                t.justified += secs
                if j.is_paid and state.paid:
                    t.paid_valid += secs
            else:
                t.unpaid_excess += secs
                _add_deviation(result, UNPAID_EXCESS, t.day, a, b, None, state)
    return result


def _add_deviation(result: Result, kind: str, day: date, a: datetime, b: datetime, expected: str | None, state: Actual | None):
    last = result.deviations[-1] if result.deviations else None
    if (last and last.kind == kind and last.day == day and last.end == a and last.expected == expected
            and _same_state(last.actual, state)):
        last.end = b
        return
    result.deviations.append(Deviation(kind, day, a, b, expected, state))
