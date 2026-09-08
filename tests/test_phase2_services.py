from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from telegram.error import TelegramError

from app.database.base import Base
from app.database.models import Admin, MandatoryChannel, Movie, User
from app.services.movies import find_active_movie_by_code
from app.services.permissions import is_admin
from app.services.subscriptions import check_mandatory_subscriptions, get_active_mandatory_channels
from app.services.users import has_active_premium, register_or_update_user


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as database_session:
        yield database_session
    await engine.dispose()


@pytest.mark.asyncio
async def test_user_registration_updates_instead_of_creating_duplicate(session) -> None:
    telegram_user = SimpleNamespace(id=101, username="old_name", first_name="Ali")
    first = await register_or_update_user(session, telegram_user)
    await session.commit()
    telegram_user.username, telegram_user.first_name = "new_name", "Vali"
    second = await register_or_update_user(session, telegram_user)
    await session.commit()
    assert first.id == second.id
    assert second.username == "new_name"
    assert second.first_name == "Vali"


def test_premium_bypass_uses_utc_and_requires_unexpired_value() -> None:
    user = User(telegram_id=1, first_name="A", premium_until=datetime.now(UTC) + timedelta(seconds=1))
    assert has_active_premium(user)
    user.premium_until = datetime.now(UTC) - timedelta(seconds=1)
    assert not has_active_premium(user)


class FakeBot:
    def __init__(self, statuses: dict[int, object]) -> None:
        self.statuses = statuses

    async def get_chat_member(self, chat_id: int, user_id: int):
        response = self.statuses[chat_id]
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(status=response)


@pytest.mark.asyncio
async def test_mandatory_subscription_marks_missing_and_api_errors_as_not_verified() -> None:
    channels = [
        MandatoryChannel(chat_id=-1001, title="A"),
        MandatoryChannel(chat_id=-1002, title="B"),
        MandatoryChannel(chat_id=-1003, title="C"),
    ]
    result = await check_mandatory_subscriptions(
        FakeBot({-1001: "member", -1002: "left", -1003: TelegramError("temporary")}), 42, channels
    )
    assert [channel.chat_id for channel in result.missing] == [-1002]
    assert [channel.chat_id for channel in result.unavailable] == [-1003]
    assert not result.is_subscribed


@pytest.mark.asyncio
async def test_configured_required_channels_are_added_to_database_channels(session) -> None:
    channels = await get_active_mandatory_channels(session, (-100777,))
    assert [channel.chat_id for channel in channels] == [-100777]


@pytest.mark.asyncio
async def test_movie_lookup_returns_only_active_movie(session) -> None:
    session.add_all([
        Movie(code="1527", title="Active", telegram_file_id="file-active"),
        Movie(code="9999", title="Inactive", telegram_file_id="file-inactive", is_active=False),
    ])
    await session.commit()
    assert (await find_active_movie_by_code(session, "1527")).title == "Active"
    assert await find_active_movie_by_code(session, "9999") is None


@pytest.mark.asyncio
async def test_admin_permission_accepts_config_or_database_admin(session) -> None:
    session.add(Admin(telegram_id=22))
    await session.commit()
    assert await is_admin(session, 11, (11,))
    assert await is_admin(session, 22, ())
    assert not await is_admin(session, 33, ())
