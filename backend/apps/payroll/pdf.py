"""Fase 22 — Boletas de pago en PDF (generador PDF 1.4 nativo: Helvetica / WinAnsi, sin dependencias externas).

`payslip_pdf(content)` dibuja el MISMO contenido congelado de la boleta (o el de la vista previa / preliminar): datos
del colaborador y del periodo, cortes de asistencia, líneas por grupo, totales, líquido en letras, firmas y el sello
SHA-256. Los montos llevan el símbolo de la moneda del país de la planilla.
"""

from __future__ import annotations

import unicodedata
import zlib
from datetime import date
from decimal import Decimal

from apps.common.currency import money, symbol

PAGE_W, PAGE_H = 612, 792  # Carta
MARGIN = 40
GROUPS = [
    (("EARNING", "TIME_DISCOUNT"), "Devengado"),
    (("LEGAL",), "Retenciones de ley"),
    (("DEDUCTION",), "Otros descuentos autorizados"),
    (("EMPLOYER",), "Aportes patronales (no se descuentan)"),
    (("INFO",), "Insumos de tiempo (información)"),
]
SOURCE = {"SALARY": "Salario", "WEB_TIMER": "Web Timer", "ADHERENCE": "WFM / adherencia", "AP": "AP", "LAW": "Ley"}

# Anchos AFM de Helvetica (1/1000 em) para ASCII 32..126.
_W = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556,
      556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833,
      722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556,
      556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334,
      260, 334, 584]


def _char_w(ch: str) -> int:
    base = unicodedata.normalize("NFKD", ch)[:1] or ch
    o = ord(base)
    return _W[o - 32] if 32 <= o <= 126 else 556


def text_width(s: str, size: float, bold: bool = False) -> float:
    return sum(_char_w(c) for c in s) * size / 1000 * (1.06 if bold else 1)


def _esc(s: str) -> bytes:
    raw = s.encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def wrap(s: str, width: float, size: float, bold: bool = False) -> list[str]:
    out, line = [], ""
    for word in str(s or "").split():
        trial = f"{line} {word}".strip()
        if text_width(trial, size, bold) <= width or not line:
            line = trial
        else:
            out.append(line)
            line = word
    if line:
        out.append(line)
    return out or [""]


def _load_image(path) -> dict | None:
    """PNG → RGB sin pérdida (FlateDecode) sobre fondo blanco. None si el archivo no existe."""
    try:
        from PIL import Image

        im = Image.open(path)
    except (OSError, ImportError):
        return None
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        flat = Image.new("RGB", im.size, (255, 255, 255))
        flat.paste(im, mask=im.getchannel("A"))
        im = flat
    im = im.convert("RGB")
    return {"w": im.width, "h": im.height, "data": zlib.compress(im.tobytes(), 9)}


class Canvas:
    def __init__(self):
        self.pages: list[list[bytes]] = []
        self.images: dict[str, dict] = {}
        self.new_page()

    def image(self, key: str, img: dict, x: float, y: float, w: float, h: float):
        """Dibuja una imagen registrada como XObject (/Im…) en (x, y) con tamaño w × h puntos."""
        self.images.setdefault(key, img)
        self.ops.append(b"q %.2f 0 0 %.2f %.2f %.2f cm /%s Do Q" % (w, h, x, y, key.encode()))

    def new_page(self):
        self.ops: list[bytes] = []
        self.pages.append(self.ops)
        self.y = PAGE_H - MARGIN

    def text(self, x: float, y: float, s: str, size: float = 9, bold: bool = False, align: str = "left", gray: float = 0):
        if align == "right":
            x -= text_width(s, size, bold)
        elif align == "center":
            x -= text_width(s, size, bold) / 2
        font = b"/F2" if bold else b"/F1"
        self.ops.append(b"%.3f g BT %s %.1f Tf %.2f %.2f Td (%s) Tj ET" % (gray, font, size, x, y, _esc(s)))

    def line(self, x1, y1, x2, y2, width: float = 0.5, gray: float = 0.6):
        self.ops.append(b"%.3f G %.2f w %.2f %.2f m %.2f %.2f l S" % (gray, width, x1, y1, x2, y2))

    def rect(self, x, y, w, h, fill: float = 0.93):
        self.ops.append(b"%.3f g %.2f %.2f %.2f %.2f re f" % (fill, x, y, w, h))

    def ensure(self, needed: float):
        if self.y - needed < MARGIN + 30:
            self.new_page()

    def render(self, footer=None) -> bytes:
        objects: list[bytes] = []

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        catalog = add(b"")  # se completa al final
        pages_id = add(b"")
        f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        xobjects = b""
        for key, img in self.images.items():
            n = add(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB /BitsPerComponent 8 "
                    b"/Filter /FlateDecode /Length %d >>\nstream\n%s\nendstream" % (img["w"], img["h"], len(img["data"]), img["data"]))
            xobjects += b"/%s %d 0 R " % (key.encode(), n)
        resources = b"/Font << /F1 %d 0 R /F2 %d 0 R >>" % (f1, f2) + (b" /XObject << %s>>" % xobjects if xobjects else b"")
        kids = []
        total = len(self.pages)
        for i, ops in enumerate(self.pages, 1):
            if footer:
                self.ops = ops
                footer(self, i, total)
            stream = zlib.compress(b"\n".join(ops))
            content = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n%s\nendstream" % (len(stream), stream))
            kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Resources << %s >> /Contents %d 0 R >>"
                            % (pages_id, PAGE_W, PAGE_H, resources, content)))
        objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id
        objects[pages_id - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), len(kids))
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for n, body in enumerate(objects, 1):
            offsets.append(len(out))
            out += b"%d 0 obj\n%s\nendobj\n" % (n, body)
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
        for off in offsets:
            out += b"%010d 00000 n \n" % off
        out += b"trailer\n<< /Size %d /Root %d 0 R /Info << /Producer (Metamorph ERP) >> >>\nstartxref\n%d\n%%%%EOF\n" % (
            len(objects) + 1, catalog, xref)
        return bytes(out)


