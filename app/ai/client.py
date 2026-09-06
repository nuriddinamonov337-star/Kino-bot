"""AIMLAPI (OpenAI-compatible) client with structured JSON validation."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.ai.key_rotation import ApiKeyRotator
from app.utils.sanitize import sanitize_error

logger = logging.getLogger(__name__)

SCENE_CATEGORIES = (
    "strong_dialogue",
    "emotional",
    "surprising",
    "conflict",
    "suspense",
    "humor",
    "visually_interesting",
)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.DOTALL)


class AimlApiError(Exception):
    """Raised when every available key failed or the response is unusable."""


class KeyTransientError(Exception):
    """The current key should be skipped and another key tried."""


@dataclass(frozen=True, slots=True)
class SelectedScene:
    start: float
    end: float
    reason: str
    score: float
    categories: tuple[str, ...]


class AimlApiClient:
    def __init__(
        self,
        *,
        keys: tuple[str, ...],
        base_url: str,
        model: str,
        timeout: float,
        cooldown_seconds: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not keys:
            raise AimlApiError("AIMLAPI keys are not configured")
        self._rotator = ApiKeyRotator(keys, cooldown_seconds=cooldown_seconds)
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._transport = transport

    async def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        last_error = "No AIMLAPI keys available"
        for _ in range(len(self._rotator)):
            index, key = self._rotator.acquire()
            if key is None:
                break
            try:
                payload = await self._request(key, system, user)
                return _load_json_object(payload)
            except KeyTransientError as exc:
                logger.warning("AIMLAPI key index %s skipped after provider error", index)
                self._rotator.disable(index)
                last_error = str(exc)
            except httpx.HTTPError as exc:
                last_error = sanitize_error(str(exc))
                logger.warning("AIMLAPI transport error on key index %s", index)
        raise AimlApiError(sanitize_error(last_error))

    async def _request(self, key: str, system: str, user: str) -> str:
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        body = {
            "model": self._model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport, headers=headers
        ) as client:
            response = await client.post(f"{self._base_url}/chat/completions", json=body)
        if response.status_code in {401, 403, 429}:
            raise KeyTransientError(f"provider status {response.status_code}")
        lowered = (response.text or "").lower()
        if response.status_code >= 400 and any(
            token in lowered for token in ("quota", "rate limit", "rate_limit", "insufficient_quota")
        ):
            raise KeyTransientError(f"provider status {response.status_code}")
        if response.status_code >= 400:
            raise AimlApiError(f"AIMLAPI request failed with status {response.status_code}")
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AimlApiError("AIMLAPI response is missing message content") from exc


def _load_json_object(text: str) -> dict[str, Any]:
    cleaned = _FENCE_RE.sub("", text.strip()).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AimlApiError("AI response is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise AimlApiError("AI JSON root must be an object")
    return parsed


def parse_scene_analysis(
    payload: dict[str, Any],
    *,
    max_scenes: int,
    min_seconds: float,
    max_seconds: float,
    video_duration: float | None = None,
) -> list[SelectedScene]:
    """Validate model JSON and return at most ``max_scenes`` usable clips."""
    raw_scenes = payload.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise AimlApiError("AI JSON must contain a non-empty 'scenes' array")
    selected: list[SelectedScene] = []
    for item in raw_scenes:
        scene = _parse_scene(item, min_seconds=min_seconds, max_seconds=max_seconds, video_duration=video_duration)
        if scene is not None:
            selected.append(scene)
    selected.sort(key=lambda scene: scene.score, reverse=True)
    unique: list[SelectedScene] = []
    for scene in selected:
        if any(abs(scene.start - other.start) < 1.0 for other in unique):
            continue
        unique.append(scene)
        if len(unique) >= max_scenes:
            break
    if not unique:
        raise AimlApiError("AI JSON did not contain any valid scene timestamps")
    return unique


def _parse_scene(
    item: Any,
    *,
    min_seconds: float,
    max_seconds: float,
    video_duration: float | None,
) -> SelectedScene | None:
    if not isinstance(item, dict):
        return None
    try:
        start = float(item.get("start"))
        end = float(item.get("end"))
    except (TypeError, ValueError):
        return None
    if start < 0 or end <= start:
        return None
    if video_duration is not None and start >= video_duration:
        return None
    duration = end - start
    if duration < min_seconds:
        end = start + min_seconds
    if end - start > max_seconds:
        end = start + max_seconds
    if video_duration is not None:
        end = min(end, video_duration)
        if end - start < min_seconds * 0.5:
            return None
    reason = str(item.get("reason") or "").strip()
    if not reason:
        return None
    try:
        score = float(item.get("score", 0))
    except (TypeError, ValueError):
        score = 0.0
    categories_raw = item.get("categories") or []
    if isinstance(categories_raw, str):
        categories_raw = [categories_raw]
    if not isinstance(categories_raw, list):
        return None
    categories = tuple(
        str(category) for category in categories_raw if str(category) in SCENE_CATEGORIES
    )
    return SelectedScene(start=start, end=end, reason=reason[:1000], score=score, categories=categories)


SCENE_SYSTEM_PROMPT = (
    "You analyze movie scene metadata and return STRICT JSON only. "
    "Identify the most interesting/engaging moments using: strong dialogue, "
    "emotional moments, surprising moments, conflict, suspense, humor, and "
    "visually interesting moments. "
    'Schema: {"scenes":[{"start":number,"end":number,"reason":string,'
    '"score":number,"categories":[string]}]}. '
    "Timestamps are seconds from the start of the video. "
    "Each clip must be 15-30 seconds. Return at most 4 scenes. "
    "Never include markdown or commentary."
)
