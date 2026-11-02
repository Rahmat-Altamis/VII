"""Analysis History view: list + detail tabs (overview..export)."""
from __future__ import annotations

from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QSplitter, QTabWidget, QTextEdit, QVBoxLayout, QWidget)


class HistoryView(QWidget):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service
        lay = QHBoxLayout(self)
        split = QSplitter()
        self.list = QListWidget(); self.list.setMaximumWidth(320)
        self.list.itemClicked.connect(self._show)
        self.tabs = QTabWidget()
        for name in ("Overview", "Video Understanding", "Transcript", "Claims",
                     "Web Evidence", "Verification", "Media Origin",
                     "Originality", "Processing Log"):
            w = QTextEdit(); w.setReadOnly(True)
            self.tabs.addTab(w, name)
            setattr(self, f"tab_{name.split()[0].lower()}", w)
        split.addWidget(self.list); split.addWidget(self.tabs)
        split.setStretchFactor(1, 1)
        lay.addWidget(split)
        self._jobs: list[dict] = []

    def refresh(self):
        try:
            self._jobs = self._service.list(100)
        except Exception:  # noqa: BLE001
            self._jobs = []
        self.list.clear()
        for j in self._jobs:
            QListWidgetItem(f"{j['id']} [{j['status']}]", self.list)

    def show_job(self, job_id: str):
        for i, j in enumerate(self._jobs):
            if j["id"] == job_id:
                self.list.setCurrentRow(i)
                self._show(self.list.item(i))
                return
        self.refresh()
        self.show_job(job_id) if self._jobs else None

    def _show(self, item):
        jid = item.text().split(" ")[0]
        d = self._service.get(jid)
        if not d:
            return
        mode = "SYNTHETIC DEMO — fixtures, not live verification" if d["offline"] else "LIVE Meta API"
        self._set("Overview", f"<h2>{d['title']}</h2><p>Job <code>{d['id']}</code><br>"
                              f"Status: <b>{d['status']}</b> · Mode: {mode}<br>"
                              f"Source: {d['source_kind']} — {d['source_ref']}<br>"
                              f"Acquisition: {d['acquisition_method']}</p>")
        claims_txt = "\n".join(
            f"• [{c['id']}] ({c['kind']}) {c['text']}" for c in d["claims"]) or "(no claims)"
        self._set("Video", claims_txt)
        tr = "\n".join(f"[{s['start_s']:.1f}-{s['end_s']:.1f}] {s['text']}"
                       for s in d["transcript"]) or "(no transcript)"
        self._set("Transcript", tr)
        self._set("Claims", claims_txt)
        ev = "\n\n".join(f"• {e['title'] or e['url']}\n  {e['url']} ({e['method']}, claim {e['claim_id']})\n"
                         f"  {e['snippet'][:300]}" for e in d["evidence"]) or "(no sources — offline or no results)"
        self._set("Web", ev)
        ver = "\n\n".join(
            f"• {c['id']}: {c['assessment']['status'] if c['assessment'] else 'not yet analyzed'}\n"
            f"  {(c['assessment'] or {}).get('explanation','')}" for c in d["claims"]) or "(none)"
        self._set("Verification", ver)
        self._set("Media", f"Acquisition: {d['acquisition_method']}\nRef: {d['source_ref']}")
        self._set("Originality", "(see exported report for SHA-256 / perceptual-hash details)")
        log = "\n".join(f"[{l['stage']}/{l['level']}] {l['message']}" for l in d["log"])
        self._set("Processing", log or "(empty)")

    def _set(self, tab_prefix: str, text: str):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i).startswith(tab_prefix):
                w = self.tabs.widget(i)
                if text.strip().startswith("<"):
                    w.setHtml(text)
                else:
                    w.setPlainText(text)
                return
