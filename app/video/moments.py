"""Moment selection strategies for Reels.

Three strategies pick at most ``max_count`` clips from a movie:

- ``metadata`` — the current AI-first path: PySceneDetect scene boundaries
  are sent to the LLM, which returns the most engaging moments.
- ``transcript`` — transcript-first path (AI-Youtube-Shorts-Generator style):
  a Whisper transcript (text + timestamps only, no audio sent anywhere) is
  sent to the LLM, which grounds moments in dialogue/subject matter.
- ``heuristic`` — fully local fallback used when AI is unavailable: prefers
  15-30 s scenes with high motion, spread across the movie.

:func:`select_moments` is the single entry point used by the pipeline.
``strategy="auto"`` tries AI first (transcript when one is supplied,
otherwise metadata) and falls back to the heuristic on any AI failure, so a
dead AI provider degrades quality but never the job.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.ai.client import SCENE_SYSTEM_PROMPT, AimlApiError, parse_scene_analysis
from app.utils.sanitize import sanitize_error
from app.video.processing import scene_prompt_payload

logger = logging.getLogger(__name__)

AiComplete = Callable[..., Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class Moment:
    start: float
    end: float
    score: float
    reason: str
    strategy: str


TRANSCRIPT_SYSTEM_PROMPT = (
    "You analyze a video transcript (timestamps + dialogue) and return STRICT JSON only. "
    "Identify the most interesting/engaging moments using: strong dialogue, "
    "emotional moments, surprising moments, conflict, suspense, humor, and "
    "cliffhangers that make viewers want to watch more. "
    'Schema: {"scenes":[{"start":number,"end":number,"reason":string,'
    '"score":number,"categories":[string]}]}. '
    "Timestamps MUST fall inside the transcript time ranges. "
    "Each clip must be 15-30 seconds. Return at most 4 scenes. "
    "Never include markdown or commentary."
)


def _to_moments(selected, *, strategy: str) -> list[Moment]:
    return [
        Moment(start=item.start, end=item.end, score=item.score, reason=item.reason, strategy=strategy)
        for item in selected
    ]


async def select_by_metadata(
    scenes: list[tuple[float, float]],
    *,
    ai_complete: AiComplete,
    title: str = "",
    duration: float | None = None,
    max_count: int = 4,
    min_seconds: float = 15,
    max_seconds: float = 30,
) -> list[Moment]:
    """AI-first selection from PySceneDetect boundaries."""
    if not scenes:
        raise AimlApiError("No scenes were detected for metadata selection")
    user = (
        f"Movie title: {title}\nDuration seconds: {duration:.2f}\n"
        f"{scene_prompt_payload(scenes)}\n"
        "Return JSON for the most engaging 15-30 second moments."
    ) if duration is not None else (
        f"Movie title: {title}\n{scene_prompt_payload(scenes)}\n"
        "Return JSON for the most engaging 15-30 second moments."
    )
    analysis = await ai_complete(system=SCENE_SYSTEM_PROMPT, user=user)
    selected = parse_scene_analysis(
        analysis,
        max_scenes=max_count,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
        video_duration=duration,
    )
    return _to_moments(selected, strategy="metadata")


def _transcript_prompt(transcript: list[dict[str, object]], max_chars: int = 12000) -> str:
    lines: list[str] = []
    budget = max_chars
    for segment in transcript[:200]:
        try:
            start = float(segment.get("start", 0))  # type: ignore[union-attr]
            end = float(segment.get("end", 0))  # type: ignore[union-attr]
        except (TypeError, ValueError):
            continue
        text = str(segment.get("text") or "").strip().replace("\n", " ")
        if not text:
            continue
        line = f"[{start:.1f}-{end:.1f}] {text}"
        if len(line) > budget:
            break
        lines.append(line)
        budget -= len(line)
    return "\n".join(lines)


async def select_by_transcript(
    transcript: list[dict[str, object]],
    *,
    ai_complete: AiComplete,
    duration: float | None = None,
    max_count: int = 4,
    min_seconds: float = 15,
    max_seconds: float = 30,
) -> list[Moment]:
    """Transcript-first selection: LLM grounds moments in dialogue."""
    prompt = _transcript_prompt(transcript)
    if not prompt:
        raise AimlApiError("Transcript is empty; cannot select moments")
    user = (
        f"Video duration seconds: {duration:.2f}\nTranscript:\n{prompt}\n"
        f"Return JSON for the most engaging 15-30 second moments (at most {max_count})."
    ) if duration is not None else (
        f"Transcript:\n{prompt}\n"
        f"Return JSON for the most engaging 15-30 second moments (at most {max_count})."
    )
    analysis = await ai_complete(system=TRANSCRIPT_SYSTEM_PROMPT, user=user)
    selected = parse_scene_analysis(
        analysis,
        max_scenes=max_count,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
        video_duration=duration,
    )
    return _to_moments(selected, strategy="transcript")


def select_by_heuristic(
    scenes: list[tuple[float, float]],
    duration: float | None = None,
    *,
    max_count: int = 4,
    min_seconds: float = 15,
    max_seconds: float = 30,
    scores: list[float] | None = None,
    min_gap_seconds: float = 5.0,
) -> list[Moment]:
    """Local fallback: prefer 15-30 s, high-motion scenes spread over the movie."""
    candidates: list[Moment] = []
    for index, (start, end) in enumerate(scenes):
        if end <= start or start < 0:
            continue
        if duration is not None and start >= duration:
            continue
        length = end - start
        if length < min_seconds:
            fit = max(0.0, length / min_seconds)
            end = start + min_seconds
        elif length > max_seconds:
            fit = max(0.0, 1.0 - (length - max_seconds) / max_seconds)
            end = start + max_seconds
        else:
            fit = 1.0
        if duration is not None:
            end = min(end, duration)
            if end - start < min_seconds * 0.5:
                continue
        motion = 0.5
        if scores is not None and index < len(scores):
            try:
                motion = min(1.0, max(0.0, float(scores[index])))
            except (TypeError, ValueError):
                motion = 0.5
        score = 0.6 * fit + 0.4 * motion
        candidates.append(
            Moment(
                start=start,
                end=end,
                score=score,
                reason=f"Heuristic pick: {length:.0f}s scene at {start:.0f}s",
                strategy="heuristic",
            )
        )
    candidates.sort(key=lambda item: item.score, reverse=True)
    picked: list[Moment] = []
    for candidate in candidates:
        if any(abs(candidate.start - other.start) < min_gap_seconds for other in picked):
            continue
        picked.append(candidate)
        if len(picked) >= max_count:
            break
    return picked


async def select_moments(
    scenes: list[tuple[float, float]],
    *,
    duration: float | None = None,
    max_count: int = 4,
    strategy: str = "auto",
    ai_complete: AiComplete | None = None,
    transcript: list[dict[str, object]] | None = None,
    title: str = "",
    min_seconds: float = 15,
    max_seconds: float = 30,
) -> list[Moment]:
    """Pick moments with ``strategy`` ("auto" falls back to heuristic on AI failure)."""
    mode = (strategy or "auto").lower()
    if mode not in {"auto", "metadata", "transcript", "heuristic"}:
        logger.warning("Unknown moment strategy %r; using auto", strategy)
        mode = "auto"
    if mode == "heuristic":
        return select_by_heuristic(
            scenes, duration, max_count=max_count, min_seconds=min_seconds, max_seconds=max_seconds
        )
    if mode == "metadata":
        if ai_complete is None:
            raise AimlApiError("AI is required for the metadata strategy")
        return await select_by_metadata(
            scenes, ai_complete=ai_complete, title=title, duration=duration,
            max_count=max_count, min_seconds=min_seconds, max_seconds=max_seconds,
        )
    if mode == "transcript":
        if ai_complete is None or not transcript:
            raise AimlApiError("Transcript and AI are required for the transcript strategy")
        return await select_by_transcript(
            transcript, ai_complete=ai_complete, duration=duration,
            max_count=max_count, min_seconds=min_seconds, max_seconds=max_seconds,
        )
    # auto: transcript when supplied, else metadata; heuristic on any AI failure.
    if ai_complete is None:
        logger.warning("No AI client; using heuristic moment selection")
        return select_by_heuristic(
            scenes, duration, max_count=max_count, min_seconds=min_seconds, max_seconds=max_seconds
        )
    try:
        if transcript:
            return await select_by_transcript(
                transcript, ai_complete=ai_complete, duration=duration,
                max_count=max_count, min_seconds=min_seconds, max_seconds=max_seconds,
            )
        return await select_by_metadata(
            scenes, ai_complete=ai_complete, title=title, duration=duration,
            max_count=max_count, min_seconds=min_seconds, max_seconds=max_seconds,
        )
    except Exception as exc:
        logger.warning("AI moment selection failed (%s); using heuristic", sanitize_error(str(exc)))
        return select_by_heuristic(
            scenes, duration, max_count=max_count, min_seconds=min_seconds, max_seconds=max_seconds
        )