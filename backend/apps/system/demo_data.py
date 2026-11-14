"""Fase 26 — Datos de prueba para la demostración (python manage.py demo_data).

Genera, con los MISMOS servicios que usa la interfaz (validaciones, AP, triggers y auditoría incluidos):

* Catálogo operativo: 3 clientes, 5 marcas, 3 líneas de negocio y 7 sub-líneas (sincronizados con el roster).
* 28 colaboradores con expediente completo (datos personales, seguridad social, banco, contacto de emergencia, documentos
  obligatorios con imagen de muestra y fotografía), su Primera AP de horario aprobada y su roster (cliente, marca, línea,
  sub-línea, Team Manager, puesto y tipo de contrato).
* Cadena de mando: Operations Director → Operations Manager → 2 Account Supervisors → 4 Team Managers → 16 agentes.
  Fase 27: se verifica que cada agente quede bajo SU Team Manager con la cadena completa; el roster incluye la wave,
  las fechas de capacitación, nesting y salida a producción y el tipo de documento de reportes.
* General IDs (Fase 27): Payroll Tool ID para todos y ACD ID por cuenta (cliente y marca) para los agentes.
* Cuentas de usuario por rol (RRHH, WFM, líderes y agentes) con contraseñas aleatorias fuertes.
* Segmentos de la grilla (breaks, almuerzo, coaching, reuniones y capacitación) para el corte del 10 al 24 de noviembre
  de 2026 y la asistencia ACD de los días ya transcurridos.
* Comunicados genéricos del periódico virtual (algunos con acuse de recibo obligatorio).

Es idempotente: lo que ya existe se reutiliza (por código, documento de identidad, usuario o título). Cada ejecución
asigna contraseñas NUEVAS a las cuentas de prueba y reescribe el archivo de accesos.

Todo lo generado se identifica por el dominio de correo DEMO_DOMAIN y el prefijo DEMO_USER_PREFIX de los usuarios.
"""

from __future__ import annotations

import io
import random
import secrets
import string
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone

DEMO_DOMAIN = "demo.metamorph.test"
DEMO_USER_PREFIX = "demo."
CUTOFF_START, CUTOFF_END = date(2026, 11, 10), date(2026, 11, 24)
TZ = ZoneInfo("America/El_Salvador")


class DemoError(Exception):
    pass


# ======================================================================== catálogo
CLIENTS = [
    ("NOVA", "Nova Telecom", "Nova Telecom, S.A. de C.V.", "Telefonía móvil, internet y televisión"),
    ("AURA", "Aura Seguros", "Aura Seguros, S.A.", "Seguros de auto, vida y gastos médicos"),
    ("VERTEX", "Vertex Retail", "Vertex Retail Group, Inc.", "Comercio electrónico y logística"),
]
BRANDS = [
    ("NOVA-MOVIL", "Nova Móvil", "NOVA"),
    ("NOVA-HOGAR", "Nova Hogar", "NOVA"),
    ("AURA-AUTO", "Aura Auto", "AURA"),
    ("AURA-VIDA", "Aura Vida", "AURA"),
    ("VERTEX-ONLINE", "Vertex Online", "VERTEX"),
]
LINES = [
    ("VOZ", "Voz (Inbound)", "Atención telefónica entrante"),
    ("CHAT", "Chat y mensajería", "WhatsApp, chat web y redes sociales"),
    ("BACKOFFICE", "Back Office", "Gestión de casos sin contacto en vivo"),
]
SUB_LINES = [
    ("VOZ-SOPORTE", "Soporte técnico", "VOZ"),
    ("VOZ-VENTAS", "Ventas", "VOZ"),
    ("VOZ-SINIESTROS", "Reclamos y siniestros", "VOZ"),
    ("CHAT-SOPORTE", "Soporte por chat", "CHAT"),
    ("CHAT-RETENCION", "Retención", "CHAT"),
    ("BO-EMAIL", "Gestión de correos", "BACKOFFICE"),
    ("BO-VERIFICACION", "Verificación de pedidos", "BACKOFFICE"),
]

# ======================================================================== personas
# (clave, nombre, segundo nombre, apellido, segundo apellido, género, puesto, rol de la app, salario, centro de costos)
STAFF = [
    ("hr", "Gabriela", "Alejandra", "Martínez", "Rosales", "F", "Generalista de RRHH", "HR", "1350.00", "SV-RRHH"),
    ("payroll", "Luis", "Ernesto", "Hernández", "Aguilar", "M", "Especialista de planillas", "HR", "1250.00", "SV-RRHH"),
    ("wfm", "Fernanda", "Lucía", "Ortiz", "Navarrete", "F", "Analista WFM", "WFM", "1100.00", "SV-ADM"),
    ("rta", "Ernesto", "Javier", "Romero", "Valle", "M", "Analista de tiempo real", "WFM", "950.00", "SV-ADM"),
    ("director", "Roberto", "Alejandro", "Méndez", "Castillo", "M", "Director de Operaciones", "WFM", "3200.00", "SV-OPS"),
    ("manager", "Claudia", "Patricia", "Rivas", "Herrera", "F", "Operations Manager", "WFM", "2400.00", "SV-OPS"),
    ("sup_nova", "Diego", "Fernando", "Salazar", "Mejía", "M", "Account Supervisor", "WFM", "1600.00", "SV-OPS"),
    ("sup_aura", "Mónica", "Beatriz", "Alvarado", "Flores", "F", "Account Supervisor", "WFM", "1600.00", "SV-OPS"),
    ("tm_nova1", "José", "Manuel", "Portillo", "Cruz", "M", "Team Manager", "WFM", "1150.00", "SV-OPS"),
    ("tm_nova2", "Karla", "Vanessa", "Guzmán", "Ramos", "F", "Team Manager", "WFM", "1150.00", "SV-OPS"),
    ("tm_aura", "Andrés", "Eduardo", "Molina", "Santos", "M", "Team Manager", "WFM", "1150.00", "SV-OPS"),
    ("tm_vertex", "Daniela", "Sofía", "Campos", "Orellana", "F", "Team Manager", "WFM", "1150.00", "SV-OPS"),
]
LEADERS = [  # (clave, nivel, jefe, cliente)
    ("director", "OPS_DIRECTOR", None, None),
    ("manager", "OPS_MANAGER", "director", None),
    ("sup_nova", "ACCOUNT_SUPERVISOR", "manager", "NOVA"),
    ("sup_aura", "ACCOUNT_SUPERVISOR", "manager", "AURA"),
    ("tm_nova1", "TEAM_MANAGER", "sup_nova", "NOVA"),
    ("tm_nova2", "TEAM_MANAGER", "sup_nova", "NOVA"),
    ("tm_aura", "TEAM_MANAGER", "sup_aura", "AURA"),
    ("tm_vertex", "TEAM_MANAGER", "sup_aura", "VERTEX"),
]
STAFF_ROSTER = {"director": None, "manager": None, "sup_nova": "NOVA", "sup_aura": "AURA", "tm_nova1": "NOVA",
                "tm_nova2": "NOVA", "tm_aura": "AURA", "tm_vertex": "VERTEX"}
