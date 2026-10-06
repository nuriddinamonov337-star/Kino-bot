"""Tests for window-based moment selection (Clip Generator / Adversitas style)."""

import pytest

from app.ai.client import AimlApiError
from app.video.moments import (
    Moment,
    Window,
    select_moment_in_window,
    select_moments_by_windows,
    snap_to_sentence_boundary,
    split_into_windows,
    validate_moment,
)


def _transcript() -> list[dict[str, object]]:
    """A 12-minute transcript with contiguous 10-second segments.

    Boundaries fall on multiples of 10 (0, 10, 20, ...), matching how Whisper
    emits back-to-back segments in practice.
    """
    return [
        {"start": float(i * 10), "end": float(i * 10 + 10), "text": f"line {i}"}
        for i in range(72)
    ]


def _ai(payload: dict):
    async def complete(*, system: str, user: str) -> dict:
        return payload

    return complete


def _ai_sequence(payloads: list[dict]):
    """Return an AI stub that yields each payload in order, then repeats the last."""
    calls = {"n": 0}

    async def complete(*, system: str, user: str) -> dict:
        index = min(calls["n"], len(payloads) - 1)
        calls["n"] += 1
        return payloads[index]

    return complete


# ---------------------------------------------------------------------------
# split_into_windows
# ---------------------------------------------------------------------------


def test_split_into_windows() -> None:
    windows = split_into_windows(_transcript(), window_seconds=300)
    # 720 seconds / 300 = 3 windows (0-300, 300-600, 600-900)
    assert len(windows) == 3
    assert windows[0].start == 0
    assert windows[0].end == 300
    assert windows[1].start == 300
    assert windows[2].start == 600
    # Every segment lands in exactly one window.
    total_segments = sum(len(window.segments) for window in windows)
    assert total_segments == len(_transcript())
    # Window text is populated for the AI prompt.
    assert windows[0].text


def test_split_into_windows_empty() -> None:
    assert split_into_windows([], window_seconds=300) == []
    assert split_into_windows(_transcript(), window_seconds=0) == []


def test_split_into_windows_skips_empty_gaps() -> None:
    transcript = [
        {"start": 0.0, "end": 5.0, "text": "a"},
        {"start": 900.0, "end": 905.0, "text": "b"},
    ]
    windows = split_into_windows(transcript, window_seconds=300)
    # Only windows 0 and 3 have segments; empty windows are skipped.
    assert [window.index for window in windows] == [0, 3]


# ---------------------------------------------------------------------------
# snap_to_sentence_boundary
# ---------------------------------------------------------------------------


def test_snap_to_sentence_boundary() -> None:
    transcript = [
        {"start": 10.0, "end": 18.0, "text": "a"},
        {"start": 18.0, "end": 26.0, "text": "b"},
        {"start": 26.0, "end": 34.0, "text": "c"},
    ]
    # Start snaps to the nearest segment start (12 -> 10); end snaps to the
    # nearest segment end (31 -> 34, closer than 26).
    start, end = snap_to_sentence_boundary(12.0, 31.0, transcript)
    assert start == pytest.approx(10.0)
    assert end == pytest.approx(34.0)


def test_snap_to_sentence_boundary_without_transcript() -> None:
    assert snap_to_sentence_boundary(5.0, 25.0, []) == (5.0, 25.0)


# ---------------------------------------------------------------------------
# validate_moment
# ---------------------------------------------------------------------------


def test_validate_moment_duration() -> None:
    window = Window(index=0, start=0.0, end=300.0, segments=_transcript())
    transcript = _transcript()
    # Valid: 20 s, on segment boundaries (10 -> 30).
    good = Moment(start=10.0, end=30.0, score=0.9, reason="x", strategy="window")
    assert validate_moment(good, window, transcript) is True
    # Too short: 10 s.
    short = Moment(start=10.0, end=20.0, score=0.9, reason="x", strategy="window")
    assert validate_moment(short, window, transcript) is False
    # Too long: 40 s.
    long = Moment(start=10.0, end=50.0, score=0.9, reason="x", strategy="window")
    assert validate_moment(long, window, transcript) is False


