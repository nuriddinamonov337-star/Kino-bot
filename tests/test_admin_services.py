from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import MandatoryChannel, Movie, User
from app.services.admin import (
    add_database_admin,
    create_mandatory_channel,
    create_movie,
    dashboard_statistics,
    hard_delete_movie,
    list_database_admins,
    movie_code_exists,
    remove_database_admin,
    soft_delete_channel,
)


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
async def test_duplicate_movie_code_is_detectable(session) -> None:
    await create_movie(session, code="1527", title="Test", telegram_file_id="file")
    await session.commit()
    assert await movie_code_exists(session, "1527")


@pytest.mark.asyncio
async def test_movie_creation_and_hard_delete(session) -> None:
    movie = await create_movie(session, code="1528", title="New", source_url="https://example.com/video")
    await session.commit()
    assert movie.telegram_file_id is None
    deleted = await hard_delete_movie(session, movie.id)
    await session.commit()
    assert deleted is not None and deleted.code == "1528"
    assert await session.get(Movie, movie.id) is None
    assert await hard_delete_movie(session, movie.id) is None


@pytest.mark.asyncio
async def test_mandatory_channel_creation_reactivates_and_soft_deletes(session) -> None:
    channel = await create_mandatory_channel(session, chat_id=-1001, title="Channel", username="channel", invite_url=None)
    await session.commit()
    assert await soft_delete_channel(session, channel.id)
    await session.commit()
    assert channel.is_active is False
    restored = await create_mandatory_channel(session, chat_id=-1001, title="Updated", username="new", invite_url="https://t.me/new")
    assert restored.id == channel.id and restored.is_active


@pytest.mark.asyncio
async def test_statistics_query(session) -> None:
    session.add_all([User(telegram_id=1, first_name="A"), User(telegram_id=2, first_name="B", is_active=False), User(telegram_id=3, first_name="C", premium_until=datetime.now(UTC) + timedelta(days=1)), Movie(code="1", title="Active", telegram_file_id="a"), Movie(code="2", title="Inactive", telegram_file_id="b", is_active=False), MandatoryChannel(chat_id=-1002, title="Active"), MandatoryChannel(chat_id=-1003, title="Inactive", is_active=False)])
    await session.commit()
    result = await dashboard_statistics(session)
    assert result["users"] == 3
    assert result["active_users"] == 2
    assert result["premium_users"] == 1
    assert result["movies"] == 2
    assert result["active_movies"] == 1
    assert result["active_channels"] == 1
    assert result["reels"] == 0
    assert result["reel_jobs"] == 0
    assert result["pending_payments"] == 0
    assert result["revenue"] == 0
    assert result["ad_requests"] == 0


@pytest.mark.asyncio
async def test_database_admin_crud(session) -> None:
    await add_database_admin(session, 555)
    await add_database_admin(session, 555)  # idempotent
    await session.commit()
    admins = await list_database_admins(session)
    assert [admin.telegram_id for admin in admins] == [555]
    assert await remove_database_admin(session, 555) is True
    await session.commit()
    assert await list_database_admins(session) == []
    assert await remove_database_admin(session, 555) is False
