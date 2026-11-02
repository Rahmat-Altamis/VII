"""Main window: sidebar navigation + stacked views + status/progress."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QListWidget, QMainWindow,
                               QMessageBox, QProgressBar, QStackedWidget, QStatusBar,
                               QVBoxLayout, QWidget)

from vii.application.jobs import JobRunner
from vii.application.services import AnalysisService
from vii.config import get_settings
from vii.ui.styles import DARK_QSS
from vii.ui.views.dashboard import DashboardView
from vii.ui.views.diagnostics import DiagnosticsView
from vii.ui.views.evidence import EvidenceView
from vii.ui.views.history import HistoryView
from vii.ui.views.new_analysis import NewAnalysisView
from vii.ui.views.settings import SettingsView
from vii.ui.workers import AnalysisWorker


class MainWindow(QMainWindow):
    def __init__(self, service: AnalysisService):
        super().__init__()
        self.service = service
        self.runner = JobRunner(service)
        self.setWindowTitle("Video Integrity Intelligence")
        self.resize(1240, 820)

        central = QWidget(); root = QHBoxLayout(central); root.setContentsMargins(0, 0, 0, 0)
        self.nav = QListWidget(); self.nav.setMaximumWidth(200)
        self.nav.addItems(["Dashboard", "New Analysis", "Analysis History",
                           "Evidence Library", "Settings", "Diagnostics"])
        self.nav.currentRowChanged.connect(self._switch)
        self.stack = QStackedWidget()
        self.dashboard = DashboardView(service, on_open=self.open_job)
        self.new_view = NewAnalysisView(service, on_started=self.start_job)
        self.history = HistoryView(service)
        self.evidence = EvidenceView(service)
        self.settings_v = SettingsView(service)
        self.diag = DiagnosticsView(service)
        for w in (self.dashboard, self.new_view, self.history, self.evidence,
                  self.settings_v, self.diag):
            self.stack.addWidget(w)
        root.addWidget(self.nav); root.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.status = QStatusBar(); self.setStatusBar(self.status)
        self.progress = QProgressBar(); self.progress.setVisible(False)
        self.status.addPermanentWidget(self.progress)
        self._worker: AnalysisWorker | None = None
        self._current: str | None = None
        self.nav.setCurrentRow(0)

    def _switch(self, i: int):
        self.stack.setCurrentIndex(i)
        for v in (self.dashboard, self.history, self.evidence, self.settings_v, self.diag):
            if self.stack.widget(i) is v and hasattr(v, "refresh"):
                v.refresh()

    def open_job(self, job_id: str):
        self.nav.setCurrentRow(2)
        self.history.show_job(job_id)

    def start_job(self, job_id: str):
        self._current = job_id
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.status.showMessage(f"Running {job_id}…")
        self._worker = AnalysisWorker(self.service, job_id)
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.finished.connect(self._on_finished)
        self._worker.start()
        self.open_job(job_id)

    def _on_progress(self, jid: str, status: str, msg: str):
        if jid == self._current:
            self.status.showMessage(f"{jid}: {status} — {msg}")

    def _on_finished(self, jid: str, result, error):
        self.progress.setVisible(False)
        if error is not None:
            QMessageBox.critical(self, "Analysis failed", str(error)[:1000])
            self.status.showMessage(f"{jid} failed: {error}")
        else:
            self.status.showMessage(f"{jid} complete: {len(result.get('claims', []))} claims.")
        self.history.refresh(); self.dashboard.refresh(); self.evidence.refresh()


def run_app() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_QSS)
    try:
        service = AnalysisService(get_settings())
    except Exception as e:  # noqa: BLE001
        QMessageBox.critical(None, "Startup failed", str(e)[:1000])
        return 1
    win = MainWindow(service)
    win.show()
    _s = service.settings
    mode = ("LIVE Meta API" if _s.live_mode else
            ("SYNTHETIC DEMO" if _s.demo_enabled else "NO KEY — provider analysis unavailable"))
    win.status.showMessage(f"Ready ({mode}). Start with New Analysis.", 8000)
    return app.exec()
