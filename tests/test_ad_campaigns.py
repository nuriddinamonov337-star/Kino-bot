"""Tests for the paid advertising campaign system (§12).

Covers the six behaviours required by the spec:

1. Tariff pricing and schedule sizes come from settings.
2. The tariff menu labels are exact.
3. ``next_post_time`` uses the fixed daily hours.
4. The full campaign lifecycle (create → receipt → approve → post → complete).
5. Campaigns complete after ``total_posts`` posts.
6. Rejecting and listing campaigns works.
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.database.base import Base
from app.database.models import AdContentType, AdStatus, AdTariff, User
from app.keyboards.advertising import tariff_menu
from app.services.advertising import (
    approve_campaign,
    attach_receipt,
    create_ad_campaign,
    get_campaign,
    list_campaigns,
    list_due_campaigns,
    next_post_time,
    record_post,
    reject_campaign,
    tariff_duration_days,
    tariff_price,
    tariff_times_per_day,
    tariff_total_posts,
)


def _settings() -> Settings:
    return Settings(bot_token="x", database_url="sqlite+aiosqlite://", _env_file=None)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as value:
        yield value
    await engine.dispose()


def test_tariff_pricing_defaults() -> None:
    settings = _settings()
    assert tariff_price(AdTariff.WEEK, settings) == 30000
    assert tariff_price(AdTariff.MONTH, settings) == 100000
    assert tariff_duration_days(AdTariff.WEEK) == 7
    assert tariff_duration_days(AdTariff.MONTH) == 30
    assert tariff_times_per_day(AdTariff.WEEK, settings) == 3
    assert tariff_times_per_day(AdTariff.MONTH, settings) == 5
    assert tariff_total_posts(AdTariff.WEEK, settings) == 21
    assert tariff_total_posts(AdTariff.MONTH, settings) == 150


def test_tariff_menu_labels_are_exact() -> None:
    labels = [button.text for row in tariff_menu(30000, 100000).inline_keyboard for button in row]
    assert labels == [
        "🔹 1 Week — 30,000 so'm",
        "🔹 1 Month — 100,000 so'm",
        "❌ Bekor qilish",
    ]


def test_next_post_time_uses_fixed_hours() -> None:
    # 08:00 → next slot is 09:00 the same day.
    morning = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
    assert next_post_time(AdTariff.WEEK, morning) == datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    # 22:00 → all slots passed, first slot next day.
    night = datetime(2026, 1, 1, 22, 0, tzinfo=UTC)
    assert next_post_time(AdTariff.WEEK, night) == datetime(2026, 1, 2, 9, 0, tzinfo=UTC)


def test_next_post_time_respects_configured_hours() -> None:
    settings = Settings(
        bot_token="x",
        database_url="sqlite+aiosqlite://",
        reklama_post_hours_3=(10, 14, 20),
        _env_file=None,
    )
    morning = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
    assert next_post_time(AdTariff.WEEK, morning, settings) == datetime(2026, 1, 1, 10, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_campaign_lifecycle(session) -> None:
    settings = _settings()
    user = User(telegram_id=7, first_name="A")
    session.add(user)
    await session.flush()
    campaign = await create_ad_campaign(
        session,
        user,
        tariff=AdTariff.WEEK,
        content_type=AdContentType.VIDEO,
        file_id="file-1",
        caption="Reklama",
        settings=settings,
    )
    assert campaign.status is AdStatus.PENDING
    assert campaign.price == 30000
    assert campaign.total_posts == 21
    await attach_receipt(session, campaign.id, "receipt-1")
    assert campaign.receipt_file_id == "receipt-1"

    approved = await approve_campaign(session, campaign.id, datetime(2026, 1, 1, 8, 0, tzinfo=UTC))
    assert approved is not None and approved.status is AdStatus.ACTIVE
    assert approved.next_post_at == datetime(2026, 1, 1, 9, 0, tzinfo=UTC)

    due = await list_due_campaigns(session, datetime(2026, 1, 1, 9, 0, tzinfo=UTC))
    assert [item.id for item in due] == [campaign.id]

    updated = await record_post(session, campaign.id, datetime(2026, 1, 1, 9, 0, tzinfo=UTC))
    assert updated is not None and updated.posted_count == 1
    assert updated.status is AdStatus.ACTIVE


@pytest.mark.asyncio
async def test_campaign_completes_after_total_posts(session) -> None:
    settings = _settings()
    user = User(telegram_id=8, first_name="B")
    session.add(user)
    await session.flush()
    campaign = await create_ad_campaign(
        session,
        user,
        tariff=AdTariff.WEEK,
        content_type=AdContentType.PHOTO,
        file_id="file-2",
        caption=None,
        settings=settings,
    )
    await approve_campaign(session, campaign.id, datetime(2026, 1, 1, 8, 0, tzinfo=UTC))
    campaign.total_posts = 2
    await session.flush()
    await record_post(session, campaign.id, datetime(2026, 1, 1, 9, 0, tzinfo=UTC))
    final = await record_post(session, campaign.id, datetime(2026, 1, 1, 15, 0, tzinfo=UTC))
    assert final is not None
    assert final.status is AdStatus.COMPLETED
    assert final.next_post_at is None
    assert final.completed_at is not None


@pytest.mark.asyncio
async def test_reject_and_list_campaigns(session) -> None:
    settings = _settings()
    user = User(telegram_id=9, first_name="C")
    session.add(user)
    await session.flush()
    campaign = await create_ad_campaign(
        session,
        user,
        tariff=AdTariff.MONTH,
        content_type=AdContentType.DOCUMENT,
        file_id="file-3",
        caption="Doc",
        settings=settings,
    )
    rejected = await reject_campaign(session, campaign.id)
    assert rejected is not None and rejected.status is AdStatus.REJECTED
    # Rejecting again is a no-op.
    assert await reject_campaign(session, campaign.id) is None

    rows, total = await list_campaigns(session, AdStatus.REJECTED, 0)
    assert total == 1 and rows[0].id == campaign.id
    fetched = await get_campaign(session, campaign.id)
    assert fetched is not None and fetched.user.telegram_id == 9
