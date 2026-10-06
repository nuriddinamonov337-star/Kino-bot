"""Mandatory-channel membership checks with Telegram API failure isolation."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telegram import Bot
from telegram.error import TelegramError

from app.database.models import MandatoryChannel
from app.services.admin import increment_channel_campaign

logger = logging.getLogger(__name__)
MEMBER_STATUSES = {"member", "administrator", "creator", "owner"}



@dataclass(frozen=True, slots=True)
class SubscriptionCheck:
    missing: tuple[MandatoryChannel, ...]
    unavailable: tuple[MandatoryChannel, ...]

    @property
    def is_subscribed(self) -> bool:
        return not self.missing and not self.unavailable


async def get_active_mandatory_channels(
    session: AsyncSession, configured_ids: tuple[int, ...] = ()
) -> list[MandatoryChannel]:
    channels = list(
        await session.scalars(
            select(MandatoryChannel)
            .where(MandatoryChannel.is_active.is_(True))
            .order_by(MandatoryChannel.created_at)
        )
    )
    existing_ids = {channel.chat_id for channel in channels}
    for chat_id in configured_ids:
        if chat_id not in existing_ids:
            channels.append(
                MandatoryChannel(
                    chat_id=chat_id,
                    title=f"Kanal {chat_id}",
                    username=None,
                    invite_url=None,
                )
            )
    return channels


async def check_mandatory_subscriptions(bot: Bot, user_id: int, channels: list[MandatoryChannel]) -> SubscriptionCheck:
    missing: list[MandatoryChannel] = []
    unavailable: list[MandatoryChannel] = []
    for channel in channels:
        try:
            member = await bot.get_chat_member(chat_id=channel.chat_id, user_id=user_id)
        except TelegramError:
            logger.warning("Unable to verify membership in mandatory channel %s", channel.chat_id, exc_info=True)
            unavailable.append(channel)
            continue
        status = getattr(member, "status", "")
        status_value = getattr(status, "value", status)
        if str(status_value).lower() not in MEMBER_STATUSES:
            missing.append(channel)
    return SubscriptionCheck(tuple(missing), tuple(unavailable))


async def count_campaign_subscribers(
    session: AsyncSession, channels: list[MandatoryChannel]
) -> list[MandatoryChannel]:
    """Increment the subscriber counter of every active campaign channel.

    Called once a user has been verified as subscribed to all mandatory
    channels. Returns the channels whose campaign just completed so the caller
    can notify the admin.
    """
    completed: list[MandatoryChannel] = []
    for channel in channels:
        if channel.campaign_status != "active" or channel.campaign_target <= 0:
            continue
        if await increment_channel_campaign(session, channel):
            completed.append(channel)
    return completed


