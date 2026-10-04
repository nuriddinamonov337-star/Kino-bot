"""Worker service startup and Railway config regression tests.

These guard the fixes for the Worker crash-loop on Railway:

- the worker must expose an HTTP health server (Railway healthcheck "/");
- the worker must fail with a clear logged error when config is invalid;
- a dedicated ``railway.worker.toml`` must exist with the worker start command.
"""

from pathlib import Path

import pytest

from app.config import Settings
from app.workers import reels

ROOT = Path(__file__).resolve().parents[1]


def test_worker_railway_config_uses_worker_command() -> None:
    config = (ROOT / "railway.worker.toml").read_text(encoding="utf-8")
    assert 'builder = "NIXPACKS"' in config
    assert 'startCommand = "python -m app.workers.reels"' in config
    assert "healthcheckPath" in config
    # The worker must NOT run migrations (the bot service owns that step).
    assert "alembic upgrade head" not in config


def test_root_railway_config_still_targets_bot() -> None:
    config = (ROOT / "railway.toml").read_text(encoding="utf-8")
    assert 'startCommand = "python -m app.bot"' in config


def test_requirements_pin_greenlet_and_headless_opencv() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "greenlet" in requirements
    assert "opencv-python-headless" in requirements


def test_worker_loop_accepts_health_server() -> None:
    import inspect

    signature = inspect.signature(reels.worker_loop)
    assert "health" in signature.parameters


def test_worker_main_exits_cleanly_on_invalid_config(monkeypatch) -> None:
    def boom() -> Settings:
        raise ValueError("missing BOT_TOKEN")

    monkeypatch.setattr(reels, "get_settings", boom)
    with pytest.raises(SystemExit) as excinfo:
        reels.main()
    assert excinfo.value.code == 1


def test_worker_run_builds_health_server_when_port_set(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_worker_loop(stop, health=None) -> None:
        captured["health"] = health

    monkeypatch.setattr(reels, "worker_loop", fake_worker_loop)
    settings = Settings(
        bot_token="test-token",
        database_url="sqlite+aiosqlite:///test.db",
        health_port=8080,
    )
    import asyncio

    asyncio.run(reels._run(asyncio.Event(), settings))
    assert captured["health"] is not None
