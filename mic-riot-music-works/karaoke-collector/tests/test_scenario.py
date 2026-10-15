from __future__ import annotations

import pytest

from singws_live_test_runner.api import Song
from singws_live_test_runner.scenario import BatchScheduler, ScenarioGenerator


def songs(count: int = 20) -> tuple[Song, ...]:
    return tuple(Song(str(index), f"Song {index}", "Artist", "local") for index in range(count))


def test_manifest_is_seeded_unique_and_uses_test_last_name() -> None:
    manifest = ScenarioGenerator().build(seed=7, run_id="run-1", count=20, songs=songs())

    assert len(manifest) == 20
    assert len({item.singer_display_name for item in manifest}) == 20
    assert {item.singer_last_name for item in manifest} == {"Test"}
    assert len({item.song_id for item in manifest}) == 20
    assert manifest == ScenarioGenerator().build(seed=7, run_id="run-1", count=20, songs=songs())


def test_manifest_rejects_count_larger_than_unique_songbook() -> None:
    with pytest.raises(ValueError, match="unique songs"):
        ScenarioGenerator().build(seed=1, run_id="run-1", count=3, songs=songs(2))


def test_scheduler_starts_with_ten_and_replenishes_only_after_eight_complete() -> None:
    manifest = ScenarioGenerator().build(seed=7, run_id="run-1", count=25, songs=songs(25))
    scheduler = BatchScheduler()

    initial = scheduler.next_batch(manifest, submitted_ordinals=set(), completed_ordinals=set())
    no_top_up = scheduler.next_batch(manifest, submitted_ordinals={item.ordinal for item in initial}, completed_ordinals=set(range(1, 8)))
    top_up = scheduler.next_batch(manifest, submitted_ordinals={item.ordinal for item in initial}, completed_ordinals=set(range(1, 9)))

    assert [item.ordinal for item in initial] == list(range(1, 11))
    assert no_top_up == ()
    assert [item.ordinal for item in top_up] == list(range(11, 21))
