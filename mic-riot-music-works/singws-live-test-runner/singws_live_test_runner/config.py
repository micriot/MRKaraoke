"""Safe configuration values and secret redaction."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class RunConfiguration:
    tenant_id: str
    api_base_url: str
    credential_reference: str
    target_song_count: int
    request_pace_seconds: int
    baseline_song: str
    required_host_name: str

    def replace(self, **changes: object) -> "RunConfiguration":
        return replace(self, **changes)

    def validation_messages(self) -> tuple[str, ...]:
        messages: list[str] = []
        if not self.tenant_id.strip():
            messages.append("tenant_id is required")
        if not self.api_base_url.startswith("https://"):
            messages.append("api_base_url must use https")
        if not self.credential_reference.strip():
            messages.append("credential_reference is required")
        if not 1 <= self.target_song_count <= 100:
            messages.append("target_song_count must be between 1 and 100")
        if self.request_pace_seconds < 1:
            messages.append("request_pace_seconds must be at least 1")
        if not self.baseline_song.strip():
            messages.append("baseline_song is required")
        if not self.required_host_name.strip():
            messages.append("required_host_name is required")
        return tuple(messages)


class Redactor:
    def __init__(self, secrets: tuple[str, ...]) -> None:
        self._secrets = tuple(secret for secret in secrets if secret)

    def redact(self, value: str) -> str:
        for secret in self._secrets:
            value = value.replace(secret, "[REDACTED]")
        return value

    def redact_exception(self, error: BaseException) -> str:
        return self.redact(str(error))
