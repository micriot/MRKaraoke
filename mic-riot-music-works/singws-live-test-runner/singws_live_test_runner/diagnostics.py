"""Local audio/display readiness checks and fast pre-show choreography."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AudioRouteStatus:
    device_name: str
    ready: bool
    message: str


class AudioRouteInspector:
    def inspect(self, device_name: str) -> AudioRouteStatus:
        built_in = "speaker" in device_name.lower() and "headphone" not in device_name.lower()
        return AudioRouteStatus(
            device_name=device_name,
            ready=built_in,
            message="Mac built-in speakers ready" if built_in else "Test audio must remain on Mac built-in speakers",
        )


@dataclass(frozen=True, slots=True)
class DisplayFrame:
    mode: str
    visible_text: str


class DisplayMock:
    def render(self, *, rotation: tuple[str, ...], current_song: str, physical_display_present: bool) -> DisplayFrame:
        mode = "physical+mock" if physical_display_present else "mock"
        return DisplayFrame(mode=mode, visible_text=f"UP NEXT: {', '.join(rotation)} | NOW PLAYING: {current_song}")


@dataclass(frozen=True, slots=True)
class PreShowCheckpoint:
    provider: str
    fast_forward_seconds: int


class PreShowScenario:
    def checkpoints(self) -> tuple[PreShowCheckpoint, ...]:
        return (
            PreShowCheckpoint("local", 30),
            PreShowCheckpoint("karafun", 30),
            PreShowCheckpoint("local", 30),
        )
