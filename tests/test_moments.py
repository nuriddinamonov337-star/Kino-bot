"""Tests for transcript/metadata/heuristic moment selection (no network)."""

import json

import pytest

from app.ai.client import AimlApiError
from app.video.moments import (
    Moment,
    select_by_heuristic,
    select_by_metadata,
    select_by_transcript,
    select_moments,
)


def _ai(payload: dict):
    async def complete(*, system: str, user: str) -> dict:
        return payload

    return complete


def _scenes_payload() -> dict:
    return {
        "scenes": [
            {"start": 10, "end": 35, "reason": "heated argument", "score": 0.9, "categories": ["conflict"]},
            {"start": 100, "end": 120, "reason": "tearful goodbye", "score": 0.7, "categories": ["emotional"]},
        ]
    }


def test_moment_dataclass_fields() -> None:
    moment = Moment(start=1.0, end=20.0, score=0.8, reason="x", strategy="heuristic")
    assert (moment.start, moment.end, moment.strategy) == (1.0, 20.0, "heuristic")


async def test_select_by_metadata_returns_moments() -> None:
    moments = await select_by_metadata(
        [(0.0, 60.0), (60.0, 150.0)],
        ai_complete=_ai(_scenes_payload()),
        title="Test",
        duration=200.0,
        max_count=4,
    )
    assert len(moments) == 2
    assert all(moment.strategy == "metadata" for moment in moments)
    assert moments[0].reason == "heated argument"


async def test_select_by_metadata_rejects_empty_scenes() -> None:
    with pytest.raises(AimlApiError):
        await select_by_metadata([], ai_complete=_ai(_scenes_payload()))


async def test_select_by_transcript_returns_moments() -> None:
    transcript = [
        {"start": 8.0, "end": 14.0, "text": "You lied to me all along!"},
        {"start": 98.0, "end": 104.0, "text": "Goodbye, my friend."},
    ]
    moments = await select_by_transcript(
        transcript, ai_complete=_ai(_scenes_payload()), duration=200.0, max_count=4
    )
    assert len(moments) == 2
    assert all(moment.strategy == "transcript" for moment in moments)


async def test_select_by_transcript_rejects_empty_transcript() -> None:
    with pytest.raises(AimlApiError):
        await select_by_transcript([], ai_complete=_ai(_scenes_payload()))
    with pytest.raises(AimlApiError):
        await select_by_transcript(
            [{"start": 0, "end": 1, "text": "   "}], ai_complete=_ai(_scenes_payload())
        )


def test_select_by_heuristic_prefers_good_length() -> None:
    scenes = [(0.0, 5.0), (100.0, 125.0), (200.0, 260.0)]
    moments = select_by_heuristic(scenes, 300.0, max_count=4)
    assert moments[0].start == pytest.approx(100.0)
    assert moments[0].strategy == "heuristic"
    assert all(moment.end - moment.start <= 30 for moment in moments)


def test_select_by_heuristic_skips_invalid_and_limits_count() -> None:
    scenes = [(i * 10.0, i * 10.0 + 20.0) for i in range(10)]
    scenes.append((5.0, 4.0))  # invalid
    moments = select_by_heuristic(scenes, 300.0, max_count=4)
    assert len(moments) == 4
    assert all(moment.strategy == "heuristic" for moment in moments)


async def test_auto_falls_back_to_heuristic_when_ai_fails() -> None:
    async def broken_ai(*, system: str, user: str) -> dict:
        raise AimlApiError("provider down")

    moments = await select_moments(
        [(0.0, 60.0), (60.0, 150.0)],
        duration=200.0,
        strategy="auto",
        ai_complete=broken_ai,
        max_count=4,
    )
    assert moments
    assert all(moment.strategy == "heuristic" for moment in moments)


async def test_auto_without_ai_uses_heuristic() -> None:
    moments = await select_moments([(0.0, 25.0)], duration=100.0, strategy="auto")
    assert len(moments) == 1
    assert moments[0].strategy == "heuristic"


async def test_explicit_heuristic_needs_no_ai() -> None:
    moments = await select_moments([(0.0, 25.0)], duration=100.0, strategy="heuristic")
    assert moments[0].strategy == "heuristic"


async def test_unknown_strategy_becomes_auto() -> None:
    moments = await select_moments([(0.0, 25.0)], duration=100.0, strategy="weird")
    assert moments[0].strategy == "heuristic"


async def test_explicit_metadata_without_ai_raises() -> None:
    with pytest.raises(AimlApiError):
        await select_moments([(0.0, 25.0)], duration=100.0, strategy="metadata")