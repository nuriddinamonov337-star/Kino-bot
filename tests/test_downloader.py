"""Unit tests for URL validation and download routing (no network access)."""

import pytest

from app.video.downloader import (
    DownloadError,
    download_movie_source,
    download_with_ytdlp,
    looks_like_stream_or_page,
    validate_source_url,
)


def test_valid_http_urls_are_accepted() -> None:
    assert validate_source_url("https://example.com/video.mp4") == "https://example.com/video.mp4"
    assert validate_source_url("  http://cdn.example.com/a/b.mov  ") == "http://cdn.example.com/a/b.mov"


@pytest.mark.parametrize(
    "bad_url",
    [
        "ftp://example.com/video.mp4",
        "not-a-url",
        "",
        "http://localhost/video.mp4",
        "http://127.0.0.1/video.mp4",
        "http://10.0.0.5/video.mp4",
        "http://192.168.1.1/video.mp4",
        "http://user:password@example.com/video.mp4",
        "https://example.com",  # no path is fine? must still pass scheme/host check
    ],
)
def test_unsafe_urls_are_rejected(bad_url: str) -> None:
    if bad_url == "https://example.com":
        assert validate_source_url(bad_url) == bad_url  # host-only URLs are allowed
        return
    with pytest.raises(DownloadError):
        validate_source_url(bad_url)


def test_routing_prefers_ytdlp_for_streams_and_pages() -> None:
    assert looks_like_stream_or_page("https://cdn.example.com/video.mp4") is False
    assert looks_like_stream_or_page("https://cdn.example.com/live/playlist.m3u8") is True
    assert looks_like_stream_or_page("https://example.com/watch?v=abc123") is True


async def test_ytdlp_missing_reports_install_hint(tmp_path) -> None:
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        with pytest.raises(DownloadError, match="yt-dlp is not installed"):
            await download_with_ytdlp("https://example.com/watch?v=abc123", tmp_path / "out.mp4")
        return
    pytest.skip("yt-dlp is installed; missing-dependency path not exercised")


async def test_router_rejects_invalid_url_without_network(tmp_path) -> None:
    with pytest.raises(DownloadError):
        await download_movie_source("ftp://example.com/video.mp4", tmp_path / "out.mp4")