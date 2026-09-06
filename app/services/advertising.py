"""Advertising request persistence and validation."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import (
    AdvertisingRequest,
    AdvertisingStatus,
    AdvertisingType,
    CampaignStatus,
    SubscriberCampaign,
    User,
)

MAX_DETAILS = 2000
MAX_TITLE = 255


def get_contact_handle(admin_contact_username: str | None) -> str | None:
    """Return a normalized Telegram username for direct admin contact."""
    if admin_contact_username is None:
        return None
    value = admin_contact_username.strip()
    if not value:
        return None
    if value.startswith("@"):
        return value
    return f"@{value}"


def validate_http_link(value: str) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Link http/https bo‘lishi kerak.")
    return value.strip()


def validate_target_count(value: str) -> int:
    if not value.strip().isdigit():
        raise ValueError("Obunachi soni butun musbat son bo‘lishi kerak.")
    count = int(value.strip())
    if count < 1 or count > 1_000_000:
        raise ValueError("Obunachi soni 1–1000000 oralig‘ida bo‘lishi kerak.")
    return count


def validate_details(value: str) -> str:
    text = value.strip()
    if len(text) < 5 or len(text) > MAX_DETAILS:
        raise ValueError("Matn 5–2000 belgi bo‘lishi kerak.")
    return text


async def create_advertising_request(
    session: AsyncSession,
    user: User,
    *,
    ad_type: AdvertisingType,
    details: str,
    channel_title: str | None = None,
    channel_link: str | None = None,
    target_count: int | None = None,
) -> AdvertisingRequest:
    campaign_id = None
    if ad_type is AdvertisingType.SUBSCRIBERS:
        campaign = SubscriberCampaign(
            channel_id=0,
            channel_title=channel_title or "",
            channel_link=channel_link or "",
            target_count=target_count or 0,
            status=CampaignStatus.PENDING,
        )
        session.add(campaign)
        await session.flush()
        campaign_id = campaign.id
    request = AdvertisingRequest(
        user_id=user.id,
        ad_type=ad_type,
        status=AdvertisingStatus.PENDING,
        details=details,
        channel_title=channel_title,
        channel_link=channel_link,
        target_count=target_count,
        campaign_id=campaign_id,
    )
    session.add(request)
    await session.flush()
    return request


async def list_advertising_requests(
    session: AsyncSession, status: AdvertisingStatus | None, page: int, page_size: int = 10
) -> tuple[list[AdvertisingRequest], int]:
    query = select(AdvertisingRequest).order_by(AdvertisingRequest.created_at.desc())
    if status is not None:
        query = query.where(AdvertisingRequest.status == status)
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await session.scalars(query.offset(page * page_size).limit(page_size))
    return list(rows), total


async def get_advertising_request(session: AsyncSession, request_id: UUID) -> AdvertisingRequest | None:
    return await session.scalar(
        select(AdvertisingRequest)
        .options(selectinload(AdvertisingRequest.user))
        .where(AdvertisingRequest.id == request_id)
    )


async def update_advertising_status(
    session: AsyncSession,
    request_id: UUID,
    status: AdvertisingStatus,
    admin_telegram_id: int,
    note: str | None = None,
) -> AdvertisingRequest | None:
    request = await session.scalar(
        select(AdvertisingRequest)
        .options(selectinload(AdvertisingRequest.user))
        .where(AdvertisingRequest.id == request_id)
    )
    if request is None:
        return None
    request.status = status
    request.reviewed_by = admin_telegram_id
    request.reviewed_at = datetime.now(UTC)
    if note:
        request.admin_note = note[:1000]
    if request.campaign_id is not None:
        campaign = await session.get(SubscriberCampaign, request.campaign_id)
        if campaign is not None:
            campaign.status = {
                AdvertisingStatus.APPROVED: CampaignStatus.ACTIVE,
                AdvertisingStatus.COMPLETED: CampaignStatus.COMPLETED,
                AdvertisingStatus.REJECTED: CampaignStatus.CANCELLED,
                AdvertisingStatus.CANCELLED: CampaignStatus.CANCELLED,
            }.get(status, campaign.status)
    await session.flush()
    return request
