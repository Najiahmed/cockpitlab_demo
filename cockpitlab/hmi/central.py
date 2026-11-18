"""Écran central (multimédia) : écran d'accueil avec navigation, média, énergie et climatisation."""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QVBoxLayout, QWidget)

from ..middleware import VehicleState
from . import theme as t

INSTRUCTIONS = [
    ("↱", "Tournez à droite", "Avenue des Essais"),
    ("↰", "Tournez à gauche", "Rue du Banc"),
    ("↑", "Continuez tout droit", "Boulevard de l'Intégration"),
    ("⟳", "Au rond-point, 2e sortie", "Route de la Validation"),
]

TRACKS = [
    ("Signal Clair", "Les Trames Libres", 214),
    ("Non-Régression", "Banc Numéro 4", 187),
    ("Build Verte", "Pipeline Orchestra", 243),
]


def card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    return frame


def label(text: str = "", name: str | None = None) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    return lbl


class NavigationView(QWidget):
    """Carte factice qui défile selon la vitesse réelle du véhicule simulé."""

    PIXELS_PER_METRE = 1.6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(240)
        self._offset = 0.0
        self._instruction = 0
        self._distance_m = 450.0
        self._remaining_km = 12.4
        self._speed = 0.0

    def advance(self, state: VehicleState, dt: float) -> None:
        metres = max(state.speed_kmh, 0) / 3.6 * dt if state.gear == "D" else 0.0
        self._speed = state.speed_kmh
        self._offset = (self._offset + metres * self.PIXELS_PER_METRE) % 80
        self._remaining_km = max(0.0, self._remaining_km - metres / 1000)
        self._distance_m -= metres
        if self._distance_m <= 0:
            self._instruction = (self._instruction + 1) % len(INSTRUCTIONS)
            self._distance_m = 350.0 + 150 * (self._instruction % 3)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, w, h), 16, 16)
        p.setClipPath(clip)
        p.fillRect(self.rect(), t.color("#0B1420"))

        # Rues secondaires qui défilent
        p.setPen(QPen(t.color("#16263A"), 10))
        y = -80 + self._offset
        while y < h + 80:
            p.drawLine(QPointF(0, y), QPointF(w, y))
            y += 80
        for x in (w * 0.18, w * 0.78):
            p.drawLine(QPointF(x, 0), QPointF(x, h))
        # Route principale + itinéraire
        p.setPen(QPen(t.color("#1E3550"), 26))
        p.drawLine(QPointF(w / 2, 0), QPointF(w / 2, h))
        route = QPen(t.color(t.ACCENT), 8)
        route.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(route)
        p.drawLine(QPointF(w / 2, h - 40), QPointF(w / 2, 70))
        # Véhicule
        car = QPainterPath()
        cx, cy = w / 2, h - 48
        car.moveTo(cx, cy - 14)
        car.lineTo(cx + 11, cy + 12)
        car.lineTo(cx, cy + 6)
        car.lineTo(cx - 11, cy + 12)
        car.closeSubpath()
        p.setPen(QPen(t.color(t.BG), 2))
        p.setBrush(t.color("#FFFFFF"))
        p.drawPath(car)

        # Bandeau d'instruction
        icon, action, street = INSTRUCTIONS[self._instruction]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(t.color("#0F1B2A", 235))
        p.drawRoundedRect(QRectF(12, 12, w - 24, 58), 12, 12)
        p.setPen(t.color(t.ACCENT))
        p.setFont(t.font(34, True))
        p.drawText(QRectF(20, 12, 50, 58), Qt.AlignmentFlag.AlignCenter, icon)
        p.setPen(t.color(t.TEXT))
        p.setFont(t.font(17, True))
        p.drawText(QRectF(78, 16, w - 100, 26), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{self._distance_m:.0f} m · {action}")
        p.setPen(t.color(t.MUTED))
        p.setFont(t.font(14))
        p.drawText(QRectF(78, 42, w - 100, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, street)

        # Arrivée estimée
        avg_speed = max(self._speed, 30.0)
        eta = datetime.now() + timedelta(hours=self._remaining_km / avg_speed)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(t.color("#0F1B2A", 235))
        p.drawRoundedRect(QRectF(12, h - 44, 190, 32), 10, 10)
        p.setPen(t.color(t.TEXT))
        p.setFont(t.font(14, True))
        p.drawText(QRectF(12, h - 44, 190, 32), Qt.AlignmentFlag.AlignCenter,
                   f"Arrivée {eta:%H:%M} · {self._remaining_km:.1f} km")
        p.end()


class MediaCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.playing = True
        self.track = 0
        self.position = 0.0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.addWidget(label("MÉDIA · Bluetooth", "muted"))
        self.title = label(name="title")
        self.artist = label(name="muted")
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        layout.addWidget(self.title)
        layout.addWidget(self.artist)
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        for text, slot in (("⏮", self.previous), ("⏯", self.toggle), ("⏭", self.next)):
            btn = QPushButton(text)
            btn.setObjectName("round")
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(slot)
            buttons.addWidget(btn)
        layout.addLayout(buttons)
        self._refresh()

    def toggle(self) -> None:
        self.playing = not self.playing

    def next(self) -> None:
        self.track = (self.track + 1) % len(TRACKS)
        self.position = 0.0
        self._refresh()

    def previous(self) -> None:
        self.track = (self.track - 1) % len(TRACKS)
        self.position = 0.0
        self._refresh()

    def tick(self, dt: float) -> None:
        if self.playing:
            self.position += dt
            if self.position >= TRACKS[self.track][2]:
                self.next()
        self._refresh()

    def _refresh(self) -> None:
        title, artist, duration = TRACKS[self.track]
        self.title.setText(title)
        self.artist.setText(artist)
        self.progress.setMaximum(duration)
        self.progress.setValue(int(self.position))


class EnergyCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.addWidget(label("ÉNERGIE", "muted"))
        self.consumption = label("--", "big")
        layout.addWidget(self.consumption)
        layout.addWidget(label("kWh/100 km instantané", "muted"))
        self.range = label("", "title")
        layout.addWidget(self.range)
        layout.addStretch()

    def update_state(self, s: VehicleState) -> None:
        if s.is_valid("VCU_Status") and s.is_valid("ESP_Speed") and s.speed_kmh > 5:
            self.consumption.setText(f"{s.power_kw / s.speed_kmh * 100:.1f}")
        else:
            self.consumption.setText("--")
        self.range.setText(f"Autonomie {s.range_km} km" if s.is_valid("BMS_Battery") else "Autonomie --")


class ClimateBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.temps = [21.0, 21.0]
        self.ac_on = True
        self.fan = 2
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        self._labels = []
        for side in (0, 1):
            minus, value, plus = QPushButton("−"), label(name="title"), QPushButton("+")
            for btn in (minus, plus):
                btn.setObjectName("round")
                btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            minus.clicked.connect(lambda _=False, i=side: self.change_temp(i, -0.5))
            plus.clicked.connect(lambda _=False, i=side: self.change_temp(i, +0.5))
            self._labels.append(value)
            group = QHBoxLayout()
            group.addWidget(minus)
            group.addWidget(value)
            group.addWidget(plus)
            layout.addLayout(group)
            if side == 0:
                layout.addStretch()
                self.ac = QPushButton("A/C")
                self.ac.setCheckable(True)
                self.ac.setChecked(True)
                self.ac.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                self.ac.toggled.connect(self._set_ac)
                self.fan_btn = QPushButton()
                self.fan_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                self.fan_btn.clicked.connect(self._cycle_fan)
                layout.addWidget(self.ac)
                layout.addWidget(self.fan_btn)
                layout.addStretch()
        self._refresh()

    def change_temp(self, side: int, delta: float) -> None:
        self.temps[side] = min(28.0, max(16.0, self.temps[side] + delta))
        self._refresh()

    def _set_ac(self, on: bool) -> None:
        self.ac_on = on

    def _cycle_fan(self) -> None:
        self.fan = self.fan % 5 + 1
        self._refresh()

    def _refresh(self) -> None:
        for lbl, temp in zip(self._labels, self.temps):
            lbl.setText(f"{temp:.1f}°")
        self.fan_btn.setText(f"Ventilation {'●' * self.fan}{'○' * (5 - self.fan)}")


class CentralScreen(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("screen")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 14)
        layout.setSpacing(10)

        status = QHBoxLayout()
        self.clock = label(name="title")
        status.addWidget(self.clock)
        status.addStretch()
        self.software = label("", "muted")
        status.addWidget(self.software)
        status.addSpacing(16)
        status.addWidget(label("4G ▂▄▆   Wi-Fi   12 °C ext.", "muted"))
        layout.addLayout(status)

        nav_card = card()
        nav_layout = QVBoxLayout(nav_card)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        self.navigation = NavigationView()
        nav_layout.addWidget(self.navigation)
        layout.addWidget(nav_card, 3)

        grid = QGridLayout()
        grid.setSpacing(10)
        self.media = MediaCard()
        self.energy = EnergyCard()
        grid.addWidget(self.media, 0, 0)
        grid.addWidget(self.energy, 0, 1)
        layout.addLayout(grid, 2)

        self.climate = ClimateBar()
        layout.addWidget(self.climate)

    def set_software(self, version: str) -> None:
        text = f"Logiciel {version}"
        if self.software.text() != text:
            self.software.setText(text)

    def set_state(self, state: VehicleState, dt: float) -> None:
        self.clock.setText(datetime.now().strftime("%H:%M"))
        self.navigation.advance(state, dt)
        self.media.tick(dt)
        self.energy.update_state(state)
