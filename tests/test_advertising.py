import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import AdvertisingStatus, AdvertisingType, User
from app.keyboards.advertising import advertising_menu
from app.services.advertising import (
    create_advertising_request,
    get_contact_handle,
    update_advertising_status,
    validate_http_link,
    validate_target_count,
)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as value:
        yield value
    await engine.dispose()


def test_advertising_validation() -> None:
    assert validate_http_link("https://t.me/example") == "https://t.me/example"
    with pytest.raises(ValueError):
        validate_http_link("t.me/example")
    assert validate_target_count("500") == 500
    with pytest.raises(ValueError):
        validate_target_count("0")


def test_advertising_menu_labels_are_exact() -> None:
    labels = [
        button.text
        for row in advertising_menu().inline_keyboard
        for button in row
        if button.callback_data != "ad:cancel"
    ]
    assert labels == [
        "📢 Obunachi yig‘ish",
        "📣 Botda reklama",
        "📡 Kanallarda reklama",
        "👨‍💻 Admin bilan bog‘lanish",
    ]


def test_contact_handle_uses_configured_admin_username() -> None:
    assert get_contact_handle("cinestream_admin") == "@cinestream_admin"
    assert get_contact_handle("@cinestream_admin") == "@cinestream_admin"
    assert get_contact_handle(None) is None
    assert get_contact_handle("") is None


@pytest.mark.asyncio
async def test_advertising_request_lifecycle(session) -> None:
    user = User(telegram_id=7, first_name="A")
    session.add(user)
    await session.flush()
    request = await create_advertising_request(
        session,
        user,
        ad_type=AdvertisingType.SUBSCRIBERS,
        details="Kanalga obunachi kerak",
        channel_title="Test",
        channel_link="https://t.me/test",
        target_count=100,
    )
    assert request.status is AdvertisingStatus.PENDING
    assert request.campaign_id is not None
    updated = await update_advertising_status(session, request.id, AdvertisingStatus.APPROVED, 99)
    assert updated.status is AdvertisingStatus.APPROVED
    assert updated.reviewed_by == 99
