"""Confirmed public Mic Riot request-page adapter."""

from __future__ import annotations

import json
from dataclasses import dataclass
from time import monotonic
from typing import Callable, Protocol
from urllib.parse import urlencode

from .config import Redactor
from .domain import TestRequest


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: str


class HttpTransport(Protocol):
    def request(self, method: str, url: str, form: dict[str, str] | None = None) -> HttpResponse: ...


@dataclass(frozen=True, slots=True)
class Song:
    song_id: str
    title: str
    artist: str
    source: str


@dataclass(frozen=True, slots=True)
class RequestAcknowledgement:
    request_id: str
    client_correlation_id: str


class MicRiotClient:
    def __init__(self, *, base_url: str, tenant_id: str, transport: HttpTransport, redactor: Redactor, clock: Callable[[], float] = monotonic) -> None:
        self._base_url = base_url.rstrip("/")
        self._tenant_id = tenant_id
        self._transport = transport
        self._redactor = redactor
        self._clock = clock
        self._tenant_verified = False
        self._last_submission_at: float | None = None

    def verify_tenant(self) -> None:
        response = self._transport.request("GET", self._url("index.php", user=self._tenant_id))
        self._require_success(response)
        try:
            tenant = json.loads(response.body).get("tenant")
        except json.JSONDecodeError:
            tenant = self._tenant_id if f"const TENANT = '{self._tenant_id}';" in response.body else None
        if tenant != self._tenant_id:
            raise PermissionError("tenant mismatch")
        self._tenant_verified = True

    def songbook(self, query: str) -> tuple[Song, ...]:
        response = self._transport.request("GET", self._url("search.php", user=self._tenant_id, q=query, offset="0"))
        payload = self._payload(response)
        return tuple(Song(str(item["song_id"]), str(item["title"]), str(item["artist"]), str(item["source"])) for item in payload["results"])

    def create_request(self, request: TestRequest, *, confirmed: bool) -> RequestAcknowledgement:
        if not self._tenant_verified:
            raise PermissionError("tenant must be verified before request creation")
        if not confirmed:
            raise PermissionError("explicit operator confirmation is required")
        now = self._clock()
        if self._last_submission_at is not None and now - self._last_submission_at < 1:
            raise RuntimeError("request pacing must be at least one second")
        form = {"songid": request.song_id, "selected_source": "local", "artist": request.song_artist, "title": request.song_title, "singer": request.singer_display_name, "key": "0"}
        response = self._transport.request("POST", self._url("submitreq.php", user=self._tenant_id), form)
        payload = self._payload(response)
        if payload.get("status") not in {"success", "waitlisted"}:
            raise RuntimeError(self._redactor.redact(str(payload.get("message", "request failed"))))
        request_id = str(payload.get("request_id", payload.get("id", "")))
        if not request_id:
            raise RuntimeError("request response did not include an id")
        self._last_submission_at = now
        return RequestAcknowledgement(request_id=request_id, client_correlation_id=request.run_id)

    def _url(self, path: str, **query: str) -> str:
        return f"{self._base_url}/{path}?{urlencode(query)}"

    def _payload(self, response: HttpResponse) -> dict[str, object]:
        self._require_success(response)
        try:
            return json.loads(response.body)
        except json.JSONDecodeError as error:
            raise RuntimeError(self._redactor.redact_exception(error)) from error

    def _require_success(self, response: HttpResponse) -> None:
        if response.status >= 400:
            raise RuntimeError(self._redactor.redact(f"Mic Riot HTTP {response.status}: {response.body}"))
