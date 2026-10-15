"""Deterministic test-singer manifests and safe rolling batches."""

from __future__ import annotations

from random import Random

from .api import Song
from .domain import TestRequest


_FIRST_NAMES = (
    "Jordan", "Avery", "Casey", "Morgan", "Taylor", "Riley", "Cameron", "Parker", "Quinn", "Hayden",
    "Alex", "Bailey", "Drew", "Emerson", "Finley", "Gray", "Harper", "Jamie", "Kendall", "Logan",
    "Marley", "Noel", "Payton", "Reese", "Sage", "Skyler", "Tatum", "Valerie", "Wesley", "Zion",
    "Adrian", "Blake", "Charlie", "Dakota", "Elliot", "Frankie", "Gavin", "Hollis", "Isaac", "Jules",
    "Kai", "Lane", "Micah", "Nico", "Oakley", "Presley", "River", "Sawyer", "Shawn", "Toby",
    "Uma", "Vaughn", "Winter", "Xander", "Yvette", "Zane", "Ari", "Brett", "Corey", "Devon",
    "Ellis", "Flynn", "Greer", "Haven", "Indigo", "Jaden", "Keegan", "Lennon", "Milan", "Navy",
    "Onyx", "Phoenix", "Rowan", "Spencer", "Teagan", "Urban", "Vera", "Wren", "Yuri", "Zuri",
    "Amari", "Briar", "Cleo", "Dallas", "Eden", "Fable", "Gemma", "Hugo", "Iris", "Jasper",
    "Kira", "Luca", "Mira", "Nolan", "Opal", "Paige", "Remy", "Sloane", "Theo", "Willow",
)


class ScenarioGenerator:
    def build(self, *, seed: int, run_id: str, count: int, songs: tuple[Song, ...]) -> tuple[TestRequest, ...]:
        if not 1 <= count <= 100:
            raise ValueError("count must be between 1 and 100")
        if len({song.song_id for song in songs}) < count:
            raise ValueError("songbook does not contain enough unique songs")
        random = Random(seed)
        chosen_names = random.sample(_FIRST_NAMES, count)
        chosen_songs = random.sample(list(songs), count)
        return tuple(
            TestRequest(run_id, ordinal, name, "Test", song.song_id, song.title, song.artist)
            for ordinal, (name, song) in enumerate(zip(chosen_names, chosen_songs, strict=True), start=1)
        )


class BatchScheduler:
    def next_batch(
        self,
        manifest: tuple[TestRequest, ...],
        *,
        submitted_ordinals: set[int],
        completed_ordinals: set[int],
    ) -> tuple[TestRequest, ...]:
        pending = len(submitted_ordinals - completed_ordinals)
        if not submitted_ordinals:
            return manifest[:10]
        if len(completed_ordinals) < 8 or pending != 2:
            return ()
        remaining = tuple(item for item in manifest if item.ordinal not in submitted_ordinals)
        return remaining[:10]
