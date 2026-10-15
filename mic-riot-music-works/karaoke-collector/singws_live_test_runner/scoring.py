"""Explainable 1–10 media score helper."""

from __future__ import annotations


def score_from_failures(failure_count: int) -> int:
    return max(1, 10 - failure_count * 2)
