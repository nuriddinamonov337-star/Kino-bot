"""Telegram fayl yuklash va fallback (Problem 2).

``ReelPipeline._obtain_source`` quyidagilarni bajarishi kerak:

* Telegram ``file_id`` mavjud bo'lsa, avval shuni yuklab olish;
* Telegram yuklash muvaffaqiyatsiz bo'lsa, ``source_url`` ga o'tish (fallback);
* ikkalasi ham ishlamasa, aniq va tushunarli xato ko'tarish;
* xatolikni logga yozish (file_id va sabab bilan).
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from telegram.error import TelegramError

from app.video.pipeline import ReelPipeline
from app.video.processing import VideoProcessingError


class _FakeBot:
    """Minimal Bot stub: ``get_file`` natijasini boshqaradi."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.requested: list[str] = []

    async def get_file(self, file_id: str):
        self.requested.append(file_id)
        if self.fail:
            raise TelegramError("file is not available")
        return _FakeTelegramFile()


class _FakeTelegramFile:
    async def download_to_drive(self, custom_path: str) -> None:
        Path(custom_path).write_bytes(b"video-bytes")


def _pipeline(bot) -> ReelPipeline:
    return ReelPipeline(settings=SimpleNamespace(aimlapi_key_values=()), database=None, bot=bot)


def _movie(**kwargs):
    base = {
        "code": "777",
        "telegram_file_id": None,
        "telegram_file_unique_id": None,
        "source_url": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_telegram_file_id_is_preferred(tmp_path) -> None:
    bot = _FakeBot()
    pipeline = _pipeline(bot)
    destination = tmp_path / "source.mp4"
    movie = _movie(telegram_file_id="tg-file", source_url="https://example.com/video.mp4")

    await pipeline._obtain_source(movie, destination)

    assert bot.requested == ["tg-file"]
    assert destination.read_bytes() == b"video-bytes"


@pytest.mark.asyncio
async def test_falls_back_to_source_url_when_telegram_fails(tmp_path, monkeypatch) -> None:
    bot = _FakeBot(fail=True)
    pipeline = _pipeline(bot)
    destination = tmp_path / "source.mp4"
    movie = _movie(telegram_file_id="stale-file", source_url="https://example.com/video.mp4")

    called: dict[str, str] = {}

    async def _fake_download(url: str, dest: Path, *args, **kwargs) -> Path:
        called["url"] = url
        dest.write_bytes(b"from-url")
        return dest

    monkeypatch.setattr("app.video.pipeline.download_http_source", _fake_download)

    await pipeline._obtain_source(movie, destination)

    assert bot.requested == ["stale-file"]
    assert called["url"] == "https://example.com/video.mp4"
    assert destination.read_bytes() == b"from-url"


@pytest.mark.asyncio
async def test_clear_error_when_both_sources_fail(tmp_path, monkeypatch) -> None:
    bot = _FakeBot(fail=True)
    pipeline = _pipeline(bot)
    destination = tmp_path / "source.mp4"
    movie = _movie(telegram_file_id="stale-file", source_url="https://example.com/video.mp4")

    async def _boom(url: str, dest: Path, *args, **kwargs) -> Path:
        raise VideoProcessingError("HTTP 403")

    monkeypatch.setattr("app.video.pipeline.download_http_source", _boom)

    with pytest.raises(VideoProcessingError) as excinfo:
        await pipeline._obtain_source(movie, destination)

    message = str(excinfo.value)
    assert "Video yuklanmadi" in message
    assert "qayta forward qiling yoki URL yuboring" in message


@pytest.mark.asyncio
async def test_clear_error_when_no_source_at_all(tmp_path) -> None:
    bot = _FakeBot()
    pipeline = _pipeline(bot)
    destination = tmp_path / "source.mp4"
    movie = _movie()

    with pytest.raises(VideoProcessingError) as excinfo:
        await pipeline._obtain_source(movie, destination)

    assert "Video yuklanmadi" in str(excinfo.value)
