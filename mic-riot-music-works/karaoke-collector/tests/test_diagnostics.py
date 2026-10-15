from __future__ import annotations

from singws_live_test_runner.diagnostics import AudioRouteInspector, DisplayMock, PreShowScenario


def test_builtin_speakers_are_allowed_and_headphones_block_without_mutation() -> None:
    inspector = AudioRouteInspector()

    built_in = inspector.inspect("MacBook Pro Speakers")
    headphones = inspector.inspect("External Headphone Jack")

    assert built_in.ready is True
    assert headphones.ready is False
    assert headphones.device_name == "External Headphone Jack"


def test_display_mock_renders_without_physical_display() -> None:
    mock = DisplayMock()

    frame = mock.render(rotation=("Jordan Test",), current_song="Neon Moon", physical_display_present=False)

    assert frame.mode == "mock"
    assert "Jordan Test" in frame.visible_text
    assert "Neon Moon" in frame.visible_text


def test_pre_show_sequence_is_local_karafun_local_with_fast_forward_checkpoints() -> None:
    checkpoints = PreShowScenario().checkpoints()

    assert [(item.provider, item.fast_forward_seconds) for item in checkpoints] == [
        ("local", 30),
        ("karafun", 30),
        ("local", 30),
    ]
