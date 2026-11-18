from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDockWidget, QHBoxLayout, QLabel, QMainWindow, QVBoxLayout, QWidget

from ..app.runtime import CockpitRuntime
from .bench import BenchPanel
from .central import CentralScreen
from .cluster import ClusterWidget
from . import theme as t

TICK_MS = 20


class MainWindow(QMainWindow):
    def __init__(self, runtime: CockpitRuntime):
        super().__init__()
        self.rt = runtime
        self.setWindowTitle("CockpitLab — cockpit Android Automotive simulé")

        dashboard = QWidget()
        dashboard.setObjectName("dashboard")
        outer = QVBoxLayout(dashboard)
        outer.setContentsMargins(16, 10, 16, 16)
        outer.setSpacing(10)
        # Bandeau de narration des scénarios (utile pour filmer une démonstration)
        self.banner = QLabel("")
        self.banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner.setMinimumHeight(34)
        self.banner.setVisible(False)
        outer.addWidget(self.banner)
        layout = QHBoxLayout()
        layout.setSpacing(16)
        self.cluster = ClusterWidget()
        self.central = CentralScreen()
        layout.addWidget(self.cluster, 3)
        layout.addWidget(self.central, 2)
        outer.addLayout(layout, 1)
        self.setCentralWidget(dashboard)
        self._banner_text = None

        self.bench = BenchPanel(runtime)
        dock = QDockWidget("Banc de test", self)
        dock.setObjectName("bench")
        dock.setWidget(self.bench)
        dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable
                         | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
        self.resizeDocks([dock], [400], Qt.Orientation.Vertical)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._last = time.monotonic()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(TICK_MS)

    def _tick(self) -> None:
        now = time.monotonic()
        dt = min(max(now - self._last, 0.0), 0.1)
        self._last = now
        scenarios = self.bench.scenarios
        factor = scenarios.time_factor  # accélération du temps pendant un scénario
        for _ in range(factor):
            self.rt.step(dt)
            scenarios.tick(dt)
        state = self.rt.state
        self.cluster.set_state(state)
        self.central.set_state(state, dt * factor)
        self.central.set_software(self.rt.build.version)
        self.bench.sync()
        self._update_banner(*scenarios.narration)

    def _update_banner(self, text: str, colour: str) -> None:
        if (text, colour) == self._banner_text:
            return
        self._banner_text = (text, colour)
        self.banner.setVisible(bool(text))
        self.banner.setText(text)
        self.banner.setStyleSheet(
            f"background:{t.PANEL}; color:{colour}; border:1px solid {colour}; border-radius:17px;"
            f"font-size:16px; font-weight:600; padding:4px 16px;")

    # Conduite au clavier
    def keyPressEvent(self, event) -> None:
        if event.isAutoRepeat() or self.bench.scenarios.active:
            return
        if event.key() == Qt.Key.Key_Up:
            self.bench.driving.accelerator.setValue(70)
        elif event.key() == Qt.Key.Key_Down:
            self.bench.driving.brake.setValue(80)
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.isAutoRepeat() or self.bench.scenarios.active:
            return
        if event.key() == Qt.Key.Key_Up:
            self.bench.driving.accelerator.setValue(0)
        elif event.key() == Qt.Key.Key_Down:
            self.bench.driving.brake.setValue(0)
        else:
            super().keyReleaseEvent(event)

    def closeEvent(self, event) -> None:
        self.timer.stop()
        self.bench.tests.shutdown()
        self.bench.scenarios.stop()
        self.rt.shutdown()
        super().closeEvent(event)