_LOGO_CACHE: dict = {}


def doc_logo() -> dict | None:
    """Logo de documentos (apps/system/static/brand/doc_header_logo_pdf.png, `manage.py brand_assets`)."""
    if "doc" not in _LOGO_CACHE:
        from apps.system.brand import PDF_LOGO

        _LOGO_CACHE["doc"] = _load_image(PDF_LOGO)
    return _LOGO_CACHE["doc"]


def _d(value) -> str:
    if not value:
        return "—"
    s = str(value)[:10]
    try:
        return date.fromisoformat(s).strftime("%d/%m/%Y")
    except ValueError:
        return s


def _num(value, digits: int = 2) -> str:
    if value in (None, ""):
        return ""
    return f"{Decimal(str(value)):,.{digits}f}"


def _hours(value) -> str:
    """Horas decimales → HH:MM:SS (formato oficial de las boletas)."""
    secs = int(round(Decimal(str(value)) * 3600))
    sign = "-" if secs < 0 else ""
    secs = abs(secs)
    return f"{sign}{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"


def _qty(line: dict) -> str:
    q = line.get("quantity")
    if q in (None, ""):
        return ""
    if line.get("unit") == "horas":
        return f"{_hours(q)} h"
    return f"{_num(q)} {line.get('unit') or ''}".strip()


def _rate(line: dict) -> str:
    r = line.get("rate")
    if r in (None, ""):
        return ""
    if line.get("kind") in ("LEGAL", "EMPLOYER"):
        return f"{Decimal(str(r)) * 100:.2f} %"
    return _num(r, 4)


