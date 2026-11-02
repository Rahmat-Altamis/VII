"""QThread worker that runs the pipeline off the GUI thread."""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal


class AnalysisSignals(QObject):
    progress = Signal(str, str, str)  # job_id, status, message
    finished = Signal(str, object, object)  # job_id, result, error


class AnalysisWorker(QThread):
    def __init__(self, service, job_id: str):
        super().__init__()
        self.signals = AnalysisSignals()
        self._service = service
        self._job_id = job_id

    def run(self):
        def _cb(jid, status, msg):
            self.signals.progress.emit(jid, str(status), msg)
        try:
            result = self._service.run(self._job_id, _cb)
            self.signals.finished.emit(self._job_id, result, None)
        except Exception as e:  # noqa: BLE001 — forwarded to UI
            self.signals.finished.emit(self._job_id, None, e)
