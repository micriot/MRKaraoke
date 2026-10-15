"""Narrow local SingWS bridge; live accessibility control is added after UI discovery."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SingWSObservation:
    connected: bool
    state: str


class SingWSBridge:
    def observe(self) -> SingWSObservation:
        return SingWSObservation(connected=False, state="not connected")
