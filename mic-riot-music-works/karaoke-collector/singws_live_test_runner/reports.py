"""Local, redacted test-run report exports."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .domain import RunRecord, SongResult


class ReportExporter:
    def __init__(self, *, redactions: tuple[str, ...] = ()) -> None:
        self._redactions = tuple(value for value in redactions if value)

    def export_json(self, path: Path, run: RunRecord, results: tuple[SongResult, ...], evidence: tuple[str, ...]) -> Path:
        payload = {"run_id": run.id, "mode": run.mode, "results": [asdict(item) for item in results], "evidence": [self._redact(item) for item in evidence]}
        path.write_text(json.dumps(payload, indent=2, default=str))
        return path

    def export_html(self, path: Path, run: RunRecord, results: tuple[SongResult, ...], evidence: tuple[str, ...]) -> Path:
        rows = "".join(f"<li>#{item.request_ordinal}: video {item.video_score}/10, track {item.track_score}/10</li>" for item in results)
        notes = "".join(f"<li>{self._redact(item)}</li>" for item in evidence)
        path.write_text(f"<h1>Karaoke Collector</h1><p>Run: {run.id}</p><ul>{rows}</ul><ul>{notes}</ul>")
        return path

    def _redact(self, value: str) -> str:
        for secret in self._redactions:
            value = value.replace(secret, "[REDACTED]")
        return value
