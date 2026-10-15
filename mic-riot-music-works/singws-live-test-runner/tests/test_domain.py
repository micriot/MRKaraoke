from __future__ import annotations

from datetime import UTC, datetime

import pytest

from singws_live_test_runner.domain import (
    ObservedEvent,
    RunMode,
    RunRecord,
    RunState,
    SongResult,
    TestRequest,
)
from singws_live_test_runner.storage import RunStore


def test_run_record_allows_only_legal_state_transitions() -> None:
    run = RunRecord.new(mode=RunMode.LIVE_TEST, target_song_count=10)

    assert run.state is RunState.DRAFT
    preflight = run.transition_to(RunState.PREFLIGHT)
    ready = preflight.transition_to(RunState.READY)
    assert preflight.state is RunState.PREFLIGHT
    assert ready.transition_to(RunState.RUNNING).state is RunState.RUNNING

    with pytest.raises(ValueError, match="Illegal run transition"):
        run.transition_to(RunState.COMPLETED)


def test_observed_events_are_immutable_and_appended_in_order() -> None:
    run = RunRecord.new(mode=RunMode.PRE_SHOW, target_song_count=3)
    event = ObservedEvent(
        run_id=run.id,
        kind="bgm_stopped",
        occurred_at=datetime.now(UTC),
        details={"source": "bridge"},
    )

    updated = run.append_event(event)

    assert run.events == ()
    assert updated.events == (event,)
    with pytest.raises(AttributeError):
        event.kind = "changed"  # type: ignore[misc]


def test_run_store_reloads_partial_run_with_events_and_results(tmp_path) -> None:
    store = RunStore(tmp_path / "runs.sqlite3")
    run = RunRecord.new(mode=RunMode.LIVE_TEST, target_song_count=20)
    request = TestRequest(
        run_id=run.id,
        ordinal=1,
        singer_first_name="Jordan",
        singer_last_name="Test",
        song_id="SC-001",
        song_title="Neon Moon",
        song_artist="Brooks & Dunn",
    )
    event = ObservedEvent(
        run_id=run.id,
        kind="queue_arrived",
        occurred_at=datetime.now(UTC),
        details={"request_id": "server-1"},
    )
    result = SongResult(
        run_id=run.id,
        request_ordinal=1,
        completed=False,
        video_score=None,
        track_score=None,
        notes=("still queued",),
    )

    store.create_run(run)
    store.append_event(event)
    store.save_result(result)

    restored = store.load_run(run.id)

    assert restored.run == run
    assert restored.events == (event,)
    assert restored.results == (result,)
    assert request.singer_display_name == "Jordan Test"
