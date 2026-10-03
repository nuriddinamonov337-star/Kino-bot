"""AIMLAPI (OpenAI-compatible) client with structured JSON validation."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.ai.key_rotation import ApiKeyRotator
from app.utils.sanitize import sanitize_error

logger = logging.getLogger(__name__)

_RETRYABLE_TRANSPORT_ERRORS = (httpx.TimeoutException, httpx.ConnectError)

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


class ModelUnavailableError(AimlApiError):
    """The requested model is not available; a fallback model may be tried."""


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
        fallback_model: str | None = None,
        retry_backoff_base: float = 1.0,
    ) -> None:
        if not keys:
            raise AimlApiError("AIMLAPI keys are not configured")
        self._rotator = ApiKeyRotator(keys, cooldown_seconds=cooldown_seconds)
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._fallback_model = fallback_model if fallback_model != model else None
        self._timeout = timeout
        self._transport = transport
        self._retry_backoff = retry_backoff_base

    def _models_in_order(self) -> list[str]:
        models = [self._model]
        if self._fallback_model:
            models.append(self._fallback_model)
        return models

    async def complete_json(self, *, system: str, user: str) -> dict[str, Any]:
        """Try the primary model on every key, then the fallback model if configured."""
        last_error = "No AIMLAPI keys available"
        models = self._models_in_order()
        for position, model in enumerate(models):
            try:
                return await self._attempt_model(model, system=system, user=user)
            except AimlApiError as exc:
                last_error = str(exc)
                if position < len(models) - 1:
                    logger.warning(
                        "Model %s failed (%s). Trying fallback model.",
                        model,
                        sanitize_error(str(exc)),
                    )
        raise AimlApiError(f"All AIMLAPI keys exhausted. Last error: {sanitize_error(last_error)}")

    async def _attempt_model(self, model: str, *, system: str, user: str) -> dict[str, Any]:
        last_error = "No AIMLAPI keys available"
        for _ in range(len(self._rotator)):
            index, key = self._rotator.acquire()
            if key is None:
                logger.warning("All %d AIMLAPI key(s) are in cooldown; cannot try model %s", len(self._rotator), model)
                break
            logger.info("AIMLAPI request with model %s (key slot %d/%d)", model, (index or 0) + 1, len(self._rotator))
            try:
                payload = await self._request(key, system, user, model=model)
                return _load_json_object(payload)
            except ModelUnavailableError:
                logger.warning("AIMLAPI model %s unavailable; key slot %s stays active", model, index)
                raise
            except KeyTransientError as exc:
                logger.warning("AIMLAPI key slot %d skipped: %s", index, exc)
                if index is not None:
                    self._rotator.disable(index)
                last_error = str(exc)
            except httpx.HTTPError as exc:
                last_error = sanitize_error(str(exc))
                logger.warning("AIMLAPI transport error on key slot %s: %s", index, sanitize_error(str(exc)))
        raise AimlApiError(f"All AIMLAPI keys exhausted for model {model}. Last error: {sanitize_error(last_error)}")

    async def _request(self, key: str, system: str, user: str, *, model: str) -> str:
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        body = {
            "model": model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport, headers=headers
            ) as client:
                retrying = AsyncRetrying(
                    stop=stop_after_attempt(3),
                    wait=wait_exponential(multiplier=self._retry_backoff, min=0, max=30),
                    retry=retry_if_exception_type(_RETRYABLE_TRANSPORT_ERRORS),
                    before_sleep=before_sleep_log(logger, logging.WARNING),
                    reraise=True,
                )
                async for attempt in retrying:
                    with attempt:
                        response = await client.post(f"{self._base_url}/chat/completions", json=body)
        except httpx.TimeoutException as exc:
            logger.warning("AIMLAPI request timed out after %s seconds; switching key", self._timeout)
            raise KeyTransientError(f"Request timed out after {self._timeout} seconds") from exc
        except httpx.ConnectError as exc:
            logger.warning("AIMLAPI connection failed; switching key: %s", sanitize_error(str(exc)))
            raise KeyTransientError(f"Connection failed: {sanitize_error(str(exc))}") from exc
        if response.status_code in {401, 403}:
            logger.error("AIMLAPI key invalid or unauthorized (provider status %s)", response.status_code)
            raise KeyTransientError(f"API key invalid (provider status {response.status_code})")
        if response.status_code == 429:
            logger.warning("AIMLAPI rate limit exceeded (429); switching key")
            raise KeyTransientError("Rate limit exceeded (provider status 429)")
        lowered = (response.text or "").lower()
        if response.status_code >= 500:
            logger.warning("AIMLAPI provider server error (status %s); switching key", response.status_code)
            raise KeyTransientError(f"Provider server error (status {response.status_code})")
        if response.status_code in {400, 404} and "model" in lowered:
            logger.warning("AIMLAPI model %s not available (status %s); trying fallback model", model, response.status_code)
            raise ModelUnavailableError(f"Model {model} not available (status {response.status_code})")
        if response.status_code >= 400 and any(
            token in lowered for token in ("quota", "rate limit", "rate_limit", "insufficient_quota")
        ):
            logger.warning("AIMLAPI quota exhausted (status %s); switching key", response.status_code)
            raise KeyTransientError(f"Quota exhausted (provider status {response.status_code})")
        if response.status_code >= 400:
            logger.error("AIMLAPI request failed with status %s: %s", response.status_code, sanitize_error(response.text or ""))
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
