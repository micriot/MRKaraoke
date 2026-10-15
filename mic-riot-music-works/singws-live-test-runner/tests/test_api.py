from __future__ import annotations

import json
from pathlib import Path

import pytest

from singws_live_test_runner.api import HttpResponse, MicRiotClient
from singws_live_test_runner.config import Redactor
from singws_live_test_runner.domain import RunMode, RunRecord, TestRequest


class FakeTransport:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str, dict[str, str] | None]] = []

    def request(self, method: str, url: str, form: dict[str, str] | None = None) -> HttpResponse:
        self.calls.append((method, url, form))
        return self.responses.pop(0)


def fixture_response() -> HttpResponse:
    payload = Path("tests/fixtures/micriot/search_neon_moon.json").read_text()
    return HttpResponse(status=200, body=payload)


def client_with(transport: FakeTransport) -> MicRiotClient:
    return MicRiotClient(
        base_url="https://micriot.net",
        tenant_id="mrk",
        transport=transport,
        redactor=Redactor(("secret",)),
        clock=lambda: 10.0,
    )


def test_songbook_uses_confirmed_public_search_schema() -> None:
    transport = FakeTransport([fixture_response()])

    songs = client_with(transport).songbook("Neon Moon")

    assert songs[0].song_id == "1618699"
    assert transport.calls == [
        ("GET", "https://micriot.net/search.php?user=mrk&q=Neon+Moon&offset=0", None)
    ]


def test_wrong_tenant_response_blocks_request_creation() -> None:
    transport = FakeTransport([HttpResponse(status=200, body=json.dumps({"tenant": "other"}))])

    with pytest.raises(PermissionError, match="tenant mismatch"):
        client_with(transport).verify_tenant()


def test_create_request_requires_confirmed_tenant_and_keeps_correlation_local() -> None:
    transport = FakeTransport(
        [
            HttpResponse(status=200, body=json.dumps({"tenant": "mrk"})),
            HttpResponse(status=200, body=json.dumps({"status": "success", "request_id": "r-1"})),
        ]
    )
    run = RunRecord.new(mode=RunMode.LIVE_TEST, target_song_count=1)
    request = TestRequest(
        run_id=run.id,
        ordinal=1,
        singer_first_name="Jordan",
        singer_last_name="Test",
        song_id="1618699",
        song_title="Neon Moon",
        song_artist="Brooks & Dunn",
    )
    client = client_with(transport)

    client.verify_tenant()
    acknowledgement = client.create_request(request, confirmed=True)

    assert acknowledgement.request_id == "r-1"
    assert transport.calls[1][2]["singer"] == "Jordan Test"
    assert acknowledgement.client_correlation_id == run.id
    assert "run_correlation_id" not in transport.calls[1][2]


def test_http_errors_are_redacted() -> None:
    transport = FakeTransport([HttpResponse(status=500, body="server saw secret")])

    with pytest.raises(RuntimeError) as error:
        client_with(transport).songbook("Neon Moon")

    assert "secret" not in str(error.value)
