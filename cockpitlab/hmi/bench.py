"""Banc de test : pilotage du véhicule simulé et trace CAN (comme un poste de banc HIL)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QPushButton, QSlider, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ..app.runtime import CockpitRuntime
from ..bus import DATABASE
from . import theme as t
from .scenarios_tab import ScenariosTab
from .tests_tab import TestsTab


def _no_focus(widget):
    widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return widget


class DrivingTab(QWidget):
    def __init__(self, runtime: CockpitRuntime, parent=None):
        super().__init__(parent)
        self.rt = runtime
        self._checks: dict[str, QCheckBox] = {}
        layout = QHBoxLayout(self)

        # Contact
        contact = QGroupBox("Contact")
        c = QVBoxLayout(contact)
        self.power_btn = _no_focus(QPushButton("Démarrer"))
        self.power_btn.clicked.connect(self._toggle_power)
        c.addWidget(self.power_btn)
        c.addStretch()
        layout.addWidget(contact)

        # Rapports
        gears = QGroupBox("Rapport")
        g = QVBoxLayout(gears)
        row = QHBoxLayout()
        self.gear_buttons: dict[str, QPushButton] = {}
        for gear in "PRND":
            btn = _no_focus(QPushButton(gear))
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, x=gear: setattr(self.rt.vehicle.inputs, "requested_gear", x))
            self.gear_buttons[gear] = btn
            row.addWidget(btn)
        g.addLayout(row)
        self.rejection = QLabel("")
        self.rejection.setStyleSheet(f"color: {t.ORANGE};")
        self.rejection.setWordWrap(True)
        g.addWidget(self.rejection)
        layout.addWidget(gears)

        # Pédales
        pedals = QGroupBox("Pédales")
        p = QVBoxLayout(pedals)
        self.accelerator = self._slider(p, "Accélérateur", lambda v: setattr(self.rt.vehicle.inputs, "accelerator", v / 100))
        self.brake = self._slider(p, "Frein", lambda v: setattr(self.rt.vehicle.inputs, "brake", v / 100))
        hint = QLabel("Clavier : ↑ accélérer · ↓ freiner")
        hint.setObjectName("muted")
        p.addWidget(hint)
        layout.addWidget(pedals, 2)

        # Carrosserie
        body = QGroupBox("Carrosserie")
        b = QVBoxLayout(body)
        self.left = self._check(b, "Clignotant gauche", "left_turn")
        self.right = self._check(b, "Clignotant droit", "right_turn")
        self.left.toggled.connect(lambda on: on and self.right.setChecked(False))
        self.right.toggled.connect(lambda on: on and self.left.setChecked(False))
        self._check(b, "Feux de détresse", "hazard")
        self._check(b, "Feux de croisement", "low_beam")
        self._check(b, "Feux de route", "high_beam")
        self._check(b, "Ceinture bouclée", "seatbelt_buckled", checked=True)
        layout.addWidget(body)

        # Batterie
        battery = QGroupBox("Batterie")
        bt = QVBoxLayout(battery)
        for soc in (80, 25, 12):
            btn = _no_focus(QPushButton(f"Forcer SOC à {soc} %"))
            btn.clicked.connect(lambda _=False, v=soc: setattr(runtime.vehicle, "soc_pct", float(v)))
            bt.addWidget(btn)
        bt.addStretch()
        layout.addWidget(battery)

    def _slider(self, layout, name, on_change) -> QSlider:
        row = QHBoxLayout()
        row.addWidget(QLabel(name))
        slider = _no_focus(QSlider(Qt.Orientation.Horizontal))
        slider.setRange(0, 100)
        value = QLabel("0 %")
        value.setMinimumWidth(42)
        slider.valueChanged.connect(on_change)
        slider.valueChanged.connect(lambda v: value.setText(f"{v} %"))
        row.addWidget(slider, 1)
        row.addWidget(value)
        layout.addLayout(row)
        return slider

    def _check(self, layout, text, attribute, checked=False) -> QCheckBox:
        box = _no_focus(QCheckBox(text))
        box.setChecked(checked)
        box.toggled.connect(lambda on: setattr(self.rt.vehicle.inputs, attribute, on))
        layout.addWidget(box)
        self._checks[attribute] = box
        return box

    def _toggle_power(self) -> None:
        vehicle = self.rt.vehicle
        if vehicle.ready:
            vehicle.power_off()
        else:
            vehicle.power_on()

    def sync(self) -> None:
        """Reflète l'état réel du simulateur (une demande refusée ne reste pas affichée)."""
        vehicle = self.rt.vehicle
        self.power_btn.setText("Arrêter" if vehicle.ready else "Démarrer")
        for gear, btn in self.gear_buttons.items():
            btn.setChecked(gear == vehicle.gear)
        self.rejection.setText(vehicle.last_rejection or "")
        # Les scénarios pilotent aussi le véhicule : les commandes affichent l'état réel.
        inputs = vehicle.inputs
        for slider, value in ((self.accelerator, inputs.accelerator), (self.brake, inputs.brake)):
            target = round(value * 100)
            if slider.value() != target:
                slider.setValue(target)  # met aussi à jour l'étiquette « xx % »
        for attribute, box in self._checks.items():
            if box.isChecked() != getattr(inputs, attribute):
                box.blockSignals(True)
                box.setChecked(getattr(inputs, attribute))
                box.blockSignals(False)


