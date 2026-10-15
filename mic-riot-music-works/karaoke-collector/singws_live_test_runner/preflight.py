"""Validation and explicit human confirmation before any test action."""

from __future__ import annotations

from dataclasses import dataclass

from .config import RunConfiguration
from .domain import RunRecord, RunState


@dataclass(frozen=True, slots=True)
class PreflightResult:
    configuration: RunConfiguration
    blocking_messages: tuple[str, ...]

    @property
    def is_ready(self) -> bool:
        return not self.blocking_messages


class PreflightService:
    confirmation_text = "OK, Start Test Run"

    def evaluate(self, configuration: RunConfiguration) -> PreflightResult:
        return PreflightResult(
            configuration=configuration,
            blocking_messages=configuration.validation_messages(),
        )

    def confirm_ready(
        self,
        run: RunRecord,
        result: PreflightResult,
        confirmation_text: str,
    ) -> RunRecord:
        if not result.is_ready:
            raise PermissionError("preflight has blocking messages")
        if confirmation_text != self.confirmation_text:
            raise PermissionError("explicit operator confirmation is required")
        preflight = run.transition_to(RunState.PREFLIGHT)
        return preflight.transition_to(RunState.READY)