STAFF_SCHEDULE = {"rta": "L-V 07:00-16:00 60"}
# Equipos: Team Manager → cuenta, horario y agentes (nombre, segundo nombre, apellido, segundo apellido, género, nivel)
TEAMS = {
    "tm_nova1": {
        "client": "NOVA", "brand": "NOVA-MOVIL", "lob": "VOZ", "sub": "VOZ-SOPORTE", "schedule": "L-V 07:00-16:00 60",
        "agents": [("Carlos", "Antonio", "Ramírez", "López", "M", 1), ("María", "José", "Hernández", "Pérez", "F", 1),
                   ("Kevin", "Alexander", "Pineda", "Rivera", "M", 1), ("Andrea", "Carolina", "Mejía", "Turcios", "F", 2)],
    },
    "tm_nova2": {
        "client": "NOVA", "brand": "NOVA-HOGAR", "lob": "CHAT", "sub": "CHAT-SOPORTE", "schedule": "L-V 10:00-19:00 60",
        "agents": [("Jonathan", "Isaac", "Flores", "Ayala", "M", 1), ("Sofía", "Marisol", "Cañas", "Bonilla", "F", 1),
                   ("Bryan", "Josué", "Quintanilla", "Mora", "M", 1), ("Valeria", "Ivonne", "Recinos", "Lara", "F", 2)],
    },
    "tm_aura": {
        "client": "AURA", "brand": "AURA-AUTO", "lob": "VOZ", "sub": "VOZ-SINIESTROS", "schedule": "L-V 08:00-17:00 60",
        "agents": [("Ricardo", "Alonso", "Escobar", "Galdámez", "M", 1), ("Paola", "Beatriz", "Argueta", "Chávez", "F", 1),
                   ("Óscar", "Rene", "Villalta", "Sosa", "M", 1), ("Gabriela", "Nohemy", "Fuentes", "Montes", "F", 2)],
    },
    "tm_vertex": {
        "client": "VERTEX", "brand": "VERTEX-ONLINE", "lob": "BACKOFFICE", "sub": "BO-EMAIL",
        "schedule": "L-V 11:00-20:00 60; S 08:00-12:00",
        "agents": [("Alejandro", "David", "Guevara", "Linares", "M", 1), ("Katherine", "Michelle", "Orellana", "Durán", "F", 1),
                   ("Fernando", "Enrique", "Zelaya", "Barrera", "M", 1), ("Lucía", "Fernanda", "Portillo", "Saravia", "F", 2)],
    },
}
ACD_PREFIX = {"NOVA": "NV", "AURA": "AU", "VERTEX": "VX"}  # ACD ID por cuenta (Fase 27)
TRAINING_DAYS, NESTING_DAYS = 14, 14  # capacitación y nesting antes de producción
TIER_TITLE = {1: "Agente Tier 1", 2: "Agente Tier 2"}
TIER_SALARY = {1: "520.00", 2: "640.00"}
BANKS = ["Banco Agrícola", "Banco Cuscatlán", "Banco Davivienda Salvadoreño", "BAC Credomatic", "Banco Promerica"]
EMERGENCY_NAMES = ["Rosa Elena", "Juan Carlos", "Ana Lucía", "Mario Ernesto", "Silvia Marina", "Héctor Daniel", "Carmen Alicia"]

