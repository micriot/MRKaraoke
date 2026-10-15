"""Application entry point."""

from PyQt6.QtWidgets import QApplication

from .config import RunConfiguration
from .preflight import PreflightService
from .ui.main_window import MainWindow, PreflightViewModel


def main() -> int:
    application = QApplication([])
    configuration = RunConfiguration("", "https://micriot.net", "", 10, 3, "SC – Neon Moon – Brooks & Dunn", "SingWS")
    view_model = PreflightViewModel(PreflightService().evaluate(configuration), audio_route="Waiting for SingWS", media_drive="Not checked", display="Mock pending")
    window = MainWindow(view_model)
    window.show()
    return application.exec()
