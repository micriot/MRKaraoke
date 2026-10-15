"""Resilient run control and timing classifications."""

from __future__ import annotations

from enum import StrEnum

from .domain import RunRecord, RunState


class SilenceSeverity(StrEnum):
    INFORMATIONAL = "informational"
    WARNING = "warning"
    FAILURE = "failure"


class RunCoordinator:
    def __init__(self, run: RunRecord) -> None:
        self.run = run
        self.failures: tuple[tuple[int, str], ...] = ()

    def start(self) -> None:
        if self.run.state is not RunState.READY:
            raise PermissionError("run must be READY after explicit confirmation")
        self.run = self.run.transition_to(RunState.RUNNING)

    def stop(self) -> None:
        if self.run.state is RunState.RUNNING:
            self.run = self.run.transition_to(RunState.STOPPING)

    def record_song_failure(self, ordinal: int, message: str) -> None:
        self.failures = (*self.failures, (ordinal, message))

    @staticmethod
    def classify_silence(duration_seconds: float) -> SilenceSeverity:
        if duration_seconds >= 1:
            return SilenceSeverity.FAILURE
        if duration_seconds >= 0.25:
            return SilenceSeverity.WARNING
        return SilenceSeverity.INFORMATIONAL