# ======================================================================== comunicados
ANNOUNCEMENTS = [
    {"title": "Bienvenida a la nueva plataforma Metamorph ERP", "category": "NEWS", "pinned": True,
     "summary": "Desde este mes, sus horarios, asistencia, acciones de personal y boletas se consultan en un solo lugar.",
     "body": "Estimado equipo:\n\nA partir de este corte, Metamorph ERP concentra la información de recursos humanos, "
             "Workforce Management y planillas. En el portal del colaborador encontrará su horario, el detalle de su "
             "asistencia y sus boletas de pago.\n\nSi tiene dudas, escriba a su Team Manager o al equipo de RRHH."},
    {"title": "Recordatorio: seguridad de la información y phishing", "category": "SECURITY", "requires_ack": True, "ack_days": 7,
     "summary": "Nunca comparta su contraseña ni abra enlaces de remitentes desconocidos. Confirme la lectura de esta política.",
     "body": "Hemos detectado correos que suplantan a clientes y proveedores. Recuerde:\n\n"
             "1. Nadie de TI o RRHH le pedirá su contraseña.\n2. Verifique el remitente antes de abrir adjuntos.\n"
             "3. Bloquee su equipo (Windows + L) cada vez que se levante del puesto.\n4. Reporte cualquier correo "
             "sospechoso a su supervisor.\n\nLa confirmación de lectura es obligatoria para todo el personal."},
    {"title": "Calendario de pago de la segunda quincena de noviembre", "category": "PAYROLL",
     "summary": "El corte de asistencia cierra el 24 de noviembre y el pago se acredita el 30 de noviembre.",
     "body": "El corte de asistencia de la segunda quincena de noviembre va del 10 al 24 de noviembre de 2026. Las acciones "
             "de personal que afecten el pago (horas extra, permisos y justificaciones) deben quedar aprobadas antes del "
             "cierre del corte.\n\nLa boleta preliminar estará disponible en el portal dos días antes del pago."},
    {"title": "Nueva estructura de supervisión de las cuentas Nova y Aura", "category": "ORG_CHANGE", "requires_ack": True,
     "ack_days": 5, "audience_roles": ["EMPLOYEE", "WFM"],
     "summary": "Cada cuenta tiene ahora un Account Supervisor dedicado y equipos de cuatro agentes por Team Manager.",
     "body": "Con el crecimiento de las cuentas Nova Telecom y Aura Seguros, la operación se organiza así:\n\n"
             "• Nova Telecom: Diego Salazar (Account Supervisor) con los equipos de José Portillo (Voz) y Karla Guzmán (Chat).\n"
             "• Aura Seguros y Vertex Retail: Mónica Alvarado (Account Supervisor) con los equipos de Andrés Molina y "
             "Daniela Campos.\n\nSu Team Manager ya aparece en su ficha del roster. Confirme la lectura de este cambio."},
    {"title": "Política de vacaciones y permisos 2027", "category": "HR",
     "summary": "Las vacaciones del primer trimestre de 2027 se solicitan antes del 15 de diciembre.",
     "body": "Para planificar la cobertura de la operación, las solicitudes de vacaciones de enero a marzo de 2027 se "
             "reciben hasta el 15 de diciembre. Los permisos con goce de sueldo requieren una acción de personal aprobada "
             "por WFM y RRHH."},
    {"title": "Encuesta de clima laboral 2026", "category": "FORM", "link_url": "https://forms.example.com/clima-2026",
     "link_label": "Responder la encuesta",
     "summary": "Su opinión es anónima y nos ayuda a mejorar. Toma menos de 10 minutos.",
     "body": "Le invitamos a responder la encuesta anual de clima laboral. Las respuestas son anónimas y los resultados "
             "se compartirán por cuenta en enero."},
    {"title": "Celebración de fin de año del equipo", "category": "CULTURE",
     "summary": "Viernes 18 de diciembre, después del turno: convivio, rifas y reconocimiento a los agentes del año.",
     "body": "Les esperamos a todos en el convivio de fin de año. Habrá reconocimientos a los agentes con mejor adherencia "
             "y calidad de cada cuenta. Confirme su asistencia con su Team Manager."},
    {"title": "Lanzamiento de la línea de verificación de pedidos de Vertex", "category": "OPS",
     "summary": "Vertex Retail amplía el back office con verificación de pedidos a partir de diciembre.",
     "body": "Vertex Retail confió a nuestro equipo la verificación de pedidos de alto valor. La capacitación inicia la "
             "primera semana de diciembre para los agentes Tier 2 de la cuenta."},
]


# ======================================================================== utilidades
def _dui(rng: random.Random) -> str:
    """DUI salvadoreño con dígito verificador válido (módulo 10, pesos 9..2)."""
    digits = [rng.randint(0, 9) for _ in range(8)]
    check = (10 - sum(d * w for d, w in zip(digits, range(9, 1, -1))) % 10) % 10
    return "".join(map(str, digits)) + f"-{check}"


def _phone(rng: random.Random) -> str:
    return f"{rng.choice('67')}{rng.randint(100, 999)}-{rng.randint(1000, 9999)}"


def _fold(text: str) -> str:
    table = str.maketrans("áéíóúñÁÉÍÓÚÑ", "aeiounAEIOUN")
    return text.translate(table).lower().replace(" ", "")


def new_password() -> str:
    """16 caracteres con mayúsculas, minúsculas, dígitos y símbolos (cumple los validadores de Django)."""
    alphabet = string.ascii_letters + string.digits
    while True:
        core = "".join(secrets.choice(alphabet) for _ in range(13))
        pwd = f"{core[:5]}-{core[5:10]}!{core[10:]}"
        if any(c.isupper() for c in pwd) and any(c.islower() for c in pwd) and any(c.isdigit() for c in pwd):
            return pwd


