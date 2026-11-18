"""Onglet Scénarios : build installée, scénarios joués en direct, injection de défauts à chaud."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QGridLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QListWidget, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..app.runtime import CockpitRuntime
from ..builds import BUILDS
from ..bus import DATABASE
from ..scenarios import ScenarioPlayer, ScenarioRun, StepStatus, load_scenarios
from ..scenarios.report import write_html
from . import theme as t

PAUSE_BETWEEN_S = 1.5
SPEEDS = {"Temps réel": 1, "× 2": 2, "× 4": 4}
STEP_COLORS = {StepStatus.PENDING: t.MUTED, StepStatus.RUNNING: t.ACCENT,
               StepStatus.PASSED: t.GREEN, StepStatus.FAILED: t.RED, StepStatus.SKIPPED: t.MUTED}
STEP_ICONS = {StepStatus.PENDING: "·", StepStatus.RUNNING: "▶", StepStatus.PASSED: "✔",
              StepStatus.FAILED: "✘", StepStatus.SKIPPED: "–"}


def _button(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return btn


class ScenariosTab(QWidget):
    def __init__(self, runtime: CockpitRuntime, parent=None):
        super().__init__(parent)
        self.rt = runtime
        self.scenarios = load_scenarios()
        self.player: ScenarioPlayer | None = None
        self.queue: list = []
        self.runs: list[ScenarioRun] = []
        self._pause = 0.0
        self._running = False
        self._since_finish = 0.0
        self._release_brake = False
        self._shown: list[StepStatus] = []
        self.report_path: Path | None = None

        layout = QHBoxLayout(self)
        layout.addWidget(self._build_left())
        layout.addWidget(self._build_steps(), 3)
        layout.addWidget(self._build_faults())
        self._select(0)

    # ---------------------------------------------------------------- UI
    def _build_left(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(300)
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._muted("Build installée sur le banc"))
        self.build_box = QComboBox()
        self.build_box.addItems([b.label for b in BUILDS])
        self.build_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.build_box.currentIndexChanged.connect(lambda i: self.rt.install_build(BUILDS[i]))
        v.addWidget(self.build_box)

        v.addWidget(self._muted("Scénarios"))
        self.list = QListWidget()
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for s in self.scenarios:
            self.list.addItem(f"{s.id} · {s.title}")
        self.list.currentRowChanged.connect(self._select)
        v.addWidget(self.list, 1)
        self.description = self._muted("")
        self.description.setWordWrap(True)
        v.addWidget(self.description)

        row = QHBoxLayout()
        row.addWidget(self._muted("Vitesse"))
        self.speed = QComboBox()
        self.speed.addItems(list(SPEEDS))
        self.speed.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        row.addWidget(self.speed, 1)
        v.addLayout(row)

        buttons = QHBoxLayout()
        self.play_btn = _button("▶  Jouer")
        self.all_btn = _button("▶▶  Tout jouer")
        self.stop_btn = _button("■  Arrêter")
        self.play_btn.clicked.connect(lambda: self.start([self.scenarios[self.list.currentRow()]]))
        self.all_btn.clicked.connect(lambda: self.start(list(self.scenarios)))
        self.stop_btn.clicked.connect(self.stop)
        for b in (self.play_btn, self.all_btn, self.stop_btn):
            buttons.addWidget(b)
        v.addLayout(buttons)

        self.summary = self._muted("")
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)
        self.report_btn = _button("Ouvrir le rapport des scénarios")
        self.report_btn.setEnabled(False)
        self.report_btn.clicked.connect(self._open_report)
        v.addWidget(self.report_btn)
        return panel

    def _build_steps(self) -> QWidget:
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["", "Étape", "Statut", "Détail"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setStyleSheet("QTableWidget { font-family: 'Segoe UI'; font-size: 13px; }")
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        return self.table

    def _build_faults(self) -> QWidget:
        box = QGroupBox("Injection de défauts à chaud")
        box.setFixedWidth(300)
        g = QGridLayout(box)
        self.message = QComboBox()
        self.message.addItems([m.name for m in DATABASE.messages])
        self.message.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        g.addWidget(self.message, 0, 0, 1, 2)
        actions = [
            ("Couper la trame", lambda: self.rt.vehicle.muted.add(self._msg())),
            ("Rétablir", lambda: self.rt.vehicle.muted.discard(self._msg())),
            ("Corrompre", lambda: self.rt.vehicle.corrupted.add(self._msg())),
            ("Réparer", lambda: self.rt.vehicle.corrupted.discard(self._msg())),
        ]
        for i, (text, slot) in enumerate(actions):
            btn = _button(text)
            btn.clicked.connect(slot)
            g.addWidget(btn, 1 + i // 2, i % 2)
        hot = _button("Surchauffe batterie (43 °C)")
        hot.clicked.connect(lambda: setattr(self.rt.vehicle, "battery_temp_c", 43.0))
        g.addWidget(hot, 3, 0, 1, 2)
        clear = _button("Tout rétablir")
        clear.clicked.connect(self._clear_faults)
        g.addWidget(clear, 4, 0, 1, 2)
        self.active_faults = self._muted("")
        self.active_faults.setWordWrap(True)
        g.addWidget(self.active_faults, 5, 0, 1, 2)
        hint = self._muted("Les défauts s'appliquent au véhicule en cours, "
                           "pendant la conduite manuelle comme pendant un scénario.")
        hint.setWordWrap(True)
        g.addWidget(hint, 6, 0, 1, 2)
        g.setRowStretch(7, 1)
        return box

    @staticmethod
    def _muted(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("muted")
        return label

    def _msg(self) -> str:
        return self.message.currentText()

    def _clear_faults(self) -> None:
        self.rt.vehicle.muted.clear()
        self.rt.vehicle.corrupted.clear()
        self.rt.vehicle.battery_temp_c = 24.0

    # ------------------------------------------------------------ état
    @property
    def active(self) -> bool:
        return self.player is not None and (not self.player.finished or bool(self.queue))

    @property
    def time_factor(self) -> int:
        return SPEEDS[self.speed.currentText()] if self.active else 1

    @property
    def narration(self) -> tuple[str, str]:
        """(texte, couleur) du bandeau affiché au-dessus du cockpit."""
        if self.player is None:
            return "", t.MUTED
        p = self.player
        if not p.finished:
            return f"{p.scenario.id} · étape {p.index + 1}/{len(p.scenario.steps)} · {p.narration}", t.ACCENT
        if not self._running and self._since_finish > 8.0:
            return "", t.MUTED  # le bandeau de résultat s'efface après quelques secondes
        return p.narration, (t.GREEN if p.run.passed else t.RED)

    # --------------------------------------------------------- exécution
    def start(self, scenarios: list) -> None:
        if self.active:
            return
        self.runs = []
        self.report_path = None
        self.report_btn.setEnabled(False)
        self.queue = list(scenarios)
        self._running = True
        self._launch_next()
        self._set_controls(running=True)

    def _launch_next(self) -> None:
        scenario = self.queue.pop(0)
        self.list.blockSignals(True)
        self.list.setCurrentRow(self.scenarios.index(scenario))
        self.list.blockSignals(False)
        self._fill_table(scenario)
        self.player = ScenarioPlayer(self.rt, scenario)
        self.player.tick(0.0)
        self._pause = 0.0

    def stop(self) -> None:
        if self.player and not self.player.finished:
            self.player.stop()
        self.queue = []
        self._finish()

    def tick(self, dt: float) -> None:
        """Appelé par la fenêtre principale après chaque pas de simulation."""
        faults = [f"coupée : {m}" for m in sorted(self.rt.vehicle.muted)]
        faults += [f"corrompue : {m}" for m in sorted(self.rt.vehicle.corrupted)]
        self.active_faults.setText("Défauts actifs : " + (", ".join(faults) or "aucun"))
        if self.player is None:
            return
        if not self._running:
            self._since_finish += dt
            # Fin de scénario : le frein de sécurité est relâché une fois le véhicule arrêté,
            # pour rendre la main à la conduite manuelle.
            if self._release_brake and self.rt.vehicle.speed_kmh == 0:
                self.rt.vehicle.inputs.accelerator = self.rt.vehicle.inputs.brake = 0.0
                self._release_brake = False
            return
        was_finished = self.player.finished
        self.player.tick(dt)
        self._refresh_rows()
        if not self.player.finished:
            return
        if not was_finished:
            self.runs.append(self.player.run)
            self._update_summary()
        if self.queue:
            self._pause += dt
            if self._pause >= PAUSE_BETWEEN_S:
                self._launch_next()
        else:
            self._finish()

    def _finish(self) -> None:
        if not self._running:
            return
        self._running = False
        self._since_finish = 0.0
        self._release_brake = True
        self._set_controls(running=False)
        if self.player and self.player.run not in self.runs and self.player.finished:
            self.runs.append(self.player.run)
        if self.runs:
            self.report_path = write_html(self.runs, self.rt.build.label)
            self.report_btn.setEnabled(True)
        self._update_summary()

    def _update_summary(self) -> None:
        if not self.runs:
            self.summary.setText("")
            return
        passed = sum(r.passed for r in self.runs)
        lines = [f"{passed}/{len(self.runs)} scénarios réussis sur {self.rt.build.version}"]
        lines += [f"{'✔' if r.passed else '✘'} {r.scenario.id} {r.scenario.title}" for r in self.runs]
        self.summary.setText("\n".join(lines))

    def _set_controls(self, running: bool) -> None:
        for widget in (self.play_btn, self.all_btn, self.build_box, self.list):
            widget.setEnabled(not running)

    # ------------------------------------------------------------ tableau
    def _select(self, row: int) -> None:
        if 0 <= row < len(self.scenarios) and not self.active:
            scenario = self.scenarios[row]
            self.description.setText(scenario.description)
            self._fill_table(scenario)

    def _fill_table(self, scenario) -> None:
        self.description.setText(scenario.description)
        self.table.setRowCount(len(scenario.steps))
        self._shown = [None] * len(scenario.steps)
        for row, step in enumerate(scenario.steps):
            self._set_row(row, StepStatus.PENDING, step.label, "")

    def _refresh_rows(self) -> None:
        run = self.player.run
        for row, (step, result) in enumerate(zip(self.player.scenario.steps, run.results)):
            key = (result.status, result.detail)
            if self._shown[row] != key:
                self._shown[row] = key
                self._set_row(row, result.status, step.label, result.detail)
                if result.status == StepStatus.RUNNING:
                    self.table.scrollToItem(self.table.item(row, 1))

    def _set_row(self, row: int, status: StepStatus, label: str, detail: str) -> None:
        colour = STEP_COLORS[status]
        for col, text in enumerate((STEP_ICONS[status], label, status.value, detail)):
            item = self.table.item(row, col)
            if item is None:
                item = QTableWidgetItem()
                self.table.setItem(row, col, item)
            item.setText(text)
            item.setForeground(QColor(colour if col in (0, 2) else t.TEXT))

    def _open_report(self) -> None:
        if self.report_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.report_path.resolve())))
