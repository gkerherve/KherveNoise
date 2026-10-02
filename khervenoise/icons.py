"""Programmatically drawn icons — no image files ship with the app.

QPainter draws every toolbar icon onto a transparent pixmap; ``app_icon``
is the KherveNoise mark: a KherveFitting-green tile with a noisy trace that
turns into a smooth peak.

Copyright (C) 2026 Gwilherm Kerherve
Licensed under the GNU General Public License v3.0 (see LICENSE).
"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QIcon, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap, QPolygonF)

from . import GREEN_HEX, OPP_HEX

_SIZE = 32
FG = QColor("#2b2f36")
GREEN = QColor(GREEN_HEX)
OPP = QColor(OPP_HEX)
BLUE = QColor("#2f6fb3")
EXCEL = QColor("#217346")
AMBER = QColor("#d98a00")


def _canvas(size=_SIZE):
    px = QPixmap(size, size)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)
    p.scale(size / 32.0, size / 32.0)
    return px, p


def _pen(color=FG, w=2.0):
    pen = QPen(color, w)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _icon(draw):
    icon = QIcon()
    for sz in (16, 24, 32, 48, 64):
        px, p = _canvas(sz)
        draw(p)
        p.end()
        icon.addPixmap(px)
    return icon


def _peak_path(x0, x1, base, height, n=40, centre=None, width=None):
    centre = (x0 + x1) / 2 if centre is None else centre
    width = (x1 - x0) / 6 if width is None else width
    path = QPainterPath()
    for i in range(n + 1):
        x = x0 + (x1 - x0) * i / n
        y = base - height * math.exp(-0.5 * ((x - centre) / width) ** 2)
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    return path


def _noisy_path(x0, x1, base, height, amp=1.6, n=22, seed=3):
    centre, width = (x0 + x1) / 2, (x1 - x0) / 6
    path = QPainterPath()
    for i in range(n + 1):
        x = x0 + (x1 - x0) * i / n
        jitter = amp * math.sin(i * 2.7 + seed) * (1 if i % 2 else -1)
        y = base - height * math.exp(-0.5 * ((x - centre) / width) ** 2) + jitter
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    return path


def _doc(p, color=FG, fill=QColor("#ffffff")):
    path = QPainterPath()
    path.moveTo(7, 3); path.lineTo(20, 3); path.lineTo(26, 9)
    path.lineTo(26, 29); path.lineTo(7, 29); path.closeSubpath()
    p.setPen(_pen(color, 1.6)); p.setBrush(fill); p.drawPath(path)
    p.drawLine(QPointF(20, 3), QPointF(20, 9)); p.drawLine(QPointF(20, 9), QPointF(26, 9))


def _badge(p, text, color, rect=QRectF(13, 17, 18, 13)):
    p.setPen(Qt.NoPen); p.setBrush(color)
    p.drawRoundedRect(rect, 2.5, 2.5)
    f = QFont("Helvetica"); f.setPixelSize(8 if len(text) > 2 else 9); f.setBold(True)
    p.setFont(f); p.setPen(QColor("white"))
    p.drawText(rect, Qt.AlignCenter, text)


def _arrow_down(p, x, y0, y1, color=FG):
    p.setPen(_pen(color, 2.2))
    p.drawLine(QPointF(x, y0), QPointF(x, y1))
    p.drawLine(QPointF(x - 4, y1 - 4), QPointF(x, y1))
    p.drawLine(QPointF(x + 4, y1 - 4), QPointF(x, y1))


# ---------------------------------------------------------------- app icon
def app_icon_pixmap(sz: int) -> QPixmap:
    px = QPixmap(sz, sz)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)
    grad = QLinearGradient(0, 0, 0, sz)
    grad.setColorAt(0.0, QColor("#6fd3b6"))
    grad.setColorAt(1.0, QColor("#3a9c80"))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(grad))
    r = sz * 0.18
    p.drawRoundedRect(QRectF(0, 0, sz, sz), r, r)
    p.scale(sz / 64.0, sz / 64.0)
    if sz >= 40:
        f = QFont("Georgia"); f.setPixelSize(26); f.setBold(True)
        p.setFont(f); p.setPen(QColor("white"))
        p.drawText(QRectF(0, 1, 64, 30), Qt.AlignCenter, "KN")
    base, top = (54, 26) if sz >= 40 else (50, 36)
    noisy = _noisy_path(6, 34, base, top, amp=3.2, n=14)
    p.setPen(_pen(QColor(255, 255, 255, 150), 2.4)); p.setBrush(Qt.NoBrush)
    p.drawPath(noisy)
    smooth = _peak_path(30, 58, base, top, centre=44, width=4.5)
    p.setPen(_pen(QColor("white"), 3.4))
    p.drawPath(smooth)
    p.end()
    return px


def app_icon() -> QIcon:
    icon = QIcon()
    for sz in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(app_icon_pixmap(sz))
    return icon


# ------------------------------------------------------------------ file
def new_instance():
    def d(p):
        p.setPen(_pen(FG, 1.6)); p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(QRectF(3, 7, 18, 15), 2, 2)
        p.setBrush(QColor("#eaf7f2"))
        p.drawRoundedRect(QRectF(10, 13, 18, 15), 2, 2)
        p.setPen(_pen(GREEN, 2.6))
        p.drawLine(QPointF(19, 17), QPointF(19, 25)); p.drawLine(QPointF(15, 21), QPointF(23, 21))
    return _icon(d)


def open_file():
    def d(p):
        p.setPen(_pen(QColor("#a87a12"), 1.6)); p.setBrush(QColor("#f6c75a"))
        path = QPainterPath()
        path.moveTo(3, 9); path.lineTo(11, 9); path.lineTo(14, 12); path.lineTo(27, 12)
        path.lineTo(27, 26); path.lineTo(3, 26); path.closeSubpath()
        p.drawPath(path)
        p.setBrush(QColor("#fbd97f"))
        front = QPolygonF([QPointF(6, 15), QPointF(30, 15), QPointF(27, 26), QPointF(3, 26)])
        p.drawPolygon(front)
    return _icon(d)


def save():
    def d(p):
        p.setPen(_pen(QColor("#1d3f66"), 1.6)); p.setBrush(BLUE)
        p.drawRoundedRect(QRectF(4, 4, 24, 24), 2.5, 2.5)
        p.setBrush(QColor("white")); p.drawRect(QRectF(9, 4, 14, 9))
        p.setBrush(QColor("#dfe8f3")); p.drawRect(QRectF(8, 17, 16, 11))
        p.setPen(_pen(GREEN, 1.8)); p.setBrush(Qt.NoBrush)
        p.drawPath(_peak_path(9, 23, 26, 7))
    return _icon(d)


def import_excel():
    def d(p):
        _doc(p)
        p.setPen(_pen(QColor("#9aa3ad"), 1.0))
        for y in (12, 16, 20):
            p.drawLine(QPointF(10, y), QPointF(23, y))
        _badge(p, "XLS", EXCEL)
    return _icon(d)


def import_data():
    def d(p):
        _doc(p)
        p.setPen(_pen(GREEN, 1.8)); p.setBrush(Qt.NoBrush)
        p.drawPath(_noisy_path(9, 24, 18, 9, amp=1.0, n=14))
        _badge(p, "TXT", BLUE)
    return _icon(d)


def import_vamas():
    def d(p):
        _doc(p)
        p.setPen(_pen(GREEN, 1.8)); p.setBrush(Qt.NoBrush)
        p.drawPath(_peak_path(9, 24, 17, 9))
        _badge(p, "VMS", OPP)
    return _icon(d)


def export_kfit():
    def d(p):
        p.setPen(_pen(EXCEL, 1.6)); p.setBrush(QColor("#e7f3ec"))
        p.drawRoundedRect(QRectF(3, 5, 20, 22), 2, 2)
        p.setPen(_pen(QColor("#86b89c"), 1.0))
        for y in (11, 16, 21):
            p.drawLine(QPointF(5, y), QPointF(21, y))
        p.drawLine(QPointF(11, 6), QPointF(11, 26))
        p.setPen(_pen(GREEN, 2.6))
        p.drawLine(QPointF(17, 16), QPointF(29, 16))
        p.drawLine(QPointF(25, 12), QPointF(29, 16)); p.drawLine(QPointF(25, 20), QPointF(29, 16))
    return _icon(d)


def export_csv():
    def d(p):
        _doc(p)
        _badge(p, "CSV", QColor("#5b6470"))
        _arrow_down(p, 14, 6, 15, GREEN)
    return _icon(d)


def save_figure():
    def d(p):
        p.setPen(_pen(FG, 1.6)); p.setBrush(QColor("white"))
        p.drawRoundedRect(QRectF(3, 5, 26, 20), 2, 2)
        p.setPen(_pen(QColor("#9aa3ad"), 1.2))
        p.drawLine(QPointF(7, 21), QPointF(26, 21)); p.drawLine(QPointF(7, 9), QPointF(7, 21))
        p.setPen(_pen(QColor("#555"), 1.0)); p.setBrush(Qt.NoBrush)
        p.drawPath(_noisy_path(8, 26, 20, 10, amp=1.0, n=16))
        p.setPen(_pen(GREEN, 2.2))
        p.drawPath(_peak_path(8, 26, 20, 10))
        p.setPen(_pen(FG, 1.6))
        p.drawLine(QPointF(12, 29), QPointF(20, 29))
    return _icon(d)


def exit_app():
    def d(p):
        p.setPen(_pen(FG, 1.8)); p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(4, 4, 14, 24), 1.5, 1.5)
        p.setPen(_pen(OPP, 2.4))
        p.drawLine(QPointF(12, 16), QPointF(28, 16))
        p.drawLine(QPointF(23, 11), QPointF(28, 16)); p.drawLine(QPointF(23, 21), QPointF(28, 16))
    return _icon(d)


# --------------------------------------------------------------- denoise
def apply_denoise():
    def d(p):
        p.setPen(_pen(QColor("#8a9099"), 1.4)); p.setBrush(Qt.NoBrush)
        p.drawPath(_noisy_path(3, 29, 25, 17, amp=2.2, n=20))
        p.setPen(_pen(GREEN, 3.0))
        p.drawPath(_peak_path(3, 29, 25, 17))
    return _icon(d)


def auto_params():
    def d(p):
        p.setPen(_pen(GREEN, 2.0)); p.setBrush(Qt.NoBrush)
        p.drawPath(_peak_path(3, 23, 27, 14))
        star = QPainterPath()
        cx, cy, r1, r2 = 23, 9, 7, 2.6
        for i in range(8):
            a = math.pi / 4 * i - math.pi / 2
            r = r1 if i % 2 == 0 else r2
            pt = QPointF(cx + r * math.cos(a), cy + r * math.sin(a))
            star.moveTo(pt) if i == 0 else star.lineTo(pt)
        star.closeSubpath()
        p.setPen(_pen(AMBER, 1.2)); p.setBrush(QColor("#ffcc33")); p.drawPath(star)
    return _icon(d)


def create_spectra():
    def d(p):
        for i, off in enumerate((0, 4, 8)):
            p.setPen(_pen(FG, 1.3)); p.setBrush(QColor("white") if i < 2 else QColor("#eaf7f2"))
            p.drawRoundedRect(QRectF(3 + off, 3 + off, 17, 17), 1.5, 1.5)
        p.setPen(_pen(GREEN, 1.8)); p.setBrush(Qt.NoBrush)
        p.drawPath(_peak_path(12, 27, 25, 9))
        p.setPen(_pen(GREEN, 2.6))
        p.drawLine(QPointF(26, 3), QPointF(26, 11)); p.drawLine(QPointF(22, 7), QPointF(30, 7))
    return _icon(d)


def delete_spectrum():
    def d(p):
        p.setPen(_pen(FG, 1.6)); p.setBrush(QColor("white"))
        p.drawRoundedRect(QRectF(4, 6, 20, 20), 2, 2)
        p.setPen(_pen(QColor("#8a9099"), 1.4)); p.setBrush(Qt.NoBrush)
        p.drawPath(_peak_path(6, 22, 23, 11))
        p.setPen(_pen(OPP, 2.8))
        p.drawLine(QPointF(19, 17), QPointF(29, 27)); p.drawLine(QPointF(29, 17), QPointF(19, 27))
    return _icon(d)


# ------------------------------------------------------------------ view
def _magnifier(p, sign=None, box=False):
    if box:
        pen = _pen(GREEN, 1.4); pen.setStyle(Qt.DashLine)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(2, 2, 16, 13))
    p.setPen(_pen(FG, 2.0)); p.setBrush(QColor(255, 255, 255, 200))
    p.drawEllipse(QPointF(14, 14), 8, 8)
    p.setPen(_pen(FG, 3.2))
    p.drawLine(QPointF(20, 20), QPointF(28, 28))
    if sign:
        p.setPen(_pen(FG, 2.0))
        p.drawLine(QPointF(10, 14), QPointF(18, 14))
        if sign == "+":
            p.drawLine(QPointF(14, 10), QPointF(14, 18))


def zoom_box():
    return _icon(lambda p: _magnifier(p, box=True))


def zoom_out():
    return _icon(lambda p: _magnifier(p, "-"))


def zoom_reset():
    def d(p):
        p.setPen(_pen(FG, 1.6)); p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(5, 5, 22, 22))
        p.setPen(_pen(GREEN, 2.2))
        for (x, y, dx, dy) in ((5, 5, 1, 1), (27, 5, -1, 1), (5, 27, 1, -1), (27, 27, -1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + 6 * dx, y)); p.drawLine(QPointF(x, y), QPointF(x, y + 6 * dy))
    return _icon(d)


def y_zoom(sign):
    def d(p):
        p.setPen(_pen(FG, 2.0))
        p.drawLine(QPointF(9, 4), QPointF(9, 28))
        p.drawLine(QPointF(5, 8), QPointF(9, 4)); p.drawLine(QPointF(13, 8), QPointF(9, 4))
        p.drawLine(QPointF(5, 24), QPointF(9, 28)); p.drawLine(QPointF(13, 24), QPointF(9, 28))
        p.setPen(_pen(GREEN, 3.0))
        p.drawLine(QPointF(17, 16), QPointF(28, 16))
        if sign == "+":
            p.drawLine(QPointF(22.5, 10.5), QPointF(22.5, 21.5))
    return _icon(d)


# ------------------------------------------------------------- help / AI
def references():
    def d(p):
        p.setPen(_pen(QColor("#6b3d0e"), 1.4)); p.setBrush(QColor("#c98a3c"))
        p.drawRoundedRect(QRectF(5, 4, 20, 24), 2, 2)
        p.setBrush(QColor("#fff8ec")); p.drawRect(QRectF(9, 4, 16, 22))
        p.setPen(_pen(QColor("#9aa3ad"), 1.0))
        for y in (9, 13, 17, 21):
            p.drawLine(QPointF(12, y), QPointF(22, y))
        p.setPen(_pen(GREEN, 2.0))
        p.drawLine(QPointF(27, 3), QPointF(27, 12))
    return _icon(d)


def user_guide():
    def d(p):
        p.setPen(_pen(BLUE, 1.6)); p.setBrush(QColor("#e8f0fa"))
        p.drawEllipse(QPointF(16, 16), 13, 13)
        f = QFont("Georgia"); f.setPixelSize(19); f.setBold(True)
        p.setFont(f); p.setPen(BLUE)
        p.drawText(QRectF(0, 0, 32, 32), Qt.AlignCenter, "?")
    return _icon(d)


def about():
    def d(p):
        p.setPen(_pen(GREEN, 1.6)); p.setBrush(QColor("#eaf7f2"))
        p.drawEllipse(QPointF(16, 16), 13, 13)
        f = QFont("Georgia"); f.setPixelSize(18); f.setBold(True); f.setItalic(True)
        p.setFont(f); p.setPen(QColor("#2f8a70"))
        p.drawText(QRectF(0, 0, 32, 32), Qt.AlignCenter, "i")
    return _icon(d)


def mcp():
    def d(p):
        p.setPen(_pen(QColor("#a4512f"), 1.6)); p.setBrush(QColor("#f3e3d9"))
        p.drawRoundedRect(QRectF(5, 7, 22, 18), 5, 5)
        p.setPen(Qt.NoPen); p.setBrush(QColor("#c15f3c"))
        p.drawEllipse(QPointF(12, 16), 2.6, 2.6); p.drawEllipse(QPointF(20, 16), 2.6, 2.6)
        p.setPen(_pen(QColor("#a4512f"), 1.6))
        p.drawLine(QPointF(16, 3), QPointF(16, 7))
        p.drawLine(QPointF(5, 16), QPointF(2, 16)); p.drawLine(QPointF(27, 16), QPointF(30, 16))
        p.drawLine(QPointF(11, 25), QPointF(9, 29)); p.drawLine(QPointF(21, 25), QPointF(23, 29))
    return _icon(d)


def update():
    def d(p):
        p.setPen(_pen(GREEN, 2.6)); p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(5, 5, 22, 22), 30 * 16, 280 * 16)
        p.drawLine(QPointF(27, 6), QPointF(26.5, 12.5)); p.drawLine(QPointF(20, 12), QPointF(26.5, 12.5))
    return _icon(d)


def import_instrument():
    """A hemispherical analyser over a document — vendor instrument files."""
    def d(p):
        _doc(p)
        p.setPen(_pen(BLUE, 2.0)); p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(9, 9, 15, 15), 0, 180 * 16)
        p.drawArc(QRectF(12.5, 12.5, 8, 8), 0, 180 * 16)
        p.setPen(_pen(GREEN, 1.6))
        p.drawPath(_peak_path(9, 24, 27, 4))
        _badge(p, "INS", AMBER, QRectF(15, 2, 16, 10))
    return _icon(d)


def import_folder():
    def d(p):
        p.setPen(_pen(QColor("#a87a12"), 1.6)); p.setBrush(QColor("#f6c75a"))
        path = QPainterPath()
        path.moveTo(3, 8); path.lineTo(11, 8); path.lineTo(14, 11); path.lineTo(29, 11)
        path.lineTo(29, 27); path.lineTo(3, 27); path.closeSubpath()
        p.drawPath(path)
        p.setPen(_pen(GREEN, 2.0)); p.setBrush(Qt.NoBrush)
        for off in (0, 4):
            p.drawPath(_peak_path(7 + off, 22 + off, 25 - off, 7))
    return _icon(d)