class CanTraceTab(QWidget):
    ROWS = 30
    COLUMNS = ["Temps (s)", "ID", "Message", "Données", "Valeurs décodées"]

    def __init__(self, runtime: CockpitRuntime, parent=None):
        super().__init__(parent)
        self.rt = runtime
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.pause = _no_focus(QCheckBox("Pause"))
        self.filter = _no_focus(QComboBox())
        self.filter.addItem("Toutes les trames")
        for message in DATABASE.messages:
            self.filter.addItem(message.name)
        self.stats = QLabel("")
        self.stats.setObjectName("muted")
        bar.addWidget(self.pause)
        bar.addWidget(self.filter)
        bar.addStretch()
        bar.addWidget(self.stats)
        layout.addLayout(bar)

        self.table = QTableWidget(self.ROWS, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header = self.table.horizontalHeader()
        for col in range(len(self.COLUMNS) - 1):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        layout.addWidget(self.table)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(200)

    def refresh(self) -> None:
        self.stats.setText(f"Trames émises : {self.rt.bus.frames_sent}")
        if self.pause.isChecked() or not self.isVisible():
            return
        wanted = self.filter.currentText()
        rows = []
        for frame in reversed(self.rt.bus.recent(400)):
            message = DATABASE.by_id(frame.arbitration_id)
            name = message.name if message else "?"
            if wanted != "Toutes les trames" and name != wanted:
                continue
            decoded = ""
            if message:
                decoded = ", ".join(f"{k}={_fmt(v)}" for k, v in message.decode(frame.data).items())
            rows.append((f"{frame.timestamp:9.3f}", f"0x{frame.arbitration_id:03X}", name,
                         frame.data.hex(" ").upper(), decoded))
            if len(rows) == self.ROWS:
                break
        for r in range(self.ROWS):
            values = rows[r] if r < len(rows) else ("",) * len(self.COLUMNS)
            for c, value in enumerate(values):
                item = self.table.item(r, c)
                if item is None:
                    item = QTableWidgetItem()
                    self.table.setItem(r, c, item)
                item.setText(value)


def _fmt(value) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


class BenchPanel(QTabWidget):
    def __init__(self, runtime: CockpitRuntime, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.driving = DrivingTab(runtime)
        self.trace = CanTraceTab(runtime)
        self.addTab(self.driving, "Pilotage")
        self.addTab(self.trace, "Trace CAN")
        self.tests = TestsTab()
        self.addTab(self.tests, "Tests")
        self.scenarios = ScenariosTab(runtime)
        self.addTab(self.scenarios, "Scénarios")

    def sync(self) -> None:
        self.driving.sync()
