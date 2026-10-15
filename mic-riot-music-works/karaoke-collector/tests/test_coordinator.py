from __future__ import annotations

import pytest

from singws_live_test_runner.coordinator import RunCoordinator, SilenceSeverity
from singws_live_test_runner.domain import RunMode, RunRecord, RunState


def test_coordinator_cannot_start_without_ready_confirmation() -> None:
    coordinator = RunCoordinator(RunRecord.new(mode=RunMode.LIVE_TEST, target_song_count=10))

    with pytest.raises(PermissionError, match="READY"):
        coordinator.start()


def test_song_failure_is_recorded_without_stopping_run() -> None:
    run = RunRecord.new(mode=RunMode.LIVE_TEST, target_song_count=10).transition_to(RunState.PREFLIGHT).transition_to(RunState.READY)
    coordinator = RunCoordinator(run)

    coordinator.start()
    coordinator.record_song_failure(1, "black frame")

    assert coordinator.run.state is RunState.RUNNING
    assert coordinator.failures == ((1, "black frame"),)


def test_silence_severity_thresholds() -> None:
    assert RunCoordinator.classify_silence(0.249) is SilenceSeverity.INFORMATIONAL
    assert RunCoordinator.classify_silence(0.25) is SilenceSeverity.WARNING
    assert RunCoordinator.classify_silence(1.0) is SilenceSeverity.FAILURE
