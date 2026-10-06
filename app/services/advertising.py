"""Paid advertising campaign persistence and scheduling helpers (§12).

The advertising system is a self-contained paid-campaign flow:

* A user picks a tariff (week/month), sends the ad content and a payment
  receipt.
* An admin approves or rejects the campaign.
* Approved campaigns are posted to ``REKLAMA_KANAL_ID`` on a fixed daily
  schedule until ``total_posts`` is reached.

All prices and schedule sizes come from :class:`app.config.Settings` so the
operator can tune them without touching code.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import Settings
from app.database.models import AdCampaign, AdContentType, AdStatus, AdTariff, User

# Default posting hours (local server time) for each tariff. Operators can
# override these through ``REKLAMA_POST_HOURS_3`` / ``REKLAMA_POST_HOURS_5``.
WEEK_POST_HOURS: tuple[int, ...] = (9, 15, 21)
MONTH_POST_HOURS: tuple[int, ...] = (9, 12, 15, 18, 21)

TARIFF_LABELS: dict[AdTariff, str] = {
    AdTariff.WEEK: "1 Week",
    AdTariff.MONTH: "1 Month",
}



def tariff_label(tariff: AdTariff) -> str:
    return TARIFF_LABELS.get(tariff, tariff.value)


def tariff_price(tariff: AdTariff, settings: Settings) -> int:
    return settings.reklama_week_price if tariff is AdTariff.WEEK else settings.reklama_month_price


def tariff_duration_days(tariff: AdTariff) -> int:
    return 7 if tariff is AdTariff.WEEK else 30


def tariff_times_per_day(tariff: AdTariff, settings: Settings) -> int:
    if tariff is AdTariff.WEEK:
        return settings.reklama_week_times_per_day
    return settings.reklama_month_times_per_day


def tariff_total_posts(tariff: AdTariff, settings: Settings) -> int:
    return tariff_duration_days(tariff) * tariff_times_per_day(tariff, settings)


def post_hours(tariff: AdTariff, settings: Settings | None = None) -> tuple[int, ...]:
    """Return the daily posting hours for ``tariff``.

    Prefers the operator-configured hours from ``settings`` and falls back to
    the built-in defaults when settings are not supplied.
    """
    if settings is not None:
        configured = (
            settings.reklama_post_hours_3
            if tariff is AdTariff.WEEK
            else settings.reklama_post_hours_5
        )
        if configured:
            return tuple(sorted(configured))
    return WEEK_POST_HOURS if tariff is AdTariff.WEEK else MONTH_POST_HOURS


def next_post_time(
    tariff: AdTariff, now: datetime | None = None, settings: Settings | None = None
) -> datetime:
    """Return the next scheduled posting time strictly after ``now``.

    Uses the daily hours for the tariff (configurable via ``settings``). When
    all of today's slots have passed, the first slot of the next day is
    returned.
    """
    current = now or datetime.now(UTC)
    hours = post_hours(tariff, settings)
    for hour in hours:
        candidate = current.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate > current:
            return candidate
    first_hour = hours[0]
    tomorrow = (current + timedelta(days=1)).replace(hour=first_hour, minute=0, second=0, microsecond=0)
    return tomorrow



def detect_content_type(message) -> AdContentType | None:
    """Map a Telegram message to an :class:`AdContentType` (or ``None``)."""
    if getattr(message, "video", None) is not None:
        return AdContentType.VIDEO
    if getattr(message, "photo", None) is not None:
        return AdContentType.PHOTO
    if getattr(message, "document", None) is not None:
        return AdContentType.DOCUMENT
    return None


def extract_file_id(message, content_type: AdContentType) -> str | None:
    """Return the Telegram ``file_id`` for the detected content type."""
    if content_type is AdContentType.VIDEO and message.video is not None:
        return message.video.file_id
    if content_type is AdContentType.PHOTO and message.photo:
        return message.photo[-1].file_id
    if content_type is AdContentType.DOCUMENT and message.document is not None:
        return message.document.file_id
    return None


async def create_ad_campaign(
    session: AsyncSession,
    user: User,
    *,
    tariff: AdTariff,
    content_type: AdContentType,
    file_id: str,
    caption: str | None,
    settings: Settings,
) -> AdCampaign:
    """Create a PENDING campaign with tariff-derived pricing and schedule."""
    campaign = AdCampaign(
        user_id=user.id,
        tariff=tariff,
        price=tariff_price(tariff, settings),
        duration_days=tariff_duration_days(tariff),
        times_per_day=tariff_times_per_day(tariff, settings),
        total_posts=tariff_total_posts(tariff, settings),
        posted_count=0,
        content_type=content_type,
        file_id=file_id,
        caption=caption,
        status=AdStatus.PENDING,
    )
    session.add(campaign)
    await session.flush()
    return campaign


async def attach_receipt(session: AsyncSession, campaign_id: int, receipt_file_id: str) -> AdCampaign | None:
    campaign = await session.get(AdCampaign, campaign_id)
    if campaign is None:
        return None
    campaign.receipt_file_id = receipt_file_id
    await session.flush()
    return campaign


async def get_campaign(session: AsyncSession, campaign_id: int) -> AdCampaign | None:
    return await session.scalar(
        select(AdCampaign).options(selectinload(AdCampaign.user)).where(AdCampaign.id == campaign_id)
    )


async def set_admin_message_id(session: AsyncSession, campaign_id: int, message_id: int) -> None:
    campaign = await session.get(AdCampaign, campaign_id)
    if campaign is not None:
        campaign.admin_message_id = message_id
        await session.flush()


async def approve_campaign(
    session: AsyncSession,
    campaign_id: int,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> AdCampaign | None:
    """Approve a pending campaign and schedule its first post."""
    campaign = await session.scalar(
        select(AdCampaign).options(selectinload(AdCampaign.user)).where(AdCampaign.id == campaign_id)
    )
    if campaign is None or campaign.status is not AdStatus.PENDING:
        return None
    moment = now or datetime.now(UTC)
    campaign.status = AdStatus.ACTIVE
    campaign.approved_at = moment
    campaign.next_post_at = next_post_time(campaign.tariff, moment, settings)
    await session.flush()
    return campaign



async def reject_campaign(session: AsyncSession, campaign_id: int) -> AdCampaign | None:
    campaign = await session.scalar(
        select(AdCampaign).options(selectinload(AdCampaign.user)).where(AdCampaign.id == campaign_id)
    )
    if campaign is None or campaign.status is not AdStatus.PENDING:
        return None
    campaign.status = AdStatus.REJECTED
    await session.flush()
    return campaign


async def list_due_campaigns(session: AsyncSession, now: datetime | None = None) -> list[AdCampaign]:
    """Return ACTIVE campaigns whose ``next_post_at`` has arrived."""
    moment = now or datetime.now(UTC)
    rows = await session.scalars(
        select(AdCampaign)
        .options(selectinload(AdCampaign.user))
        .where(
            AdCampaign.status == AdStatus.ACTIVE,
            AdCampaign.next_post_at.is_not(None),
            AdCampaign.next_post_at <= moment,
        )
        .order_by(AdCampaign.next_post_at)
    )
    return list(rows)


async def record_post(
    session: AsyncSession,
    campaign_id: int,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> AdCampaign | None:
    """Increment ``posted_count`` and reschedule or complete the campaign."""
    campaign = await session.get(AdCampaign, campaign_id)
    if campaign is None or campaign.status is not AdStatus.ACTIVE:
        return None
    moment = now or datetime.now(UTC)
    campaign.posted_count += 1
    if campaign.posted_count >= campaign.total_posts:
        campaign.status = AdStatus.COMPLETED
        campaign.completed_at = moment
        campaign.next_post_at = None
    else:
        campaign.next_post_at = next_post_time(campaign.tariff, moment, settings)
    await session.flush()
    return campaign



async def list_campaigns(
    session: AsyncSession, status: AdStatus | None, page: int, page_size: int = 10
) -> tuple[list[AdCampaign], int]:
    query = select(AdCampaign).options(selectinload(AdCampaign.user)).order_by(AdCampaign.created_at.desc())
    if status is not None:
        query = query.where(AdCampaign.status == status)
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await session.scalars(query.offset(page * page_size).limit(page_size))
    return list(rows), total
