"""Evidence Library: all sources across jobs, clickable URLs, method badges."""
from __future__ import annotations

from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget


class EvidenceView(QWidget):
    COLS = ("Job", "Claim", "Title", "URL", "Method")

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service
        lay = QVBoxLayout(self)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(list(self.COLS))
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.cellDoubleClicked.connect(self._open_url)
        lay.addWidget(self.table)

    def refresh(self):
        rows = []
        try:
            jobs = self._service.list(100)
        except Exception:  # noqa: BLE001
            jobs = []
        for j in jobs:
            d = self._service.get(j["id"]) or {}
            for e in d.get("evidence", []):
                rows.append((j["id"][:14], e["claim_id"], e["title"][:60], e["url"], e["method"]))
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for k, v in enumerate(r):
                self.table.setItem(i, k, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()

    def _open_url(self, row, col):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        item = self.table.item(row, 3)
        if item:
            QDesktopServices.openUrl(QUrl(item.text()))
