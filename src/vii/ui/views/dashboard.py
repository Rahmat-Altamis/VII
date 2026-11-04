"""Dashboard view: stats + recent analyses."""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QListWidget, QVBoxLayout, QWidget


class DashboardView(QWidget):
    def __init__(self, service, on_open=None, parent=None):
        super().__init__(parent)
        self._service = service
        self._on_open = on_open
        lay = QVBoxLayout(self)
        self.title = QLabel("Dashboard")
        self.title.setObjectName("h1")
        self.stats = QLabel("")
        self.stats.setObjectName("dim")
        self.recent = QListWidget()
        self.recent.itemDoubleClicked.connect(self._open)
        lay.addWidget(self.title)
        lay.addWidget(self.stats)
        lay.addWidget(self.recent)

    def refresh(self):
        try:
            jobs = self._service.list(20)
        except Exception as e:  # noqa: BLE001
            self.stats.setText(f"Storage unavailable: {e}")
            return
        ok = sum(1 for j in jobs if j["status"] == "succeeded")
        _s = self._service.settings
        mode = ("LIVE Meta API" if _s.live_mode else
                ("SYNTHETIC DEMO" if _s.demo_enabled else "NO KEY, provider analysis unavailable"))
        self.stats.setText(f"{len(jobs)} analyses · {ok} succeeded · mode: {mode}")
        self.recent.clear()
        for j in jobs:
            self.recent.addItem(f"{j['id']}, {j['title']} [{j['status']}]")

    def _open(self, item):
        if self._on_open:
            self._on_open(item.text().split(", ")[0])
