"""URL yuklash fallback (Problem 3).

``download_movie_source`` URL shakliga qarab asosiy strategiyani tanlaydi
(HLS/sahifa → yt-dlp, to'g'ridan-to'g'ri fayl → httpx). Agar asosiy strategiya
ishlamasa, ikkinchisiga o'tadi. Ikkalasi ham ishlamasa, aniq xato ko'taradi.
"""


import pytest

from app.video import downloader
from app.video.downloader import DownloadError, download_movie_source


@pytest.mark.asyncio
async def test_direct_mp4_uses_http_first(tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    async def _http(url, destination, *args, **kwargs):
        calls.append("http")
        destination.write_bytes(b"http")
        return destination

    async def _ytdlp(url, destination, *args, **kwargs):
        calls.append("ytdlp")
        destination.write_bytes(b"ytdlp")
        return destination

    monkeypatch.setattr(downloader, "download_http_source", _http)
    monkeypatch.setattr(downloader, "download_with_ytdlp", _ytdlp)

    result = await download_movie_source("https://cdn.example.com/video.mp4", tmp_path / "out.mp4")

    assert calls == ["http"]
    assert result.read_bytes() == b"http"


@pytest.mark.asyncio
async def test_hls_uses_ytdlp_first(tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    async def _http(url, destination, *args, **kwargs):
        calls.append("http")
        destination.write_bytes(b"http")
        return destination

    async def _ytdlp(url, destination, *args, **kwargs):
        calls.append("ytdlp")
        destination.write_bytes(b"ytdlp")
        return destination

    monkeypatch.setattr(downloader, "download_http_source", _http)
    monkeypatch.setattr(downloader, "download_with_ytdlp", _ytdlp)

    result = await download_movie_source("https://cdn.example.com/live/playlist.m3u8", tmp_path / "out.mp4")

    assert calls == ["ytdlp"]
    assert result.read_bytes() == b"ytdlp"


@pytest.mark.asyncio
async def test_falls_back_to_ytdlp_when_http_fails(tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    async def _http(url, destination, *args, **kwargs):
        calls.append("http")
        raise DownloadError("HTTP 403")

    async def _ytdlp(url, destination, *args, **kwargs):
        calls.append("ytdlp")
        destination.write_bytes(b"ytdlp")
        return destination

    monkeypatch.setattr(downloader, "download_http_source", _http)
    monkeypatch.setattr(downloader, "download_with_ytdlp", _ytdlp)

    result = await download_movie_source("https://cdn.example.com/video.mp4", tmp_path / "out.mp4")

    assert calls == ["http", "ytdlp"]
    assert result.read_bytes() == b"ytdlp"


@pytest.mark.asyncio
async def test_falls_back_to_http_when_ytdlp_fails(tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    async def _http(url, destination, *args, **kwargs):
        calls.append("http")
        destination.write_bytes(b"http")
        return destination

    async def _ytdlp(url, destination, *args, **kwargs):
        calls.append("ytdlp")
        raise DownloadError("yt-dlp not supported")

    monkeypatch.setattr(downloader, "download_http_source", _http)
    monkeypatch.setattr(downloader, "download_with_ytdlp", _ytdlp)

    result = await download_movie_source("https://example.com/watch?v=abc", tmp_path / "out.mp4")

    assert calls == ["ytdlp", "http"]
    assert result.read_bytes() == b"http"


@pytest.mark.asyncio
async def test_clear_error_when_both_strategies_fail(tmp_path, monkeypatch) -> None:
    async def _http(url, destination, *args, **kwargs):
        raise DownloadError("HTTP 403")

    async def _ytdlp(url, destination, *args, **kwargs):
        raise DownloadError("yt-dlp not supported")

    monkeypatch.setattr(downloader, "download_http_source", _http)
    monkeypatch.setattr(downloader, "download_with_ytdlp", _ytdlp)

    with pytest.raises(DownloadError) as excinfo:
        await download_movie_source("https://example.com/watch?v=abc", tmp_path / "out.mp4")

    message = str(excinfo.value)
    assert "URL yuklanmadi" in message
    assert "MP4 yoki HLS" in message
    assert "forward qiling" in message


@pytest.mark.asyncio
async def test_invalid_url_rejected_before_any_download(tmp_path, monkeypatch) -> None:
    async def _should_not_run(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("download strategy must not run for invalid URLs")

    monkeypatch.setattr(downloader, "download_http_source", _should_not_run)
    monkeypatch.setattr(downloader, "download_with_ytdlp", _should_not_run)

    with pytest.raises(DownloadError):
        await download_movie_source("ftp://example.com/video.mp4", tmp_path / "out.mp4")
