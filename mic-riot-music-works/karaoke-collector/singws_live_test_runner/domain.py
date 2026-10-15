"""Immutable records for a local SingWS test run."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4


class RunMode(StrEnum):
    PRE_SHOW = "pre_show"
    LIVE_TEST = "live_test"


class RunState(StrEnum):
    DRAFT = "draft"
    PREFLIGHT = "preflight"
    READY = "ready"
    RUNNING = "running"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"


_ALLOWED_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.DRAFT: {RunState.PREFLIGHT, RunState.FAILED},
    RunState.PREFLIGHT: {RunState.READY, RunState.FAILED},
    RunState.READY: {RunState.RUNNING, RunState.FAILED},
    RunState.RUNNING: {RunState.STOPPING, RunState.COMPLETED, RunState.FAILED},
    RunState.STOPPING: {RunState.COMPLETED, RunState.FAILED},
    RunState.COMPLETED: set(),
    RunState.FAILED: set(),
}


@dataclass(frozen=True, slots=True)
class ObservedEvent:
    run_id: str
    kind: str
    occurred_at: datetime
    details: dict[str, str]


@dataclass(frozen=True, slots=True)
class TestRequest:
    __test__ = False

    run_id: str
    ordinal: int
    singer_first_name: str
    singer_last_name: str
    song_id: str
    song_title: str
    song_artist: str

    @property
    def singer_display_name(self) -> str:
        return f"{self.singer_first_name} {self.singer_last_name}"


@dataclass(frozen=True, slots=True)
class SongResult:
    run_id: str
    request_ordinal: int
    completed: bool
    video_score: int | None
    track_score: int | None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RunRecord:
    id: str
    mode: RunMode
    target_song_count: int
    state: RunState
    created_at: datetime
    events: tuple[ObservedEvent, ...] = field(default_factory=tuple)

    @classmethod
    def new(cls, *, mode: RunMode, target_song_count: int) -> "RunRecord":
        if not 1 <= target_song_count <= 100:
            raise ValueError("target_song_count must be between 1 and 100")
        return cls(
            id=str(uuid4()),
            mode=mode,
            target_song_count=target_song_count,
            state=RunState.DRAFT,
            created_at=datetime.now(UTC),
        )

    def transition_to(self, state: RunState) -> "RunRecord":
        if state not in _ALLOWED_TRANSITIONS[self.state]:
            raise ValueError(f"Illegal run transition: {self.state} -> {state}")
        return replace(self, state=state)

    def append_event(self, event: ObservedEvent) -> "RunRecord":
        if event.run_id != self.id:
            raise ValueError("Event does not belong to this run")
        return replace(self, events=(*self.events, event))
