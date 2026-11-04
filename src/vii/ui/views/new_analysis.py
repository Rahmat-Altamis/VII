"""New Analysis view: local MP4 or public URL, metadata preview, start."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class NewAnalysisView(QWidget):
    def __init__(self, service, on_started=None, parent=None):
        super().__init__(parent)
        self._service = service
        self._on_started = on_started
        lay = QVBoxLayout(self)
        t = QLabel("New Analysis")
        t.setObjectName("h1")
        lay.addWidget(t)

        lay.addWidget(QLabel("Input type:"))
        self.kind = QComboBox()
        self.kind.addItems(["Local MP4 file", "Public video URL"])
        self.kind.currentIndexChanged.connect(self._toggle)
        lay.addWidget(self.kind)

        row = QHBoxLayout()
        self.path = QLineEdit()
        self.path.setPlaceholderText("/path/to/video.mp4  or  https://…")
        self.browse = QPushButton("Browse…")
        self.browse.clicked.connect(self._browse)
        row.addWidget(self.path)
        row.addWidget(self.browse)
        lay.addLayout(row)
        self.meta = QLabel("")
        self.meta.setObjectName("dim")
        lay.addWidget(self.meta)

        self.title = QLineEdit()
        self.title.setPlaceholderText("Title (optional)")
        lay.addWidget(self.title)
        self.run_btn = QPushButton("Start Analysis")
        self.run_btn.clicked.connect(self._start)
        lay.addWidget(self.run_btn)
        lay.addStretch(1)
        self._toggle()

    def _toggle(self):
        self.browse.setVisible(self.kind.currentIndex() == 0)

    def _browse(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select video", "",
                                           "Video (*.mp4 *.mkv *.mov *.webm *.avi)")
        if f:
            self.path.setText(f)
            try:
                from vii.media import ffmpeg as ff
                m = ff.metadata_summary(ff.probe(f))
                self.meta.setText(f"{m.get('format','?')} · {m.get('duration_s',0):.1f}s · "
                                  f"{m.get('width','?')}x{m.get('height','?')}")
            except Exception as e:  # noqa: BLE001
                self.meta.setText(f"Preview unavailable: {e}")

    def _start(self):
        from vii.domain.schemas import AnalysisCreate
        val = self.path.text().strip()
        if not val:
            QMessageBox.warning(self, "Missing input", "Provide a file path or URL.")
            return
        try:
            if self.kind.currentIndex() == 0:
                req = AnalysisCreate(source={"kind": "local_file", "local_path": val},
                                     title=self.title.text() or None)
            else:
                req = AnalysisCreate(source={"kind": "public_url", "url": val},
                                     title=self.title.text() or None)
            jid = self._service.create(req)
        except ValueError as e:
            QMessageBox.warning(self, "Invalid input", str(e))
            return
        if self._on_started:
            self._on_started(jid)
