"""Mic Riot-style preflight view model and initial desktop shell."""

from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QMainWindow, QVBoxLayout, QWidget

from ..preflight import PreflightResult, PreflightService


class PreflightViewModel:
    def __init__(self, result: PreflightResult, *, audio_route: str, media_drive: str, display: str) -> None:
        self._result = result
        self.summary = "\n".join((f"Tenant: {result.configuration.tenant_id}", f"Songs: {result.configuration.target_song_count}", f"Audio: {audio_route}", f"Drive: {media_drive}", f"Display: {display}"))

    def can_start(self, confirmation_text: str) -> bool:
        return self._result.is_ready and confirmation_text == PreflightService.confirmation_text


class MainWindow(QMainWindow):
    def __init__(self, view_model: PreflightViewModel) -> None:
        super().__init__()
        self.setWindowTitle("Karaoke Collector")
        content = QWidget()
        layout = QVBoxLayout(content)
        title = QLabel("KARAOKE COLLECTOR")
        title.setStyleSheet("font-weight: 700; color: #48a9ff; font-size: 20px;")
        layout.addWidget(title)
        layout.addWidget(QLabel("Pre-show checks and diagnostics for your SingWS hosting experience"))
        layout.addWidget(QLabel(view_model.summary))
        self.setCentralWidget(content)
