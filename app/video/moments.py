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


@dataclass(frozen=True, slots=True)
class Window:
    """A fixed-length slice of the movie transcript (default 5 minutes)."""

    index: int
    start: float
    end: float
    segments: list[dict[str, object]]

    @property
    def text(self) -> str:
        """Human-readable transcript text for this window (for the AI prompt)."""
        return _transcript_prompt(self.segments)


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


# ---------------------------------------------------------------------------
# Window-based selection (Clip Generator / Adversitas style)
#
# Long movies (2+ hours) overwhelm the LLM when the whole transcript is sent at
# once, so quality drops. Instead we split the transcript into fixed-length
# windows (default 5 minutes), ask the AI for the single best moment inside each
# window, validate the answer, retry on invalid output, and finally keep the
# highest-scoring moments. This keeps every prompt small and grounded.
# ---------------------------------------------------------------------------


def split_into_windows(
    transcript: list[dict[str, object]],
    window_seconds: float = 300.0,
) -> list[Window]:
    """Split a transcript into fixed-length windows (default 5 minutes).

    Segments are assigned to the window that contains their start time. Empty
    windows (no usable segments) are skipped so the AI is never asked about
    silence. Returns an empty list for an empty transcript.
    """
    if not transcript or window_seconds <= 0:
        return []
    buckets: dict[int, list[dict[str, object]]] = {}
    for segment in transcript:
        try:
            start = float(segment.get("start", 0))  # type: ignore[union-attr]
        except (TypeError, ValueError):
            continue
        if start < 0:
            continue
        index = int(start // window_seconds)
        buckets.setdefault(index, []).append(segment)
    windows: list[Window] = []
    for index in sorted(buckets):
        segments = buckets[index]
        start = index * window_seconds
        windows.append(
            Window(index=index, start=start, end=start + window_seconds, segments=segments)
        )
    return windows


def snap_to_sentence_boundary(
    start: float,
    end: float,
    transcript: list[dict[str, object]],
) -> tuple[float, float]:
    """Nudge ``start``/``end`` to the nearest transcript segment boundaries.

    Cutting mid-sentence looks unnatural, so we snap the clip start to the
    beginning of the segment that contains it and the clip end to the end of
    the segment that contains it. When the transcript is empty or has no usable
    timestamps the original values are returned unchanged.
    """
    spans: list[tuple[float, float]] = []
    for segment in transcript:
        try:
            seg_start = float(segment.get("start", 0))  # type: ignore[union-attr]
            seg_end = float(segment.get("end", 0))  # type: ignore[union-attr]
        except (TypeError, ValueError):
            continue
        if seg_end > seg_start:
            spans.append((seg_start, seg_end))
    if not spans:
        return start, end
    spans.sort()
    # Snap the start to the nearest segment *start* and the end to the nearest
    # segment *end*. Using the nearest boundary (rather than the containing
    # segment) avoids snapping a value that sits exactly on a boundary back to
    # the previous segment.
    starts = [seg_start for seg_start, _ in spans]
    ends = [seg_end for _, seg_end in spans]
    snapped_start = min(starts, key=lambda value: abs(value - start))
    snapped_end = min(ends, key=lambda value: abs(value - end))
    if snapped_end <= snapped_start:
        return start, end
    return snapped_start, snapped_end


def validate_moment(
    moment: Moment,
    window: Window,
    transcript: list[dict[str, object]],
    *,
    min_duration: float = 15.0,
    max_duration: float = 30.0,
) -> bool:
    """Return ``True`` when ``moment`` is a usable clip inside ``window``.

    Checks: the interval lies inside the window, the duration is within
    ``[min_duration, max_duration]``, and both edges sit on transcript segment
    boundaries (so the cut is not mid-sentence).
    """
    if moment.end <= moment.start:
        return False
    if moment.start < window.start or moment.end > window.end:
        return False
    duration = moment.end - moment.start
    if duration < min_duration or duration > max_duration:
        return False
    spans: list[tuple[float, float]] = []
    for segment in transcript:
        try:
            seg_start = float(segment.get("start", 0))  # type: ignore[union-attr]
            seg_end = float(segment.get("end", 0))  # type: ignore[union-attr]
        except (TypeError, ValueError):
            continue
        if seg_end > seg_start:
            spans.append((seg_start, seg_end))
    if not spans:
        return True
    tolerance = 0.5
    start_ok = any(abs(moment.start - seg_start) <= tolerance for seg_start, _ in spans)
    end_ok = any(abs(moment.end - seg_end) <= tolerance for _, seg_end in spans)
    return start_ok and end_ok


async def select_moment_in_window(
    window: Window,
    *,
    ai_complete: AiComplete,
    max_duration: float = 30.0,
    min_duration: float = 15.0,
    max_retries: int = 3,
) -> Moment | None:
    """Ask the AI for the single best moment inside one window.

    The prompt only contains this window's transcript, so it stays small even
    for multi-hour movies. Every AI answer is validated with
    :func:`validate_moment`; invalid answers trigger a retry (up to
    ``max_retries``). Returns ``None`` when no valid moment is found.
    """
    prompt = window.text
    if not prompt:
        return None
    user = (
        f"Window {window.index + 1}: {window.start:.0f}s - {window.end:.0f}s.\n"
        f"Transcript:\n{prompt}\n"
        f"Return JSON with the single most engaging {min_duration:.0f}-{max_duration:.0f} "
        "second moment inside this window."
    )
    for attempt in range(1, max_retries + 1):
        try:
            analysis = await ai_complete(system=TRANSCRIPT_SYSTEM_PROMPT, user=user)
            raw = _first_raw_scene(analysis)
        except AimlApiError as exc:
            logger.warning(
                "Window %d/%d: AI javobi yaroqsiz, qayta urinish (%d/%d): %s",
                window.index + 1,
                window.index + 1,
                attempt,
                max_retries,
                sanitize_error(str(exc)),
            )
            continue
        if raw is None:
            logger.warning(
                "Window %d/%d: AI noto‘g‘ri moment qaytardi, qayta urinish (%d/%d)",
                window.index + 1,
                window.index + 1,
                attempt,
                max_retries,
            )
            continue
        raw_start, raw_end, score, reason = raw
        # Jumla chegaralariga suramiz, keyin davomiylikni tekshiramiz.
        snapped_start, snapped_end = snap_to_sentence_boundary(
            raw_start, raw_end, window.segments
        )
        snapped = Moment(
            start=snapped_start,
            end=snapped_end,
            score=score,
            reason=reason,
            strategy="window",
        )
        if validate_moment(
            snapped,
            window,
            window.segments,
            min_duration=min_duration,
            max_duration=max_duration,
        ):
            return snapped
        logger.warning(
            "Window %d/%d: AI noto‘g‘ri moment qaytardi, qayta urinish (%d/%d)",
            window.index + 1,
            window.index + 1,
            attempt,
            max_retries,
        )
    return None


def _first_raw_scene(payload: dict[str, Any]) -> tuple[float, float, float, str] | None:
    """Extract the first usable ``(start, end, score, reason)`` from AI JSON.

    Unlike :func:`parse_scene_analysis` this does not clamp the duration, so the
    caller can snap the raw timestamps to sentence boundaries first and only
    then validate the resulting length.
    """
    raw_scenes = payload.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise AimlApiError("AI JSON must contain a non-empty 'scenes' array")
    for item in raw_scenes:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("start"))
            end = float(item.get("end"))
        except (TypeError, ValueError):
            continue
        if start < 0 or end <= start:
            continue
        reason = str(item.get("reason") or "").strip()
        if not reason:
            continue
        try:
            score = float(item.get("score", 0))
        except (TypeError, ValueError):
            score = 0.0
        return start, end, score, reason[:1000]
    return None


