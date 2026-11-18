"""Combiné d'instrumentation, dessiné entièrement avec QPainter sur un canevas de 1000 x 400."""
from __future__ import annotations

import math
import time
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..middleware import VehicleState
from . import theme as t

W, H = 1000, 400
CENTER = QPointF(500, 205)
RADIUS = 150
SPEED_MAX = 180
ARC_START, ARC_SPAN = 225, -270
ALERT_PRIORITY = {"critical": 0, "warning": 1, "info": 2}


class ClusterWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = VehicleState()
        self.setMinimumSize(600, 260)

    def set_state(self, state: VehicleState) -> None:
        self._state = state
        self.update()

    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = min(self.width() / W, self.height() / H)
        p.translate((self.width() - W * scale) / 2, (self.height() - H * scale) / 2)
        p.scale(scale, scale)

        s = self._state
        blink_on = int(time.monotonic() * 3) % 2 == 0
        self._background(p)
        self._top_bar(p, s, blink_on)
        self._speed_gauge(p, s)
        self._gear_row(p, s)
        self._power_panel(p, s)
        self._battery_panel(p, s)
        self._alert_banner(p, s)
        p.end()

    # ------------------------------------------------------------------
    def _text(self, p, rect, text, size, colour, bold=False, align=Qt.AlignmentFlag.AlignCenter):
        p.setFont(t.font(size, bold))
        p.setPen(t.color(colour))
        p.drawText(QRectF(*rect), align, text)

    def _background(self, p: QPainter) -> None:
        grad = QLinearGradient(0, 0, 0, H)
        grad.setColorAt(0, t.color("#0C121B"))
        grad.setColorAt(1, t.color("#030508"))
        p.setPen(QPen(t.color(t.BORDER), 1.5))
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(2, 2, W - 4, H - 4), 30, 30)

    def _top_bar(self, p: QPainter, s: VehicleState, blink_on: bool) -> None:
        self._arrow(p, 60, 40, left=True, on=s.left_turn and blink_on)
        self._arrow(p, 940, 40, left=False, on=s.right_turn and blink_on)
        self._text(p, (400, 18, 200, 36), datetime.now().strftime("%H:%M"), 26, t.TEXT, True)
        if s.low_beam:
            self._badge(p, 120, 24, "Croisement", t.GREEN)
        if s.high_beam:
            self._badge(p, 240, 24, "Route", t.BLUE)
        ready_colour = t.GREEN if s.ready else t.MUTED
        self._badge(p, 770, 24, "READY" if s.ready else "OFF", ready_colour)

    def _arrow(self, p, x, y, left, on) -> None:
        d = -1 if left else 1
        path = QPainterPath()
        path.moveTo(x + d * 22, y)
        path.lineTo(x, y - 16)
        path.lineTo(x, y - 7)
        path.lineTo(x - d * 18, y - 7)
        path.lineTo(x - d * 18, y + 7)
        path.lineTo(x, y + 7)
        path.lineTo(x, y + 16)
        path.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(t.color(t.GREEN) if on else t.color("#1A2230"))
        p.drawPath(path)

    def _badge(self, p, x, y, text, colour) -> None:
        rect = QRectF(x, y, 105, 28)
        p.setPen(QPen(t.color(colour), 1.5))
        p.setBrush(t.color(colour, 30))
        p.drawRoundedRect(rect, 14, 14)
        self._text(p, (x, y, 105, 28), text, 14, colour, True)

    def _point_at(self, value: float, radius: float) -> QPointF:
        angle = math.radians(ARC_START + ARC_SPAN * value / SPEED_MAX)
        return QPointF(CENTER.x() + radius * math.cos(angle), CENTER.y() - radius * math.sin(angle))

    def _speed_gauge(self, p: QPainter, s: VehicleState) -> None:
        rect = QRectF(CENTER.x() - RADIUS, CENTER.y() - RADIUS, 2 * RADIUS, 2 * RADIUS)
        pen = QPen(t.color("#182130"), 14)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(rect, ARC_START * 16, ARC_SPAN * 16)

        valid = s.is_valid("ESP_Speed")
        speed = s.speed_kmh if valid else 0.0
        if speed > 0.5:
            pen.setColor(t.color(t.ACCENT if s.ready else t.ACCENT_DIM))
            p.setPen(pen)
            span = ARC_SPAN * min(speed, SPEED_MAX) / SPEED_MAX
            p.drawArc(rect, ARC_START * 16, int(span * 16))

        for value in range(0, SPEED_MAX + 1, 10):
            major = value % 40 == 0
            p.setPen(QPen(t.color(t.MUTED if major else "#2A3545"), 2 if major else 1))
            p.drawLine(self._point_at(value, RADIUS - 16), self._point_at(value, RADIUS - (28 if major else 22)))
            if major:
                pt = self._point_at(value, RADIUS - 46)
                self._text(p, (pt.x() - 20, pt.y() - 10, 40, 20), str(value), 13, t.MUTED)

        if valid:
            colour = t.TEXT if s.ready else t.MUTED
            self._text(p, (380, 140, 240, 100), f"{speed:.0f}", 86, colour, True)
        else:
            self._text(p, (380, 140, 240, 100), "---", 70, t.RED, True)
        self._text(p, (400, 232, 200, 24), "km/h", 17, t.MUTED)
        if not s.ready:
            self._text(p, (360, 258, 280, 22), "Appuyez sur Démarrer", 14, t.MUTED)

    def _gear_row(self, p: QPainter, s: VehicleState) -> None:
        valid = s.is_valid("VCU_Status")
        for i, gear in enumerate("PRND"):
            active = valid and s.gear == gear
            x = 420 + i * 40
            self._text(p, (x, 296, 40, 36), gear, 28 if active else 22,
                       t.ACCENT if active else "#3A4656", active)

    def _power_panel(self, p: QPainter, s: VehicleState) -> None:
        self._text(p, (60, 150, 240, 24), "PUISSANCE", 13, t.MUTED, align=Qt.AlignmentFlag.AlignLeft)
        valid = s.is_valid("VCU_Status")
        power = s.power_kw if valid else 0.0
        x0, width, y = 60, 240, 190
        zero = x0 + width * 50 / 210  # échelle de -50 à +160 kW
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(t.color("#182130"))
        p.drawRoundedRect(QRectF(x0, y, width, 12), 6, 6)
        if power > 0:
            p.setBrush(t.color(t.ACCENT))
            p.drawRoundedRect(QRectF(zero, y, width * min(power, 160) / 210, 12), 6, 6)
        elif power < 0:
            w = width * min(-power, 50) / 210
            p.setBrush(t.color(t.GREEN))
            p.drawRoundedRect(QRectF(zero - w, y, w, 12), 6, 6)
        p.setBrush(t.color(t.TEXT))
        p.drawRect(QRectF(zero - 1, y - 4, 2, 20))
        label = "Recharge" if power < 0 else "Traction"
        value = f"{power:+.0f} kW" if valid else "-- kW"
        self._text(p, (60, 212, 240, 40), value, 30, t.TEXT, True, Qt.AlignmentFlag.AlignLeft)
        self._text(p, (60, 252, 240, 22), label, 14, t.MUTED, align=Qt.AlignmentFlag.AlignLeft)

    def _battery_panel(self, p: QPainter, s: VehicleState) -> None:
        self._text(p, (700, 150, 240, 24), "BATTERIE", 13, t.MUTED, align=Qt.AlignmentFlag.AlignRight)
        if not s.is_valid("BMS_Battery"):
            self._text(p, (700, 180, 240, 60), "--", 40, t.RED, True, Qt.AlignmentFlag.AlignRight)
            return
        soc = s.soc_pct
        colour = t.GREEN if soc >= 30 else t.ORANGE if soc >= 15 else t.RED
        self._text(p, (700, 172, 240, 50), f"{soc:.0f} %", 40, t.TEXT, True, Qt.AlignmentFlag.AlignRight)
        x, y, w, h = 760, 228, 170, 26
        p.setPen(QPen(t.color(t.MUTED), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(x, y, w, h), 6, 6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(t.color(t.MUTED))
        p.drawRoundedRect(QRectF(x + w + 2, y + 8, 6, 10), 2, 2)
        p.setBrush(t.color(colour))
        p.drawRoundedRect(QRectF(x + 4, y + 4, (w - 8) * soc / 100, h - 8), 3, 3)
        self._text(p, (700, 262, 240, 24), f"Autonomie  {s.range_km} km", 17, t.TEXT,
                   align=Qt.AlignmentFlag.AlignRight)
        self._text(p, (700, 286, 240, 22), f"Batterie {s.battery_temp_c:.0f} °C", 13, t.MUTED,
                   align=Qt.AlignmentFlag.AlignRight)

    def _alert_banner(self, p: QPainter, s: VehicleState) -> None:
        if not s.alerts:
            return
        alert = sorted(s.alerts, key=lambda a: ALERT_PRIORITY.get(a.level, 9))[0]
        colour = t.LEVEL_COLORS.get(alert.level, t.ORANGE)
        rect = QRectF(270, 345, 460, 38)
        p.setPen(QPen(t.color(colour), 1.5))
        p.setBrush(t.color(colour, 40))
        p.drawRoundedRect(rect, 19, 19)
        extra = f"   (+{len(s.alerts) - 1})" if len(s.alerts) > 1 else ""
        self._text(p, (270, 345, 460, 38), f"⚠  {alert.text}{extra}", 16, colour, True)