def payslip_pdf(content: dict, *, content_hash: str | None = None, preliminary: bool = False, company: str = "Metamorph ERP") -> bytes:
    from apps.payroll.settlements import amount_in_words

    c = Canvas()
    cur = content.get("currency") or "USD"
    emp, period, totals = content.get("employee") or {}, content.get("period") or {}, content.get("totals") or {}
    right = PAGE_W - MARGIN

    # ---- encabezado: logo corporativo para fondos blancos (doc_header_logo, Fase 23)
    title = "BOLETA DE PAGO" + (" PRELIMINAR" if preliminary else "")
    logo = doc_logo()
    if logo:
        h = 34
        c.image("ImLogo", logo, MARGIN, c.y - h + 6, h * logo["w"] / logo["h"], h)
        c.y -= 34
        c.text(MARGIN, c.y - 6, title, 12, True, gray=0.15)
        c.y += 18
    else:
        c.text(MARGIN, c.y - 4, company, 15, True)
        c.text(MARGIN, c.y - 22, title, 12, True, gray=0.15)
    c.text(right, c.y - 4, f"Folio: {content.get('folio') or 'se asigna al cerrar'}", 9, True, "right")
    c.text(right, c.y - 17, f"Planilla: {content.get('payroll_code') or '—'}", 9, align="right")
    c.text(right, c.y - 30, f"Moneda: {cur} ({symbol(cur)})", 9, align="right")
    c.y -= 40
    c.text(MARGIN, c.y, f"{period.get('frequency_label') or ''} · {_d(period.get('start'))} al {_d(period.get('end'))} · "
                        f"pago {_d(period.get('payment_date'))}", 9, gray=0.3)
    c.y -= 8
    if preliminary:
        c.y -= 6
        c.rect(MARGIN, c.y - 14, right - MARGIN, 18, 0.96)
        c.text(MARGIN + 6, c.y - 9, "Vista previa del cálculo en curso: NO es el monto final. Reporte cualquier excepción antes del cierre.",
               8.5, True, gray=0.45)
        c.y -= 20
    c.line(MARGIN, c.y, right, c.y, 1, 0.2)
    c.y -= 16

    # ---- datos del colaborador (dos columnas)
    windows = ", ".join(f"{_d(w.get('start'))}–{_d(w.get('end'))}" for w in period.get("attendance_windows") or []) or "—"
    who = [("Colaborador", f"{emp.get('name') or ''} ({emp.get('code') or ''})"), ("Documento", emp.get("national_id") or "—"),
           ("Departamento", emp.get("cost_center_name") or emp.get("cost_center") or "—"),
           ("Salario base mensual", money(content.get("base_salary"), cur)),
           ("Días pagados (equivalentes)", _num(content.get("paid_days"))), ("Asistencia (cortes)", windows)]
    col_w = (right - MARGIN) / 2
    for i in range(0, len(who), 2):
        for j, (label, value) in enumerate(who[i:i + 2]):
            x = MARGIN + j * col_w
            c.text(x, c.y, label.upper(), 6.5, True, gray=0.45)
            c.text(x, c.y - 10, wrap(value, col_w - 10, 9)[0], 9)
        c.y -= 24
    c.y -= 4

    # ---- líneas por grupo
    cols = [MARGIN, MARGIN + 250, MARGIN + 340, MARGIN + 420, right]  # concepto | cantidad | valor | origen | monto
    lines = content.get("lines") or []
    for kinds, group_title in GROUPS:
        rows = [x for x in lines if x.get("kind") in kinds]
        if not rows:
            continue
        c.ensure(40)
        c.rect(MARGIN, c.y - 4, right - MARGIN, 15, 0.9)
        c.text(MARGIN + 4, c.y, group_title, 9, True)
        is_info = kinds == ("INFO",)
        c.text(cols[1], c.y, "Cantidad", 7.5, True, gray=0.3)
        c.text(cols[2], c.y, "Valor / tasa", 7.5, True, gray=0.3)
        c.text(cols[3], c.y, "Origen", 7.5, True, gray=0.3)
        if not is_info:
            c.text(right - 4, c.y, f"Monto ({symbol(cur)})", 7.5, True, "right", gray=0.3)
        c.y -= 16
        for x in rows:
            label_lines = wrap(x.get("label") or "", cols[1] - cols[0] - 8, 8.5)
            note_lines = wrap(x.get("notes") or "", cols[1] - cols[0] - 8, 7) if x.get("notes") else []
            needed = 11 * len(label_lines) + 9 * len(note_lines) + 4
            c.ensure(needed)
            top = c.y
            for k, t in enumerate(label_lines):
                c.text(MARGIN + 4, c.y, t, 8.5)
                c.y -= 11
            for t in note_lines:
                c.text(MARGIN + 10, c.y + 2, t, 7, gray=0.45)
                c.y -= 9
            origin = f"AP {x['folio_ap']}" if x.get("folio_ap") else SOURCE.get(x.get("source") or "", x.get("source") or "")
            c.text(cols[1], top, _qty(x), 8.5)
            c.text(cols[2], top, _rate(x), 8.5)
            c.text(cols[3], top, origin[:22], 7.5, gray=0.35)
            if not is_info:
                amount = Decimal(str(x.get("amount") or 0))
                c.text(right - 4, top, _num(amount), 8.5, align="right", gray=0.55 if amount < 0 else 0)
            c.line(MARGIN, c.y + 6, right, c.y + 6, 0.3, 0.85)
            c.y -= 2
        c.y -= 8

    # ---- totales
    c.ensure(110)
    c.line(MARGIN, c.y + 4, right, c.y + 4, 1, 0.2)
    c.y -= 10
    for label, key in (("Total devengado", "gross"), ("Total descuentos", "deductions")):
        c.text(right - 150, c.y, label, 9.5)
        c.text(right - 4, c.y, money(totals.get(key), cur), 9.5, align="right")
        c.y -= 15
    c.rect(right - 230, c.y - 6, 230, 20, 0.88)
    c.text(right - 222, c.y, "LÍQUIDO A RECIBIR", 10.5, True)
    c.text(right - 6, c.y, money(totals.get("net"), cur), 11, True, "right")
    c.y -= 22
    try:
        words = amount_in_words(Decimal(str(totals.get("net") or 0)), cur)
        for t in wrap(f"Son: {words}", right - MARGIN, 8):
            c.text(MARGIN, c.y, t, 8, gray=0.3)
            c.y -= 10
    except (ArithmeticError, ValueError):
        pass

    # ---- firmas
    c.ensure(70)
    c.y -= 40
    for i, label in enumerate(("Firma del colaborador", "Fecha de recibido")):
        x = MARGIN + i * ((right - MARGIN) / 2 + 10)
        c.line(x, c.y, x + 200, c.y, 0.6, 0.3)
        c.text(x, c.y - 11, label, 8, gray=0.35)
    c.y -= 26
    if content_hash:
        c.text(MARGIN, c.y, f"Sello SHA-256 del contenido: {content_hash}", 6.5, gray=0.45)

    def footer(cv: Canvas, page: int, total: int):
        cv.text(MARGIN, 22, f"{company} · Boleta de pago{' preliminar' if preliminary else ''} · {emp.get('code') or ''}", 7, gray=0.5)
        cv.text(right, 22, f"Página {page} de {total}", 7, align="right", gray=0.5)

    return c.render(footer)


def filename(content: dict, preliminary: bool = False) -> str:
    code = (content.get("employee") or {}).get("code") or "colaborador"
    folio = content.get("folio") or (content.get("payroll_code") or "planilla")
    return f"boleta{'-preliminar' if preliminary else ''}-{folio}-{code}.pdf".replace("/", "-").replace(" ", "_")