async def select_moments_by_windows(
    transcript: list[dict[str, object]],
    *,
    ai_complete: AiComplete,
    max_count: int = 4,
    window_seconds: float = 300.0,
    min_duration: float = 15.0,
    max_duration: float = 30.0,
    max_retries: int = 3,
) -> list[Moment]:
    """Pick the best moments across the whole movie using 5-minute windows.

    Each window contributes at most one moment; the collected moments are then
    sorted by score and the top ``max_count`` are returned. Raises
    :class:`AimlApiError` when no window yields a valid moment so the caller can
    fall back to the heuristic strategy.
    """
    windows = split_into_windows(transcript, window_seconds=window_seconds)
    if not windows:
        raise AimlApiError("Transcript is empty; cannot select moments by windows")
    collected: list[Moment] = []
    total = len(windows)
    for window in windows:
        moment = await select_moment_in_window(
            window,
            ai_complete=ai_complete,
            min_duration=min_duration,
            max_duration=max_duration,
            max_retries=max_retries,
        )
        if moment is None:
            logger.info("Window %d/%d: moment topilmadi", window.index + 1, total)
            continue
        logger.info(
            "Window %d/%d: selected moment %s - %s (score: %.2f)",
            window.index + 1,
            total,
            _format_timestamp(moment.start),
            _format_timestamp(moment.end),
            moment.score,
        )
        collected.append(moment)
    if not collected:
        raise AimlApiError("No valid moments were found in any window")
    collected.sort(key=lambda item: item.score, reverse=True)
    return collected[:max_count]


def _format_timestamp(seconds: float) -> str:
    """Format seconds as ``HH:MM:SS`` for readable logs."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"
