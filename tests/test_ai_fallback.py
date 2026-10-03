"""Tests for AIMLAPI per-status logging, tenacity retry, and fallback model."""

import httpx
import pytest

from app.ai.client import AimlApiClient, AimlApiError
from app.ai.key_rotation import ApiKeyRotator
from app.config import Settings


def _ok_payload() -> dict:
    import json as jsonlib

    scenes = {
        "scenes": [
            {"start": 5, "end": 25, "reason": "funny moment", "score": 0.9, "categories": ["humor"]}
        ]
    }
    return {"choices": [{"message": {"content": jsonlib.dumps(scenes)}}]}


def _client(handler, **overrides) -> AimlApiClient:
    base = {
        "keys": ("k1", "k2"),
        "base_url": "https://example.test/v1",
        "model": "primary-model",
        "timeout": 5,
        "transport": httpx.MockTransport(handler),
        "retry_backoff_base": 0,
    }
    base.update(overrides)
    return AimlApiClient(**base)


async def test_all_keys_failing_gives_exhausted_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "unauthorized"}})

    client = _client(handler, keys=("only",))
    with pytest.raises(AimlApiError, match="All AIMLAPI keys exhausted"):
        await client.complete_json(system="s", user="u")


async def test_401_is_logged_as_invalid_key(caplog) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "unauthorized"}})

    client = _client(handler, keys=("only",))
    with pytest.raises(AimlApiError), caplog.at_level("WARNING"):
        await client.complete_json(system="s", user="u")
    assert "invalid" in caplog.text.lower()


async def test_500_fails_over_to_next_key(caplog) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.headers["Authorization"].split()[-1]
        seen.append(key)
        if key == "k1":
            return httpx.Response(500, text="internal error")
        return httpx.Response(200, json=_ok_payload())

    client = _client(handler)
    payload = await client.complete_json(system="s", user="u")
    assert payload["scenes"][0]["reason"] == "funny moment"
    assert seen == ["k1", "k2"]
    assert "server error" in caplog.text.lower()


async def test_timeout_retries_then_switches_key() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.ConnectError("connection refused")

    client = _client(handler, keys=("only",))
    with pytest.raises(AimlApiError, match="All AIMLAPI keys exhausted"):
        await client.complete_json(system="s", user="u")
    assert calls["count"] == 3  # tenacity: 3 attempts on the same key


async def test_fallback_model_used_when_primary_model_missing() -> None:
    models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as jsonlib

        body = jsonlib.loads(request.content.decode())
        models.append(body["model"])
        if body["model"] == "primary-model":
            return httpx.Response(404, json={"error": {"message": "model primary-model not found"}})
        return httpx.Response(200, json=_ok_payload())

    client = _client(handler, keys=("only",), fallback_model="fallback-model")
    payload = await client.complete_json(system="s", user="u")
    assert payload["scenes"][0]["reason"] == "funny moment"
    assert models == ["primary-model", "fallback-model"]


def test_fourth_numbered_key_is_merged() -> None:
    settings = Settings(
        bot_token="test-token",
        database_url="sqlite+aiosqlite://",
        aimlapi_key_1="one",
        aimlapi_key_2="two",
        aimlapi_key_3="three",
        aimlapi_key_4="four",
        _env_file=None,
    )
    assert settings.aimlapi_key_values == ("one", "two", "three", "four")


def test_rotator_reuses_key_after_cooldown_expires() -> None:
    rotator = ApiKeyRotator(("a", "b"), cooldown_seconds=60)
    index, _ = rotator.acquire()
    rotator.disable(index, seconds=0)
    _, key = rotator.acquire()
    assert key in ("a", "b")