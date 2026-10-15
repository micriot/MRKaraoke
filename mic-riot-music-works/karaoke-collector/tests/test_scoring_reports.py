from __future__ import annotations

import json

from singws_live_test_runner.config import RunConfiguration
from singws_live_test_runner.domain import RunMode, RunRecord, SongResult
from singws_live_test_runner.preflight import PreflightService
from singws_live_test_runner.reports import ReportExporter
from singws_live_test_runner.ui.main_window import PreflightViewModel


def configuration() -> RunConfiguration:
    return RunConfiguration("mrk", "https://micriot.net", "key-ref", 10, 3, "SC – Neon Moon – Brooks & Dunn", "SingWS")


def test_preflight_view_model_shows_required_readiness_items_and_requires_exact_confirmation() -> None:
    result = PreflightService().evaluate(configuration())
    model = PreflightViewModel(result, audio_route="MacBook Pro Speakers", media_drive="Connected", display="Mock ready")

    assert "Tenant: mrk" in model.summary
    assert "Songs: 10" in model.summary
    assert "MacBook Pro Speakers" in model.summary
    assert model.can_start("start") is False
    assert model.can_start("OK, Start Test Run") is True


def test_report_exports_scores_and_redacts_evidence(tmp_path) -> None:
    run = RunRecord.new(mode=RunMode.LIVE_TEST, target_song_count=1)
    result = SongResult(run.id, 1, True, 9, 8, ("transition clean",))
    exporter = ReportExporter(redactions=("secret",))

    json_path = exporter.export_json(tmp_path / "report.json", run, (result,), ("secret evidence",))
    html_path = exporter.export_html(tmp_path / "report.html", run, (result,), ("secret evidence",))

    assert json.loads(json_path.read_text())["results"][0]["video_score"] == 9
    assert "[REDACTED]" in html_path.read_text()
    assert "secret" not in html_path.read_text()
    assert "Karaoke Collector" in html_path.read_text()
