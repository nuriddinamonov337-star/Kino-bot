import json

import httpx
import pytest

from app.ai.client import AimlApiClient, AimlApiError, parse_scene_analysis
from app.ai.key_rotation import ApiKeyRotator


def test_parse_scene_analysis_accepts_valid_json() -> None:
    payload = {
        "scenes": [
            {
                "start": 10,
                "end": 40,
                "reason": "conflict in the hallway",
                "score": 0.9,
                "categories": ["conflict", "suspense"],
            },
            {
                "start": 90,
                "end": 110,
                "reason": "emotional goodbye",
                "score": 0.7,
                "categories": ["emotional"],
            },
        ]
    }
    scenes = parse_scene_analysis(payload, max_scenes=4, min_seconds=15, max_seconds=30, video_duration=200)
    assert len(scenes) == 2
    assert scenes[0].end - scenes[0].start == 30
    assert scenes[0].reason == "conflict in the hallway"


def test_parse_scene_analysis_rejects_malformed_payload() -> None:
    with pytest.raises(AimlApiError):
        parse_scene_analysis({"scenes": "nope"}, max_scenes=4, min_seconds=15, max_seconds=30)
    with pytest.raises(AimlApiError):
        parse_scene_analysis({"scenes": [{"start": 5, "end": 4, "reason": "x"}]}, max_scenes=4, min_seconds=15, max_seconds=30)


def test_key_rotator_skips_disabled_keys() -> None:
    rotator = ApiKeyRotator(("alpha", "beta", "gamma"), cooldown_seconds=60)
    first_index, first_key = rotator.acquire()
    assert first_key == "alpha"
    rotator.disable(first_index)
    _, second = rotator.acquire()
    _, third = rotator.acquire()
    assert {second, third} == {"beta", "gamma"}
    rotator.disable(1)
    rotator.disable(2)
    index, key = rotator.acquire()
    assert index is None and key is None


@pytest.mark.asyncio
async def test_aiml_client_rotates_after_rate_limit() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers["Authorization"]
        calls.append(auth.split()[-1])
        if auth.endswith("bad"):
            return httpx.Response(429, json={"error": {"message": "rate limit"}})
        body = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "scenes": [
                                    {
                                        "start": 1,
                                        "end": 20,
                                        "reason": "humor",
                                        "score": 1,
                                        "categories": ["humor"],
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        }
        return httpx.Response(200, json=body)

    client = AimlApiClient(
        keys=("bad", "good"),
        base_url="https://example.test/v1",
        model="glm-5.2",
        timeout=5,
        transport=httpx.MockTransport(handler),
    )
    payload = await client.complete_json(system="sys", user="user")
    assert payload["scenes"][0]["reason"] == "humor"
    assert calls[0] == "bad"
    assert "good" in calls
