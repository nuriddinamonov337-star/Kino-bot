"""Tests for the ad poster worker (§12)."""

from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.database.base import Base
from app.database.models import AdContentType, AdStatus, AdTariff, User
from app.services.advertising import approve_campaign, create_ad_campaign
from app.workers.ad_poster import post_campaign


class _FakeBot:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str, str | None]] = []

    async def send_video(self, chat_id, file_id, caption=None):
        self.calls.append(("video", chat_id, file_id, caption))

    async def send_photo(self, chat_id, file_id, caption=None):
        self.calls.append(("photo", chat_id, file_id, caption))

    async def send_document(self, chat_id, file_id, caption=None):
        self.calls.append(("document", chat_id, file_id, caption))


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


@pytest.mark.asyncio
async def test_post_campaign_dispatches_by_content_type(session) -> None:
    settings = _settings()
    user = User(telegram_id=1, first_name="A")
    session.add(user)
    await session.flush()
    campaign = await create_ad_campaign(
        session,
        user,
        tariff=AdTariff.WEEK,
        content_type=AdContentType.VIDEO,
        file_id="vid",
        caption="Salom",
        settings=settings,
    )
    await approve_campaign(session, campaign.id, datetime(2026, 1, 1, 8, 0, tzinfo=UTC))
    bot = _FakeBot()
    assert await post_campaign(bot, -100123, campaign) is True
    assert bot.calls == [("video", -100123, "vid", "Salom")]


@pytest.mark.asyncio
async def test_post_campaign_photo_and_document(session) -> None:
    settings = _settings()
    user = User(telegram_id=2, first_name="B")
    session.add(user)
    await session.flush()
    photo = await create_ad_campaign(
        session,
        user,
        tariff=AdTariff.WEEK,
        content_type=AdContentType.PHOTO,
        file_id="pic",
        caption=None,
        settings=settings,
    )
    document = await create_ad_campaign(
        session,
        user,
        tariff=AdTariff.MONTH,
        content_type=AdContentType.DOCUMENT,
        file_id="doc",
        caption="Fayl",
        settings=settings,
    )
    bot = _FakeBot()
    assert await post_campaign(bot, -100, photo) is True
    assert await post_campaign(bot, -100, document) is True
    assert bot.calls == [
        ("photo", -100, "pic", None),
        ("document", -100, "doc", "Fayl"),
    ]


@pytest.mark.asyncio
async def test_post_campaign_returns_false_on_telegram_error(session) -> None:
    from telegram.error import TelegramError

    settings = _settings()
    user = User(telegram_id=3, first_name="C")
    session.add(user)
    await session.flush()
    campaign = await create_ad_campaign(
        session,
        user,
        tariff=AdTariff.WEEK,
        content_type=AdContentType.VIDEO,
        file_id="vid",
        caption=None,
        settings=settings,
    )

    class _FailingBot:
        async def send_video(self, *args, **kwargs):
            raise TelegramError("boom")

    assert await post_campaign(_FailingBot(), -100, campaign) is False