def test_validate_moment_outside_window() -> None:
    window = Window(index=0, start=0.0, end=300.0, segments=_transcript())
    transcript = _transcript()
    outside = Moment(start=290.0, end=320.0, score=0.9, reason="x", strategy="window")
    assert validate_moment(outside, window, transcript) is False


def test_validate_moment_not_on_boundary() -> None:
    window = Window(index=0, start=0.0, end=300.0, segments=_transcript())
    transcript = _transcript()
    # 12 -> 32 is 20 s but neither edge is a segment boundary.
    off = Moment(start=12.0, end=32.0, score=0.9, reason="x", strategy="window")
    assert validate_moment(off, window, transcript) is False


# ---------------------------------------------------------------------------
# select_moment_in_window
# ---------------------------------------------------------------------------


async def test_select_moment_in_window_valid() -> None:
    window = Window(index=0, start=0.0, end=300.0, segments=_transcript())
    payload = {
        "scenes": [
            {"start": 10, "end": 30, "reason": "heated argument", "score": 0.87, "categories": ["conflict"]}
        ]
    }
    moment = await select_moment_in_window(window, ai_complete=_ai(payload))
    assert moment is not None
    assert moment.strategy == "window"
    assert moment.start == pytest.approx(10.0)
    assert moment.end == pytest.approx(30.0)
    assert moment.score == pytest.approx(0.87)


async def test_select_moment_in_window_invalid_retry() -> None:
    window = Window(index=0, start=0.0, end=300.0, segments=_transcript())
    # First answer is too short (invalid), second answer is valid.
    invalid = {"scenes": [{"start": 10, "end": 15, "reason": "too short", "score": 0.5, "categories": []}]}
    valid = {"scenes": [{"start": 40, "end": 60, "reason": "good", "score": 0.8, "categories": ["humor"]}]}
    moment = await select_moment_in_window(
        window, ai_complete=_ai_sequence([invalid, valid]), max_retries=3
    )
    assert moment is not None
    assert moment.start == pytest.approx(40.0)
    assert moment.end == pytest.approx(60.0)


async def test_select_moment_in_window_gives_up_after_retries() -> None:
    window = Window(index=0, start=0.0, end=300.0, segments=_transcript())
    invalid = {"scenes": [{"start": 10, "end": 15, "reason": "too short", "score": 0.5, "categories": []}]}
    moment = await select_moment_in_window(
        window, ai_complete=_ai(invalid), max_retries=2
    )
    assert moment is None


async def test_select_moment_in_window_empty_text() -> None:
    window = Window(index=0, start=0.0, end=300.0, segments=[])
    moment = await select_moment_in_window(window, ai_complete=_ai({"scenes": []}))
    assert moment is None


# ---------------------------------------------------------------------------
# select_moments_by_windows
# ---------------------------------------------------------------------------


async def test_select_moments_by_windows() -> None:
    payload = {
        "scenes": [
            {"start": 10, "end": 30, "reason": "moment", "score": 0.8, "categories": ["conflict"]}
        ]
    }
    moments = await select_moments_by_windows(
        _transcript(),
        ai_complete=_ai(payload),
        max_count=4,
        window_seconds=300,
    )
    # 3 windows -> up to 3 moments, capped at max_count.
    assert 1 <= len(moments) <= 4
    assert all(moment.strategy == "window" for moment in moments)
    # Sorted by score descending.
    scores = [moment.score for moment in moments]
    assert scores == sorted(scores, reverse=True)


async def test_select_moments_by_windows_empty_transcript() -> None:
    with pytest.raises(AimlApiError):
        await select_moments_by_windows([], ai_complete=_ai({"scenes": []}))


async def test_select_moments_by_windows_no_valid_moments() -> None:
    invalid = {"scenes": [{"start": 10, "end": 15, "reason": "too short", "score": 0.5, "categories": []}]}
    with pytest.raises(AimlApiError):
        await select_moments_by_windows(
            _transcript(), ai_complete=_ai(invalid), max_retries=1
        )
