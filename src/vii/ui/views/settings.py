"""Settings view: Meta API config, offline mode, connection test, diagnostics."""
from __future__ import annotations

import shutil

from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class SettingsView(QWidget):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service
        s = service.settings
        lay = QVBoxLayout(self)
        t = QLabel("Settings")
        t.setObjectName("h1")
        lay.addWidget(t)
        form = QFormLayout()
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("(stored in OS keyring, never committed)")
        self.base = QLineEdit(s.meta_base_url)
        self.model = QLineEdit(s.meta_model)
        self.tmodel = QLineEdit(s.meta_transcription_model)
        self.offline = QCheckBox("Offline / mock mode (deterministic fixtures)")
        self.offline.setChecked(s.offline_mode or not s.has_api_key)
        form.addRow("MODEL_API_KEY:", self.key)
        form.addRow("META_BASE_URL:", self.base)
        form.addRow("META_MODEL:", self.model)
        form.addRow("Transcription model:", self.tmodel)
        form.addRow("", self.offline)
        lay.addLayout(form)
        self.test_btn = QPushButton("Test API Connection")
        self.test_btn.clicked.connect(self._test)
        self.save_btn = QPushButton("Save (key to OS keyring)")
        self.save_btn.clicked.connect(self._save)
        self.remove_btn = QPushButton("Remove stored key")
        self.remove_btn.clicked.connect(self._remove)
        lay.addWidget(self.test_btn)
        lay.addWidget(self.save_btn)
        lay.addWidget(self.remove_btn)
        self.diag = QLabel("")
        self.diag.setObjectName("dim")
        self.diag.setWordWrap(True)
        lay.addWidget(self.diag)
        lay.addStretch(1)
        self.refresh()

    def refresh(self):
        s = self._service.settings
        ff = shutil.which(s.ffmpeg_bin) is not None
        fp = shutil.which(s.ffprobe_bin) is not None
        key_state = f"set ({s.key_source})" if s.has_api_key else "NOT SET"
        self.diag.setText(
            f"Mode: {'LIVE' if s.live_mode else ('SYNTHETIC DEMO (explicit opt-in)' if s.demo_enabled else 'NO KEY, provider analysis unavailable')}\n"
            f"API key: {key_state}\n"
            f"ffmpeg: {'found' if ff else 'MISSING'} · ffprobe: {'found' if fp else 'MISSING'}\n"
            f"DB: {s.database_url} · storage: {s.storage_dir}")

    def _test(self):
        import httpx
        base = self.base.text().rstrip("/")
        key = self.key.text().strip() or self._service.settings.effective_api_key
        if not key:
            QMessageBox.information(self, "No key", "Enter MODEL_API_KEY to test (provider-backed analysis requires a key; synthetic demo needs explicit opt-in).")
            return
        try:
            r = httpx.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=15)
            QMessageBox.information(self, "Connection", f"HTTP {r.status_code}: "
                                    + ("OK, key accepted" if r.status_code < 400 else r.text[:300]))
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Connection failed", str(e)[:500])

    def _save(self):
        from vii.keystore import store_api_key
        s = self._service.settings
        new_key = self.key.text().strip()
        backend = None
        if new_key:
            # Secret goes to OS keyring (0600-file fallback), never to .env.
            backend = store_api_key(new_key, s.storage_dir)
            self.key.clear()
        existing = {}
        try:
            for ln in open(".env"):
                if "=" in ln and not ln.startswith("#"):
                    k, v = ln.strip().split("=", 1)
                    existing[k.strip()] = v
        except FileNotFoundError:
            pass
        if backend is not None:
            existing.pop("MODEL_API_KEY", None)  # key now lives in the keyring
        existing.update({
            "META_BASE_URL": self.base.text().strip(),
            "META_MODEL": self.model.text().strip(),
            "META_TRANSCRIPTION_MODEL": self.tmodel.text().strip(),
            "VII_OFFLINE_MODE": "true" if self.offline.isChecked() else "false",
        })
        with open(".env", "w") as f:
            for k, v in existing.items():
                f.write(f"{k}={v}\n")
        note = f"API key stored via {backend}. " if backend else "API key unchanged. "
        QMessageBox.information(self, "Saved", note + "Wrote .env, restart the app to apply.")

    def _remove(self):
        from vii.keystore import store_api_key
        store_api_key("", self._service.settings.storage_dir)
        self.key.clear()
        QMessageBox.information(
            self, "Removed",
            "Stored provider key removed (keyring + fallback cleared). "
            "An env MODEL_API_KEY, if set, is unchanged.")
        self.refresh()
