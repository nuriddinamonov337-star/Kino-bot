"""Tests for the mandatory-channel subscriber-growth campaign (§13)."""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import MandatoryChannel
from app.services.admin import (
    increment_channel_campaign,
    list_active_campaigns,
    start_channel_campaign,
)
from app.services.subscriptions import count_campaign_subscribers


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as value:
        yield value
    await engine.dispose()


@pytest.mark.asyncio
async def test_start_channel_campaign_creates_active_channel(session) -> None:
    channel = await start_channel_campaign(
        session,
        chat_id=-100123,
        title="Test Kanal",
        username="testkanal",
        invite_url=None,
        target=100,
        price=15000,
    )
    await session.commit()
    assert channel.campaign_status == "active"
    assert channel.campaign_target == 100
    assert channel.campaign_current == 0
    assert channel.campaign_price == 15000
    assert channel.campaign_started_at is not None
    assert channel.is_active is True


@pytest.mark.asyncio
async def test_start_channel_campaign_reactivates_existing(session) -> None:
    first = await start_channel_campaign(
        session, chat_id=-100123, title="A", username=None, invite_url=None, target=100, price=15000
    )
    await session.commit()
    second = await start_channel_campaign(
        session, chat_id=-100123, title="B", username="b", invite_url=None, target=500, price=70000
    )
    await session.commit()
    assert second.id == first.id
    assert second.campaign_target == 500
    assert second.campaign_current == 0
    assert second.campaign_status == "active"


@pytest.mark.asyncio
async def test_increment_completes_campaign_at_target(session) -> None:
    channel = await start_channel_campaign(
        session, chat_id=-100123, title="A", username=None, invite_url=None, target=2, price=15000
    )
    await session.commit()
    assert await increment_channel_campaign(session, channel) is False
    assert channel.campaign_current == 1
    assert channel.campaign_status == "active"
    assert await increment_channel_campaign(session, channel) is True
    assert channel.campaign_current == 2
    assert channel.campaign_status == "completed"
    assert channel.campaign_completed_at is not None


@pytest.mark.asyncio
async def test_increment_ignores_inactive_campaign(session) -> None:
    channel = MandatoryChannel(chat_id=-100999, title="No campaign")
    session.add(channel)
    await session.commit()
    assert await increment_channel_campaign(session, channel) is False
    assert channel.campaign_current == 0


@pytest.mark.asyncio
async def test_count_campaign_subscribers_returns_completed(session) -> None:
    channel = await start_channel_campaign(
        session, chat_id=-100123, title="A", username=None, invite_url=None, target=1, price=15000
    )
    await session.commit()
    completed = await count_campaign_subscribers(session, [channel])
    await session.commit()
    assert completed == [channel]
    assert channel.campaign_status == "completed"


@pytest.mark.asyncio
async def test_list_active_campaigns(session) -> None:
    active = await start_channel_campaign(
        session, chat_id=-100123, title="Active", username=None, invite_url=None, target=100, price=15000
    )
    inactive = MandatoryChannel(chat_id=-100999, title="Inactive")
    session.add(inactive)
    await session.commit()
    result = await list_active_campaigns(session)
    assert [channel.id for channel in result] == [active.id]