def _png(lines: list[str], *, size=(900, 560), bg=(244, 246, 249), fg=(28, 36, 48), accent=(91, 124, 250)) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, size[0], 18], fill=accent)
    draw.rectangle([24, 42, size[0] - 24, size[1] - 24], outline=(200, 207, 217), width=3)
    big, small = ImageFont.load_default(size=34), ImageFont.load_default(size=24)
    y = 70
    for i, line in enumerate(lines):
        draw.text((56, y), line, fill=accent if i == 0 else fg, font=big if i < 2 else small)
        y += 54 if i < 2 else 38
    draw.text((56, size[1] - 70), "DOCUMENTO DE PRUEBA - SIN VALIDEZ LEGAL", fill=(155, 28, 28), font=small)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _avatar(initials: str, color: tuple[int, int, int]) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (480, 480), color)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=190)
    box = draw.textbbox((0, 0), initials, font=font)
    draw.text(((480 - (box[2] - box[0])) / 2 - box[0], (480 - (box[3] - box[1])) / 2 - box[1]), initials, fill="white", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _day_span(definition: dict, key: str) -> tuple[time, time] | None:
    """Entrada y salida del día en la definición del horario (un bloque o lista de bloques)."""
    day = (definition.get("days") or {}).get(key)
    blocks = [b for b in (day if isinstance(day, list) else [day]) if b]
    if not blocks:
        return None
    return time.fromisoformat(blocks[0]["start"]), time.fromisoformat(blocks[-1]["end"])


# ======================================================================== generador
@dataclass
class Person:
    key: str
    first: str
    middle: str
    last: str
    second_last: str
    gender: str
    title: str
    role: str
    salary: str
    cost_center: str
    schedule: str
    hire: date
    team: str | None = None  # Team Manager del agente
    tier: int | None = None
    employee: object = None
    user: object = None
    password: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.first} {self.middle} {self.last} {self.second_last}"

    @property
    def username(self) -> str:
        return f"{DEMO_USER_PREFIX}{_fold(self.first)}.{_fold(self.last)}"

    @property
    def email(self) -> str:
        return f"{_fold(self.first)}.{_fold(self.last)}@{DEMO_DOMAIN}"


