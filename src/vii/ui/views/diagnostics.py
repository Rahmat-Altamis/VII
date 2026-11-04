"""Diagnostics view: redacted settings, binary checks, recent errors."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QTextEdit, QVBoxLayout, QWidget


class DiagnosticsView(QWidget):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service
        lay = QVBoxLayout(self)
        t = QLabel("Diagnostics")
        t.setObjectName("h1")
        lay.addWidget(t)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        lay.addWidget(self.text)

    def refresh(self):
        import json as _json
        d = self._service.diagnostics()
        self.text.setPlainText(_json.dumps(d, indent=2, default=str))
