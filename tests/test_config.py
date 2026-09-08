from pydantic import SecretStr

from app.config import Settings, parse_integer_list, parse_secret_list


def test_settings_parses_list_values() -> None:
    settings = Settings(
        bot_token="test-token",
        database_url="postgresql+asyncpg://user:pass@localhost:5432/test",
        redis_url="redis://localhost:6379/0",
        admin_ids="1, 2",
        required_channel_ids="-100123, -100456",
        aimlapi_keys="first, second",
        _env_file=None,
    )
    assert settings.admin_ids == (1, 2)
    assert settings.required_channel_ids == (-100123, -100456)
    assert [key.get_secret_value() for key in settings.aimlapi_keys] == ["first", "second"]


def test_empty_list_env_values_become_empty_tuples() -> None:
    settings = Settings(
        bot_token="test-token",
        database_url="postgresql+asyncpg://user:pass@localhost:5432/test",
        redis_url="redis://localhost:6379/0",
        admin_ids="",
        required_channel_ids="",
        aimlapi_keys="",
        _env_file=None,
    )
    assert settings.admin_ids == ()
    assert settings.required_channel_ids == ()
    assert settings.aimlapi_keys == ()


def test_parse_helpers_ignore_blank_and_json_looking_empty_values() -> None:
    assert parse_integer_list(None) == ()
    assert parse_integer_list("") == ()
    assert parse_integer_list("[]") == ()
    assert parse_integer_list("123456789,987654321") == (123456789, 987654321)
    assert parse_integer_list("-100123456789,-100987654321") == (-100123456789, -100987654321)
    assert parse_secret_list("") == ()
    assert parse_secret_list([SecretStr("a"), " b "]) == ("a", "b")


def test_numbered_aimlapi_keys_are_merged() -> None:
    settings = Settings(
        bot_token="test-token",
        database_url="postgresql://user:pass@localhost:5432/test",
        redis_url="redis://localhost:6379/0",
        aimlapi_key_1="one",
        aimlapi_key_2="two",
        aimlapi_key_3="three",
        _env_file=None,
    )
    assert settings.database_url.startswith("postgresql+asyncpg://")
    assert settings.aimlapi_key_values == ("one", "two", "three")


def test_railway_payment_and_advertising_variable_names_are_loaded() -> None:
    settings = Settings(
        bot_token="test-token",
        database_url="sqlite+aiosqlite://",
        card_number="9860 0601 2345 6789",
        card_owner="JOHN DOE",
        premium_week_price=10000,
        premium_month_price=15000,
        subscriber_100_price=15000,
        subscriber_500_price=70000,
        subscriber_1000_price=130000,
        admin_username="Nuriddin_Amonov_006",
        _env_file=None,
    )
    assert settings.card_number.get_secret_value() == "9860 0601 2345 6789"
    assert settings.card_owner == "JOHN DOE"
    assert settings.premium_weekly_price == 10000
    assert settings.premium_monthly_price == 15000
    assert settings.admin_contact_username == "Nuriddin_Amonov_006"
