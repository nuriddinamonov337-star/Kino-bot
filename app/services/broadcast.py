"""Broadcast targets and resilient delivery.

Target mapping (admin panel labels):

- "1-kanalga" (:attr:`BroadcastTarget.MAIN_CHANNEL`) → ``settings.main_channel_id``
- "2-kanalga" (:attr:`BroadcastTarget.REELS_CHANNEL`) → ``settings.reels_channel_id``
- "Foydalanuvchilarga" (:attr:`BroadcastTarget.USERS`) → active DB users
- "Hammasiga" (:attr:`BroadcastTarget.ALL`) → users + both channels

Delivery is rate-limited (small pause between sends) and handles Telegram
``RetryAfter``/FloodWait by sleeping the requested time and retrying. Failed
destinations are collected and logged instead of aborting the whole broadcast.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError

from app.config import Settings
from app.database.models import User
from app.utils.sanitize import sanitize_error

logger = logging.getLogger(__name__)


class BroadcastTarget(StrEnum):
    USERS = "users"
    MAIN_CHANNEL = "main_channel"
    REELS_CHANNEL = "reels_channel"
    ALL = "all"


@dataclass(slots=True)
class ResolvedTargets:
    include_users: bool = False
    channel_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class BroadcastReport:
    sent: int = 0
    failed: int = 0
    failed_chat_ids: list[int] = field(default_factory=list)


def resolve_broadcast_targets(settings: Settings, target: BroadcastTarget) -> ResolvedTargets:
    """Map an admin-panel broadcast choice to concrete destinations."""
    resolved = ResolvedTargets()
    if target in (BroadcastTarget.USERS, BroadcastTarget.ALL):
        resolved.include_users = True
    channels: list[int | None] = []
    if target in (BroadcastTarget.MAIN_CHANNEL, BroadcastTarget.ALL):
        channels.append(settings.main_channel_id)
    if target in (BroadcastTarget.REELS_CHANNEL, BroadcastTarget.ALL):
        channels.append(settings.reels_channel_id)
    resolved.channel_ids = [chat_id for chat_id in channels if chat_id is not None]
    missing = len(channels) - len(resolved.channel_ids)
    if missing:
        logger.warning("Broadcast target %s skips %d unconfigured channel(s)", target.value, missing)
    return resolved


async def get_active_user_chat_ids(session: AsyncSession) -> list[int]:
    """Return telegram_ids of active users for user broadcasts."""
    rows = await session.scalars(select(User.telegram_id).where(User.is_active.is_(True)))
    return list(rows)


async def send_with_retry(
    sender: Callable[[], Awaitable[object]],
    *,
    max_attempts: int = 4,
    base_delay: float = 1.0,
) -> object:
    """Run one Telegram send, honouring RetryAfter/FloodWait with backoff."""
    attempt = 0
    while True:
        attempt += 1
        try:
            return await sender()
        except RetryAfter as exc:
            wait = float(getattr(exc, "retry_after", base_delay)) + 1.0
            if attempt >= max_attempts:
                raise
            logger.warning("FloodWait: sleeping %.1fs (attempt %d/%d)", wait, attempt, max_attempts)
            await asyncio.sleep(wait)
        except (BadRequest, Forbidden):
            raise
        except TelegramError as exc:
            if attempt >= max_attempts:
                raise
            wait = base_delay * (2 ** (attempt - 1))
            logger.warning("Telegram send failed (attempt %d/%d); retrying in %.1fs: %s", attempt, max_attempts, wait, sanitize_error(str(exc)))
            await asyncio.sleep(wait)


async def broadcast_to_chats(
    sender_factory: Callable[[int], Callable[[], Awaitable[object]]],
    chat_ids: Iterable[int],
    *,
    delay_between: float = 0.05,
    max_attempts: int = 4,
) -> BroadcastReport:
    """Deliver one message to many chats; failures are logged, never fatal."""
    report = BroadcastReport()
    for chat_id in chat_ids:
        try:
            await send_with_retry(sender_factory(chat_id), max_attempts=max_attempts)
            report.sent += 1
        except (BadRequest, Forbidden) as exc:
            logger.info("Broadcast skipped unreachable chat %s: %s", chat_id, sanitize_error(str(exc)))
            report.failed += 1
            report.failed_chat_ids.append(chat_id)
        except (RetryAfter, TelegramError, Exception) as exc:
            logger.warning("Broadcast to %s failed: %s", chat_id, sanitize_error(str(exc)))
            report.failed += 1
            report.failed_chat_ids.append(chat_id)
        if delay_between > 0:
            await asyncio.sleep(delay_between)
    logger.info("Broadcast finished: %d sent, %d failed", report.sent, report.failed)
    return report