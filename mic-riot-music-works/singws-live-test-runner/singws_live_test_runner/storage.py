"""SQLite persistence for local test-run records and evidence."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .domain import ObservedEvent, RunMode, RunRecord, RunState, SongResult


@dataclass(frozen=True, slots=True)
class LoadedRun:
    run: RunRecord
    events: tuple[ObservedEvent, ...]
    results: tuple[SongResult, ...]


class RunStore:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    target_song_count INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    details_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS results (
                    run_id TEXT NOT NULL,
                    request_ordinal INTEGER NOT NULL,
                    completed INTEGER NOT NULL,
                    video_score INTEGER,
                    track_score INTEGER,
                    notes_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, request_ordinal)
                );
                """
            )

    def create_run(self, run: RunRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, ?)",
                (run.id, run.mode, run.target_song_count, run.state, run.created_at.isoformat()),
            )

    def append_event(self, event: ObservedEvent) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO events (run_id, kind, occurred_at, details_json) VALUES (?, ?, ?, ?)",
                (event.run_id, event.kind, event.occurred_at.isoformat(), json.dumps(event.details, sort_keys=True)),
            )

    def save_result(self, result: SongResult) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO results VALUES (?, ?, ?, ?, ?, ?)",
                (
                    result.run_id,
                    result.request_ordinal,
                    result.completed,
                    result.video_score,
                    result.track_score,
                    json.dumps(result.notes),
                ),
            )

    def load_run(self, run_id: str) -> LoadedRun:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            run = RunRecord(
                id=row["id"],
                mode=RunMode(row["mode"]),
                target_song_count=row["target_song_count"],
                state=RunState(row["state"]),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            events = tuple(
                ObservedEvent(
                    run_id=item["run_id"],
                    kind=item["kind"],
                    occurred_at=datetime.fromisoformat(item["occurred_at"]),
                    details=json.loads(item["details_json"]),
                )
                for item in connection.execute(
                    "SELECT * FROM events WHERE run_id = ? ORDER BY sequence", (run_id,)
                )
            )
            results = tuple(
                SongResult(
                    run_id=item["run_id"],
                    request_ordinal=item["request_ordinal"],
                    completed=bool(item["completed"]),
                    video_score=item["video_score"],
                    track_score=item["track_score"],
                    notes=tuple(json.loads(item["notes_json"])),
                )
                for item in connection.execute(
                    "SELECT * FROM results WHERE run_id = ? ORDER BY request_ordinal", (run_id,)
                )
            )
        return LoadedRun(run=run, events=events, results=results)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection
