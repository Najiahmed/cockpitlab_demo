"""Onglet Tests : choix de la build et de la campagne, exécution en direct, verdict, rapports."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView,
                               QLabel, QPlainTextEdit, QProgressBar, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..builds import BUILDS
from ..testing.framework import CATEGORIES, Status, TestCase, TestResult
from ..testing.report import VERDICT_COLORS, ticket_draft, write_reports
from ..testing.runner import CAMPAIGNS, CampaignReport, cases_for, run_campaign
from . import theme as t

REPORTS_DIR = Path("reports")
DEMO_PACE_S = 0.25
STATUS_COLORS = {Status.PASSED: t.GREEN, Status.FAILED: t.RED,
                 Status.ERROR: "#C084FC", Status.SKIPPED: t.MUTED}
COLUMNS = ["ID", "Test", "Sévérité", "Statut", "Durée", "Mesures"]


class CampaignWorker(QThread):
    """Exécute la campagne hors du fil de l'interface pour qu'elle reste fluide."""
    test_started = Signal(str)
    result_ready = Signal(object)
    report_ready = Signal(object)

    def __init__(self, build, campaign_key: str, pace_s: float):
        super().__init__()
        self.build, self.campaign_key, self.pace_s = build, campaign_key, pace_s
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        def on_result(result: TestResult) -> None:
            self.result_ready.emit(result)
            if self.pace_s and result.status != Status.SKIPPED:
                time.sleep(self.pace_s)

        report = run_campaign(self.build, self.campaign_key,
                              on_start=lambda case: self.test_started.emit(case.id),
                              on_result=on_result, should_stop=lambda: self._stop)
        self.report_ready.emit(report)


class TestsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: CampaignWorker | None = None
        self.report: CampaignReport | None = None
        self.results: dict[str, TestResult] = {}
        self.rows: dict[str, int] = {}
        self.report_paths: dict[str, Path] = {}

        layout = QHBoxLayout(self)
        layout.addWidget(self._build_controls())
        layout.addWidget(self._build_table(), 3)
        layout.addWidget(self._build_details(), 2)
        self._load_campaign()

    # ---------------------------------------------------------------- UI
    def _build_controls(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(290)
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)

        v.addWidget(self._muted("Build à qualifier"))
        self.build_box = self._combo([b.label for b in BUILDS])
        self.build_box.currentIndexChanged.connect(self._show_build)
        v.addWidget(self.build_box)
        self.build_desc = self._muted("")
        self.build_desc.setWordWrap(True)
        v.addWidget(self.build_desc)

        v.addWidget(self._muted("Campagne"))
        self.campaign_box = self._combo([c.name for c in CAMPAIGNS.values()])
        self.campaign_box.currentIndexChanged.connect(self._load_campaign)
        v.addWidget(self.campaign_box)

        self.demo = QCheckBox("Mode démo (exécution ralentie)")
        self.demo.setChecked(True)
        self.demo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        v.addWidget(self.demo)

        self.run_btn = QPushButton("▶  Lancer la campagne")
        self.run_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.run_btn.setStyleSheet(f"background:{t.ACCENT_DIM}; border-color:{t.ACCENT}; font-weight:600;")
        self.run_btn.clicked.connect(self._run_or_stop)
        v.addWidget(self.run_btn)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        v.addWidget(self.progress)
        self.current = self._muted("")
        v.addWidget(self.current)

        self.verdict = QLabel("—")
        self.verdict.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verdict.setMinimumHeight(54)
        self._style_verdict(None)
        v.addWidget(self.verdict)
        self.counters = self._muted("")
        self.counters.setWordWrap(True)
        v.addWidget(self.counters)

        self.open_btn = QPushButton("Ouvrir le rapport HTML")
        self.folder_btn = QPushButton("Ouvrir le dossier des rapports")
        for btn in (self.open_btn, self.folder_btn):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setEnabled(False)
            v.addWidget(btn)
        self.open_btn.clicked.connect(lambda: self._open(self.report_paths.get("html")))
        self.folder_btn.clicked.connect(lambda: self._open(REPORTS_DIR))
        v.addStretch()
        self._show_build()
        return panel

    def _build_table(self) -> QWidget:
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setStyleSheet("QTableWidget { font-family: 'Segoe UI'; font-size: 13px; }")
        header = self.table.horizontalHeader()
        for col in (0, 2, 3, 4):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._show_details)
        return self.table

    def _build_details(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setStyleSheet(f"background:{t.BG}; font-family: Consolas, monospace; font-size: 12px;")
        self.details.setPlaceholderText("Sélectionnez un test pour voir son déroulé, ses mesures et ses preuves.")
        v.addWidget(self.details)
        self.copy_btn = QPushButton("Copier le brouillon de ticket")
        self.copy_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.copy_btn.setEnabled(False)
        self.copy_btn.clicked.connect(self._copy_ticket)
        v.addWidget(self.copy_btn)
        return panel

    @staticmethod
    def _muted(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("muted")
        return label

    @staticmethod
    def _combo(items: list[str]) -> QComboBox:
        box = QComboBox()
        box.addItems(items)
        box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return box

    # ------------------------------------------------------------ logique
    @property
    def selected_build(self):
        return BUILDS[self.build_box.currentIndex()]

    @property
    def selected_campaign(self) -> str:
        return list(CAMPAIGNS)[self.campaign_box.currentIndex()]

    def _show_build(self) -> None:
        self.build_desc.setText(self.selected_build.description)

    def _load_campaign(self) -> None:
        cases = cases_for(CAMPAIGNS[self.selected_campaign])
        self.results.clear()
        self.rows = {c.id: i for i, c in enumerate(cases)}
        self.table.setRowCount(len(cases))
        for row, case in enumerate(cases):
            self._set_row(row, case, "En attente", t.MUTED)
        self.progress.setMaximum(len(cases))
        self.progress.setValue(0)
        self.current.setText(f"{len(cases)} tests · {self._category_summary(cases)}")
        self.details.clear()
        self.copy_btn.setEnabled(False)

    @staticmethod
    def _category_summary(cases: list[TestCase]) -> str:
        counts: dict[str, int] = {}
        for c in cases:
            counts[c.category] = counts.get(c.category, 0) + 1
        return ", ".join(f"{CATEGORIES[k]} {n}" for k, n in counts.items())

    def _set_row(self, row: int, case: TestCase, status: str, colour: str,
                 duration: str = "", measures: str = "") -> None:
        values = [case.id, case.title, case.severity, status, duration, measures]
        for col, value in enumerate(values):
            item = self.table.item(row, col)
            if item is None:
                item = QTableWidgetItem()
                self.table.setItem(row, col, item)
            item.setText(value)
            item.setForeground(QColor(colour if col == 3 else t.TEXT))

    def _run_or_stop(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.run_btn.setEnabled(False)
            self.run_btn.setText("Arrêt en cours…")
            return
        self._load_campaign()
        self.report = None
        self.report_paths = {}
        self._style_verdict(None)
        self.counters.setText("")
        self.open_btn.setEnabled(False)
        self.build_box.setEnabled(False)
        self.campaign_box.setEnabled(False)
        self.run_btn.setText("■  Arrêter")
        pace = DEMO_PACE_S if self.demo.isChecked() else 0.0
        self.worker = CampaignWorker(self.selected_build, self.selected_campaign, pace)
        self.worker.test_started.connect(self._on_started)
        self.worker.result_ready.connect(self._on_result)
        self.worker.report_ready.connect(self._on_report)
        self.worker.start()

    def _on_started(self, case_id: str) -> None:
        row = self.rows[case_id]
        case = cases_for(CAMPAIGNS[self.selected_campaign])[row]
        self._set_row(row, case, "En cours…", t.ACCENT)
        self.table.scrollToItem(self.table.item(row, 0))
        self.current.setText(f"En cours : {case.id} · {case.title}")

    def _on_result(self, result: TestResult) -> None:
        self.results[result.case.id] = result
        measures = " · ".join(f"{k} {v}" for k, v in result.measures.items())
        duration = f"{result.duration_s * 1000:.0f} ms" if result.status != Status.SKIPPED else ""
        self._set_row(self.rows[result.case.id], result.case, result.status.value,
                      STATUS_COLORS[result.status], duration, measures)
        self.progress.setValue(len(self.results))

    def _on_report(self, report: CampaignReport) -> None:
        self.report = report
        self.report_paths = write_reports(report, REPORTS_DIR)
        self._style_verdict(report.verdict)
        self.counters.setText(
            f"{report.count(Status.PASSED)} réussis · {report.count(Status.FAILED)} échoués · "
            f"{report.count(Status.ERROR)} erreurs · {report.count(Status.SKIPPED)} non exécutés\n"
            f"Durée {report.duration_s:.1f} s · rapports HTML, JUnit et JSON enregistrés")
        self.current.setText(f"Terminé : {report.campaign.name} sur {report.build.version}")
        self.open_btn.setEnabled(True)
        self.folder_btn.setEnabled(True)
        self.build_box.setEnabled(True)
        self.campaign_box.setEnabled(True)
        self.run_btn.setEnabled(True)
        self.run_btn.setText("▶  Lancer la campagne")
        if report.failures:  # sélectionne la première anomalie
            self.table.selectRow(self.rows[report.failures[0].case.id])

    def _style_verdict(self, verdict: str | None) -> None:
        colour = VERDICT_COLORS.get(verdict, t.BORDER) if verdict else t.BORDER
        self.verdict.setText(verdict or "Verdict : —")
        self.verdict.setStyleSheet(
            f"background:{colour}; color:white; border-radius:12px; font-size:20px; font-weight:700;")

    def _selected_result(self) -> TestResult | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return self.results.get(item.text()) if item else None

    def _show_details(self) -> None:
        result = self._selected_result()
        self.copy_btn.setEnabled(bool(result and result.failed and self.report))
        self.copy_btn.setText("Copier le brouillon de ticket")
        if result is None:
            self.details.clear()
            return
        case = result.case
        marks = {None: "▸", True: "✔", False: "✘"}
        lines = [f"{case.id} · {case.title}", f"Statut : {result.status.value}   Sévérité : {case.severity}",
                 case.requirement, "", "Déroulé :"]
        lines += [f"  {marks[s.ok]} {s.text}" for s in result.steps]
        if result.measures:
            lines += ["", "Mesures :"] + [f"  {k} : {v}" for k, v in result.measures.items()]
        if result.message:
            lines += ["", f"Message : {result.message}"]
        for key, value in result.evidence.items():
            lines.append("")
            if isinstance(value, list):
                lines += [f"{key} :"] + [f"  {line}" for line in value]
            else:
                lines.append(f"{key} : {value}")
        if result.failed and self.report:
            lines += ["", "─" * 60, "BROUILLON DE TICKET", "─" * 60, ticket_draft(result, self.report)]
        self.details.setPlainText("\n".join(lines))

    def _copy_ticket(self) -> None:
        result = self._selected_result()
        if result and self.report:
            QGuiApplication.clipboard().setText(ticket_draft(result, self.report))
            self.copy_btn.setText("Ticket copié ✔")

    @staticmethod
    def _open(path: Path | None) -> None:
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).resolve())))

    def shutdown(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)
