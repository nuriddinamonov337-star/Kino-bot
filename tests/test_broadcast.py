"""Unit tests for broadcast target mapping and FloodWait-resilient delivery."""

import pytest
from telegram.error import Forbidden, RetryAfter

from app.config import Settings
from app.services.broadcast import (
    BroadcastTarget,
    broadcast_to_chats,
    resolve_broadcast_targets,
    send_with_retry,
)


def _settings(**overrides) -> Settings:
    base = {"bot_token": "test-token", "database_url": "sqlite+aiosqlite://"}
    base.update(overrides)
    return Settings(**base, _env_file=None)


def test_channel_targets_map_to_configured_ids() -> None:
    settings = _settings(main_channel_id=-1003231515720, reels_channel_id=-100999)
    main = resolve_broadcast_targets(settings, BroadcastTarget.MAIN_CHANNEL)
    assert main.include_users is False
    assert main.channel_ids == [-1003231515720]
    second = resolve_broadcast_targets(settings, BroadcastTarget.REELS_CHANNEL)
    assert second.channel_ids == [-100999]
    everyone = resolve_broadcast_targets(settings, BroadcastTarget.ALL)
    assert everyone.include_users is True
    assert everyone.channel_ids == [-1003231515720, -100999]
    users = resolve_broadcast_targets(settings, BroadcastTarget.USERS)
    assert users.include_users is True
    assert users.channel_ids == []


def test_unconfigured_channels_are_skipped_with_warning(caplog) -> None:
    settings = _settings()
    resolved = resolve_broadcast_targets(settings, BroadcastTarget.ALL)
    assert resolved.include_users is True
    assert resolved.channel_ids == []
    assert "unconfigured channel" in caplog.text


async def test_send_with_retry_honours_retry_after() -> None:
    calls = {"count": 0}

    async def sender():
        calls["count"] += 1
        if calls["count"] < 3:
            raise RetryAfter(0)
        return "ok"

    assert await send_with_retry(sender, max_attempts=4, base_delay=0) == "ok"
    assert calls["count"] == 3


async def test_send_with_retry_gives_up_after_max_attempts() -> None:
    async def sender():
        raise RetryAfter(0)

    with pytest.raises(RetryAfter):
        await send_with_retry(sender, max_attempts=2, base_delay=0)


async def test_broadcast_collects_failures_without_aborting() -> None:
    def factory(chat_id: int):
        async def send():
            if chat_id == 2:
                raise Forbidden("bot was blocked")
            return chat_id

        return send

    report = await broadcast_to_chats(factory, [1, 2, 3], delay_between=0)
    assert report.sent == 2
    assert report.failed == 1
    assert report.failed_chat_ids == [2]