@dataclass
class Result:
    people: list[Person] = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def add(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n


def _people() -> list[Person]:
    rng = random.Random(26)
    people = []
    for i, (key, first, middle, last, second, gender, title, role, salary, cc) in enumerate(STAFF):
        hire = date(2026, 1, 12) + timedelta(days=14 * i)
        people.append(Person(key, first, middle, last, second, gender, title, role, salary, cc,
                             STAFF_SCHEDULE.get(key, "L-V 08:00-17:00 60"), hire))
    for tm, team in TEAMS.items():
        for j, (first, middle, last, second, gender, tier) in enumerate(team["agents"]):
            hire = date(2026, 8, 3) + timedelta(days=rng.randint(0, 70))
            people.append(Person(f"{tm}_a{j + 1}", first, middle, last, second, gender, TIER_TITLE[tier], "EMPLOYEE",
                                 TIER_SALARY[tier], "SV-OPS", team["schedule"], hire, team=tm, tier=tier))
    return people


class DemoSeeder:
    def __init__(self, *, stdout=None):
        self.out = stdout
        self.result = Result()
        self.rng = random.Random(2026)
        self.hr_user = None
        self.report_id_type = None

    def log(self, msg: str) -> None:
        if self.out is not None:
            self.out.write(msg)

    # ------------------------------------------------------------------ 1. catálogo
    def catalog(self) -> None:
        from apps.common.models import Country
        from apps.operations.models import Brand, Client, LineOfBusiness, SubLineOfBusiness

        sv = Country.objects.get(country_code="SV")
        clients = {}
        for code, name, legal, desc in CLIENTS:
            obj, created = Client.objects.get_or_create(code=code, defaults={"name": name, "legal_name": legal, "description": desc,
                                                                             "country": sv})
            clients[code] = obj
            self.result.add("clientes", created)
        for code, name, client in BRANDS:
            _, created = Brand.objects.get_or_create(code=code, defaults={"name": name, "client": clients[client]})
            self.result.add("marcas", created)
        lines = {}
        for code, name, desc in LINES:
            obj, created = LineOfBusiness.objects.get_or_create(code=code, defaults={"name": name, "description": desc})
            lines[code] = obj
            self.result.add("líneas de negocio", created)
        for code, name, line in SUB_LINES:
            _, created = SubLineOfBusiness.objects.get_or_create(code=code, defaults={"name": name, "line": lines[line]})
            self.result.add("sub-líneas", created)

    # ------------------------------------------------------------------ 2. colaboradores
    def _payload(self, p: Person) -> dict:
        rng = self.rng
        return {
            "country": "SV", "first_name": p.first, "middle_name": p.middle, "last_name": p.last, "second_last_name": p.second_last,
            "gender": p.gender, "national_id_type": "DUI", "national_id_number": _dui(rng),
            "birth_date": date(1975 + rng.randint(0, 27), rng.randint(1, 12), rng.randint(1, 28)).isoformat(),
            "hire_date": p.hire.isoformat(), "base_salary": p.salary, "pay_frequency": "BIWEEKLY", "cost_center": p.cost_center,
            "work_email": p.email, "personal_email": f"{_fold(p.first)}{rng.randint(10, 99)}@correo.{DEMO_DOMAIN}",
            "phone_number": _phone(rng), "social_security_number": f"{rng.randint(10**8, 10**9 - 1)}",
            "pension_id": f"{rng.randint(10**11, 10**12 - 1)}", "pension_fund": rng.choice(["CONFIA", "CRECER"]),
            "bank_name": rng.choice(BANKS), "bank_account_number": f"{rng.randint(10**9, 10**10 - 1)}",
            "emergency_contact_name": f"{rng.choice(EMERGENCY_NAMES)} {p.last}", "emergency_contact_phone": _phone(rng),
            "dependents_count": str(rng.randint(0, 3)), "schedule": p.schedule,
        }

    def employee(self, p: Person) -> None:
        from apps.employees.batch import process_single
        from apps.hcm.models import Employee

        existing = Employee.objects.filter(work_email=p.email).first()
        payload = self._payload(p)  # se calcula siempre: mantiene estable la secuencia aleatoria
        if existing is not None:
            p.employee = existing
            return
        payload["tax_id"] = payload["national_id_number"]  # DUI homologado como NIT
        outcome = process_single(payload, user=self.hr_user)
        if outcome.employee is None:
            errors = "; ".join(f"{m.field}: {m.message}" for m in outcome.row.errors)
            raise DemoError(f"No se pudo crear a {p.full_name}: {errors}")
        p.employee = outcome.employee
        self.result.add("colaboradores")

    def approve_initial(self, p: Person) -> None:
        from apps.personnel_actions import services as pa
        from apps.personnel_actions.models import Decision, PersonnelAction, Status

        for action in PersonnelAction.objects.filter(employee=p.employee, is_initial=True, status=Status.PENDING):
            while action.status == Status.PENDING:
                pa.sign(action, user=self.hr_user, decision=Decision.APPROVED, comment="Alta de datos de demostración.")
                action.refresh_from_db()
            self.result.add("AP de horario aprobadas")
        if not PersonnelAction.objects.filter(employee=p.employee, is_initial=True, status=Status.APPROVED).exists():
            raise DemoError(f"{p.full_name} quedó sin Primera AP de horario aprobada.")

    # ------------------------------------------------------------------ 3. cuentas
    def account(self, p: Person) -> None:
        from apps.accounts.models import CustomUser

        user = CustomUser.objects.filter(username=p.username).first()
        if user is None:
            user = CustomUser(username=p.username, role=p.role, employee=p.employee)
            self.result.add("cuentas de usuario")
        elif user.employee_id and user.employee_id != p.employee.employee_code:
            raise DemoError(f"La cuenta {p.username} ya existe vinculada a otro colaborador.")
        p.password = new_password()
        validate_password(p.password, user)
        user.first_name, user.last_name, user.email = p.first, p.last, p.email
        user.role, user.employee, user.cost_center = p.role, p.employee, p.employee.cost_center
        user.is_active, user.must_change_password = True, False
        user.failed_login_count, user.locked_at, user.lock_reason = 0, None, ""
        user.set_password(p.password)
        user.password_changed_at = timezone.now()
        user.save()
        p.user = user

    # ------------------------------------------------------------------ 4. jerarquía y roster
    def hierarchy(self, by_key: dict[str, Person]) -> dict[str, object]:
        from apps.operations.hierarchy import save_leader
        from apps.operations.models import OperationalLeader

        leaders = {}
        for key, level, boss, client in LEADERS:
            emp = by_key[key].employee
            lead = OperationalLeader.objects.filter(level=level, employee=emp).first()
            if lead is None:
                lead = save_leader({"level": level, "employee_code": emp.employee_code,
                                    "reports_to": leaders[boss].pk if boss else None, "client": client or ""}, user=self.hr_user)
                self.result.add("líderes")
            leaders[key] = lead
        return leaders

    def _report_id_type(self) -> str | None:
        from apps.roster.models import RosterAttribute, RosterDimensionItem

        attr = RosterAttribute.objects.filter(code="report_id_type", is_active=True).first()
        if attr is None or not attr.dimension_id:
            return None
        item = RosterDimensionItem.objects.filter(dimension_id=attr.dimension_id, code="DUI", is_active=True).first()
        return item.code if item else None

    def roster(self, p: Person) -> None:
        from apps.roster.services import apply_plan, plan_changes

        values = {"job_title": p.title, "contract_type": "PERMANENTE"}
        if self.report_id_type:
            values["report_id_type"] = self.report_id_type
        if p.team:
            team = TEAMS[p.team]
            values.update({"client": team["client"], "brand": team["brand"], "line_of_business": team["lob"],
                           "sub_line_of_business": team["sub"], "team_manager": self.people[p.team].employee.employee_code})
            # Fase 27: ciclo de ingreso del agente (capacitación → nesting → producción) y su wave.
            values.update({
                "training_wave": f"Wave {team['client']} {team['lob']} {p.hire:%m/%Y}",
                "training_start_date": p.hire.isoformat(),
                "nesting_start_date": (p.hire + timedelta(days=TRAINING_DAYS)).isoformat(),
                "nesting_end_date": (p.hire + timedelta(days=TRAINING_DAYS + NESTING_DAYS - 1)).isoformat(),
                "operations_start_date": (p.hire + timedelta(days=TRAINING_DAYS + NESTING_DAYS)).isoformat(),
            })
        elif STAFF_ROSTER.get(p.key):
            values["client"] = STAFF_ROSTER[p.key]
        plan = plan_changes(p.employee, {"effective_date": p.hire.isoformat(), "reason": "Alta de datos de demostración",
                                         "values": values})
        if not plan.ok:
            raise DemoError(f"Roster de {p.full_name}: " + "; ".join(e["message"] for e in plan.errors))
        if plan.effective_changes:
            apply_plan(plan, self.hr_user.username)
            self.result.add("asignaciones de roster", len(plan.effective_changes))

    def general_ids(self, p: Person) -> None:
        """Fase 27: IDs en herramientas externas — Payroll Tool ID (global) para todos y ACD ID por cuenta para agentes."""
        from apps.general_ids import services as gid
        from apps.general_ids.models import EmployeeGeneralId, GeneralIdType

        emp = p.employee
        wanted = [("PAYROLL_TOOL_ID", f"PT{emp.pk:06d}", None, None)]
        if p.team:
            team = TEAMS[p.team]
            wanted.append(("ACD_ID", f"{ACD_PREFIX[team['client']]}{70000 + emp.pk}", team["client"], team["brand"]))
        for code, value, client, brand in wanted:
            id_type = GeneralIdType.objects.filter(code=code, is_active=True).first()
            if id_type is None:
                note = f"Tipo de General ID {code} no configurado: se omitió."
                if note not in self.result.notes:
                    self.result.notes.append(note)
                continue
            if EmployeeGeneralId.objects.filter(employee=emp, id_type=id_type).exists():
                continue
            check = gid.validate(emp, {"id_type": id_type.pk, "value": value, "client": client, "brand": brand,
                                       "effective_start": p.hire.isoformat(), "notes": "Datos de demostración"})
            if not check.ok:
                raise DemoError(f"General ID {code} de {p.full_name}: " + "; ".join(e["message"] for e in check.errors))
            gid.create(emp, check, user=self.hr_user)
            self.result.add("General IDs")

    def verify_hierarchy(self) -> None:
        """Fase 27: cada agente debe quedar bajo SU Team Manager y con la cadena completa hasta el Director."""
        from apps.operations.hierarchy import agent_hierarchy

        agents = [p for p in self.people.values() if p.team]
        on = max(timezone.localdate(), max(p.hire for p in agents))
        tree = agent_hierarchy([p.employee.pk for p in agents], on)
        expected_sup = {tm: boss for tm, _lvl, boss, _c in LEADERS}
        for p in agents:
            chain = tree.get(p.employee.pk) or {}
            tm, sup = self.people[p.team], self.people[expected_sup[p.team]]
            got = {lvl: (chain.get(lvl) or {}).get("employee_code") for lvl in ("TEAM_MANAGER", "ACCOUNT_SUPERVISOR",
                                                                               "OPS_MANAGER", "OPS_DIRECTOR")}
            want = {"TEAM_MANAGER": tm.employee.employee_code, "ACCOUNT_SUPERVISOR": sup.employee.employee_code,
                    "OPS_MANAGER": self.people["manager"].employee.employee_code,
                    "OPS_DIRECTOR": self.people["director"].employee.employee_code}
            if got != want:
                raise DemoError(f"{p.full_name} no quedó bajo la cadena esperada: {got} ≠ {want}.")
        self.result.counts["agentes con cadena de mando completa"] = len(agents)

    def acd_membership(self, p: Person) -> None:
        from apps.acd.models import AgentGroup, AgentMembership

        group = AgentGroup.objects.filter(code="GENERAL").first()
        if group and not AgentMembership.objects.filter(group=group, employee=p.employee).exists():
            AgentMembership.objects.create(group=group, employee=p.employee)
            self.result.add("agentes en grupos ACD")

    # ------------------------------------------------------------------ 5. grilla del corte
    def _plan_for(self, p: Person, d: date, start: time, end: time) -> list[tuple[str, time, time]]:
        """Bloques del día: breaks, almuerzo y actividades de desarrollo (sin traslapes)."""
        def at(minutes: int) -> time:
            return (datetime.combine(d, start) + timedelta(minutes=minutes)).time()

        length = int((datetime.combine(d, end) - datetime.combine(d, start)).total_seconds() // 60)
        if length <= 300:  # medio turno (sábado): un break
            return [("BREAK", at(120), at(135))]
        blocks = [("BREAK", at(120), at(135)), ("MEAL", at(240), at(300)), ("BREAK", at(420), at(435))]
        if p.team is None:  # personal administrativo y líderes: solo almuerzo
            return [("MEAL", at(240), at(300))]
        weekday = d.weekday()
        if weekday == 0:
            blocks.append(("MEETING", at(15), at(45)))  # reunión de equipo del lunes
        if weekday == 2 and p.tier == 1:
            blocks.append(("COACHING", at(330), at(360)))
        if weekday == 3 and p.tier == 2:
            blocks.append(("TRAINING", at(315), at(405)))
        return blocks

    def segments(self, p: Person) -> None:
        from apps.adherence.models import ScheduleSegment
        from apps.adherence.services import AdhError, AdhErrors, save_segment
        from apps.scheduling.engine import DAY_KEYS
        from apps.scheduling.models import ScheduleAssignment

        assignment = ScheduleAssignment.objects.filter(employee=p.employee, mode="PRIMARY").order_by("-effective_start_date").first()
        if assignment is None:
            raise DemoError(f"{p.full_name} no tiene horario asignado.")
        d = CUTOFF_START
        while d <= CUTOFF_END:
            span = _day_span(assignment.definition, DAY_KEYS[d.weekday()])
            if span and not ScheduleSegment.objects.filter(employee=p.employee, shift_date=d).exists():
                start, end = span
                for code, s, e in self._plan_for(p, d, start, end):
                    try:
                        with transaction.atomic():
                            save_segment(p.employee, {"shift_date": d.isoformat(), "activity": code, "start": s.strftime("%H:%M"),
                                                      "end": e.strftime("%H:%M"), "notes": "Plan del corte (demostración)"},
                                         user=self.wfm_user, audit=False)
                        self.result.add("segmentos de grilla")
                    except (AdhError, AdhErrors) as exc:
                        self.result.notes.append(f"{p.employee.employee_code} {d}: {code} omitido ({exc}).")
            d += timedelta(days=1)

    # ------------------------------------------------------------------ 6. asistencia ACD de los días transcurridos
    def attendance(self, p: Person) -> None:
        from apps.acd.models import AgentGroup, AgentSession, AuxCode, PrimaryStatus, StatusSegment
        from apps.adherence.models import ScheduleSegment

        group = AgentGroup.objects.filter(code="GENERAL").first()
        if group is None or p.team is None:
            return
        statuses = {s.code: s for s in PrimaryStatus.objects.all()}
        aux = {a.code: a for a in AuxCode.objects.all()}
        aux_for = {"BREAK": "BREAK_STD", "MEAL": "LUNCH", "MEETING": "TEAM_MEETING", "COACHING": "COACHING",
                   "TRAINING": "TRAINING_SESSION"}
        today = timezone.localdate()
        rng = random.Random(p.employee.employee_id)
        d = CUTOFF_START
        while d <= today:  # hoy: hasta la hora actual (turnos ya iniciados)
            plan = list(ScheduleSegment.objects.filter(employee=p.employee, shift_date=d).select_related("activity").order_by("start_at"))
            if plan and not AgentSession.objects.filter(employee=p.employee, login_at__date=d).exists():
                self._day_session(p, d, plan, group, statuses, aux, aux_for, rng)
            d += timedelta(days=1)

    def _day_session(self, p, d, plan, group, statuses, aux, aux_for, rng) -> None:
        from apps.acd.models import AgentSession, StatusSegment
        from apps.scheduling.engine import DAY_KEYS
        from apps.scheduling.models import ScheduleAssignment

        assignment = ScheduleAssignment.objects.filter(employee=p.employee, mode="PRIMARY").order_by("-effective_start_date").first()
        s0, e0 = _day_span(assignment.definition, DAY_KEYS[d.weekday()])
        start, end = datetime.combine(d, s0, TZ), datetime.combine(d, e0, TZ)
        login = start - timedelta(minutes=rng.randint(2, 9), seconds=rng.randint(0, 59))
        logout = end + timedelta(minutes=rng.randint(0, 6), seconds=rng.randint(0, 59))
        now = timezone.localtime()
        if login >= now - timedelta(minutes=15):
            return  # el turno de hoy aún no empieza
        logout = min(logout, now.replace(microsecond=0) - timedelta(minutes=5))
        session = AgentSession.objects.create(employee=p.employee, group=group, login_at=login, logout_at=logout, logout_source="AGENT")
        cuts = [(login, "ON_QUEUE", None)]
        for seg in plan:
            s, e = seg.start_at.replace(tzinfo=TZ), seg.end_at.replace(tzinfo=TZ)
            code = aux_for.get(seg.activity.code)
            if not code:
                continue
            drift = timedelta(seconds=rng.randint(-60, 90))
            cuts.append((s + drift, aux[code].primary_status.code, aux[code]))
            cuts.append((e + drift, "ON_QUEUE", None))
        cuts = sorted((c for c in cuts if c[0] < logout), key=lambda c: c[0])
        rows = []
        for i, (at, status, code) in enumerate(cuts):
            until = cuts[i + 1][0] if i + 1 < len(cuts) else logout
            if until <= at:
                continue
            rows.append(StatusSegment(employee=p.employee, session=session, primary_status=statuses[status], aux_code=code, group=group,
                                      division=group.division, start_at=at, end_at=until,
                                      duration_ms=int((until - at).total_seconds() * 1000), source="AGENT"))
        StatusSegment.objects.bulk_create(rows)
        self.result.add("sesiones ACD")

    # ------------------------------------------------------------------ 7. comunicados
    def announcements(self) -> None:
        from apps.communications import services as comms
        from apps.communications.models import Announcement

        today = timezone.localdate()
        for item in ANNOUNCEMENTS:
            if Announcement.objects.filter(title=item["title"]).exists():
                continue
            data = {k: v for k, v in item.items() if k != "ack_days"}
            if item.get("ack_days"):
                data["ack_due_date"] = (today + timedelta(days=item["ack_days"])).isoformat()
            comms.create({**data, "publish": True}, user=self.hr_user)
            self.result.add("comunicados")

    # ------------------------------------------------------------------ 8. documentos del expediente
    def documents(self, p: Person) -> None:
        from apps.employees.digital_files import DocumentError, upload_document
        from apps.hcm.models import DigitalFileDocument, DocumentType

        emp = p.employee
        have = set(DigitalFileDocument.objects.filter(digital_file__employee=emp, is_current=True).values_list("document_type__code", flat=True))
        issued = emp.hire_date - timedelta(days=20)
        docs = {
            "NATIONAL_ID": (["Documento Único de Identidad", p.full_name.upper(), f"DUI {emp.national_id_number}",
                             f"Nacimiento: {emp.birth_date:%d/%m/%Y}"], {"issue_date": date(2022, 3, 15), "expiry_date": date(2030, 3, 15)}),
            "TAX_ID": (["Número de Identificación Tributaria", p.full_name.upper(), f"NIT {emp.national_id_number}",
                        "Homologado con el DUI"], {"issue_date": date(2022, 3, 15)}),
            "EMPLOYMENT_CONTRACT": (["Contrato individual de trabajo", p.full_name, f"Puesto: {p.title}",
                                     f"Ingreso: {emp.hire_date:%d/%m/%Y} · Salario: USD {emp.base_salary}"], {"issue_date": emp.hire_date}),
            "RESUME": (["Currículum vitae", p.full_name, f"Correo: {emp.work_email}", f"Teléfono: {emp.phone_number}"],
                       {"issue_date": issued}),
        }
        palette = [(31, 58, 95), (15, 76, 92), (91, 26, 50), (37, 40, 45), (31, 77, 43), (91, 124, 250)]
        for code, (lines, dates) in docs.items():
            if code in have:
                continue
            dtype = DocumentType.objects.filter(code=code, is_active=True).first()
            if dtype is None:
                continue
            upload = SimpleUploadedFile(f"{code.lower()}_{emp.employee_code}.png", _png(lines), content_type="image/png")
            try:
                with transaction.atomic():
                    upload_document(emp, dtype, upload, actor=self.hr_user.username, **dates)
                self.result.add("documentos del expediente")
            except DocumentError as exc:
                self.result.notes.append(f"{emp.employee_code} {code}: {exc}")
        if "PROFILE_PHOTO" not in have:
            dtype = DocumentType.objects.filter(code="PROFILE_PHOTO", is_active=True).first()
            if dtype is not None:
                avatar = _avatar(f"{p.first[0]}{p.last[0]}", palette[emp.employee_id % len(palette)])
                with transaction.atomic():
                    upload_document(emp, dtype, SimpleUploadedFile(f"foto_{emp.employee_code}.png", avatar, content_type="image/png"),
                                    actor=self.hr_user.username)
                self.result.add("fotografías")

    # ------------------------------------------------------------------ orquestación
    def run(self, *, documents: bool = True) -> Result:
        from apps.accounts.models import CustomUser

        people = _people()
        self.people = {p.key: p for p in people}
        hr = self.people["hr"]
        with transaction.atomic():
            self.log("Catálogo operativo…")
            self.catalog()
            self.log("Colaboradores, expedientes y Primera AP de horario…")
            # 1) La Generalista de RRHH se registra primero (sin actor) y su cuenta firma el resto de altas.
            self.employee(hr)
            self.account(hr)
            self.hr_user = hr.user
            self.approve_initial(hr)
            for p in people:
                if p is not hr:
                    self.employee(p)
                    self.approve_initial(p)
                    self.account(p)
            self.wfm_user = self.people["wfm"].user
            self.log("Cadena de mando y roster…")
            self.hierarchy(self.people)
            self.report_id_type = self._report_id_type()
            for p in people:
                self.roster(p)
                if p.team:
                    self.acd_membership(p)
            self.verify_hierarchy()
            self.log("General IDs (Payroll Tool y ACD por cuenta)…")
            for p in people:
                self.general_ids(p)
            self.log(f"Segmentos de la grilla del corte {CUTOFF_START:%d/%m} al {CUTOFF_END:%d/%m}…")
            for p in people:
                self.segments(p)
            self.log("Asistencia ACD de los días transcurridos…")
            for p in people:
                self.attendance(p)
            self.log("Comunicados del periódico virtual…")
            self.announcements()
        if documents:
            self.log("Documentos del expediente y fotografías…")
            for p in people:
                self.documents(p)
        self.result.people = people
        self.result.counts["cuentas de prueba activas"] = CustomUser.objects.filter(username__startswith=DEMO_USER_PREFIX).count()
        return self.result


# ======================================================================== archivo de accesos
REPRESENTATIVES = [
    ("Recursos Humanos (Generalista)", "hr"),
    ("Recursos Humanos (Planillas)", "payroll"),
    ("Workforce Management (Analista WFM)", "wfm"),
    ("Workforce Management (Tiempo real)", "rta"),
    ("Director de Operaciones", "director"),
    ("Operations Manager", "manager"),
    ("Supervisor de cuenta (Account Supervisor)", "sup_nova"),
    ("Team Manager", "tm_nova1"),
    ("Agente Tier 1", "tm_nova1_a1"),
    ("Agente Tier 2", "tm_nova1_a4"),
]


def write_access_file(result: Result, path: Path, *, login_url: str) -> Path:
    from apps.accounts.roles import Role

    by_key = {p.key: p for p in result.people}
    role_label = dict(Role.choices)
    now = timezone.localtime()
    lines = [
        "METAMORPH ERP — ACCESOS DE PRUEBA (Fase 26)",
        "=" * 72,
        f"Generado: {now:%d/%m/%Y %H:%M} (hora de El Salvador)",
        f"Ingreso: {login_url}",
        "",
        "CONFIDENCIAL: contraseñas en texto plano solo para la demostración. No comparta ni suba este archivo",
        "al repositorio (.gitignore lo excluye). Cada ejecución de «python manage.py demo_data» asigna",
        "contraseñas nuevas y reescribe este archivo.",
        "",
        "Sugerencia: abra cada perfil en una ventana de incógnito o en un perfil distinto del navegador; las",
        "pestañas de una misma ventana comparten la sesión.",
        "",
        "REPRESENTANTES POR ROL",
        "-" * 72,
    ]
    for label, key in REPRESENTATIVES:
        p = by_key[key]
        lines += [
            f"{label}",
            f"  Usuario:     {p.username}",
            f"  Contraseña:  {p.password}",
            f"  Rol en la app: {role_label.get(p.role, p.role)} · Puesto: {p.title}",
            f"  Colaborador: {p.full_name} ({p.employee.employee_code})",
            "",
        ]
    lines += [
        "Administrador: use su cuenta personal (no se crea un administrador de prueba).",
        "",
        "QUÉ VERIFICAR CON CADA PERFIL",
        "-" * 72,
        "• RRHH: expedientes, altas, acciones de personal (firma), planillas, comunicados y cumplimiento.",
        "• WFM: grilla de planificación del corte 10–24/11, adherencia, ciclos y cortes, tablero ACD.",
        "• Director / Manager / Supervisor / Team Manager: solo ven y gestionan su jerarquía (AP y grilla).",
        "• Agentes: portal del colaborador, horario, consola ACD, boleta diaria y acuse de comunicados.",
        "",
        "TODAS LAS CUENTAS DE PRUEBA",
        "-" * 72,
        f"{'Usuario':34} {'Contraseña':20} {'Rol':10} Puesto",
    ]
    for p in result.people:
        lines.append(f"{p.username:34} {p.password:20} {p.role:10} {p.title}")
    lines += ["", "Correos de prueba: dominio @" + DEMO_DOMAIN + " (no existe; no se envía correo real).", ""]
    path.write_text("\r\n".join(lines), encoding="utf-8")
    return path


def default_access_path() -> Path:
    return Path(settings.BASE_DIR).parent / "accesos_prueba.txt"
