"""Download owner-supplied videos from public URLs.

Two strategies are supported:

- :func:`download_http_source` — direct file URLs (MP4, etc.) via ``httpx``.
- :func:`download_with_ytdlp` — HLS/M3U8 streams and complex video pages via
  ``yt-dlp`` (no DRM/access-control bypass; default extractor behaviour only).
- :func:`download_movie_source` — small router that picks a strategy from the URL.

Security limits enforced for every download:

- only ``http``/``https`` URLs with a host name;
- URLs with embedded credentials are rejected;
- local/private hosts (SSRF protection) are rejected;
- files larger than 5 GiB are rejected (``Content-Length`` pre-check plus a
  running byte counter while streaming).
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.utils.sanitize import sanitize_error

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_DOWNLOAD_BYTES = 5 * 1024**3  # 5 GiB
_HTTP_CHUNK_SIZE = 1024 * 256


class DownloadError(Exception):
    """Raised when a URL is invalid or its video cannot be downloaded."""


def validate_source_url(url: str) -> str:
    """Return the normalized URL or raise :class:`DownloadError`.

    Rejects non-http(s) schemes, missing hosts, embedded credentials and
    local/private hosts to reduce SSRF risk.
    """
    cleaned = (url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES or not parsed.netloc:
        raise DownloadError("Only full http/https URLs are accepted")
    if parsed.username or parsed.password or "@" in parsed.netloc:
        raise DownloadError("URLs with embedded credentials are not accepted")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or host == "localhost":
        raise DownloadError("Local hosts are not accepted")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_reserved or address.is_unspecified):
        raise DownloadError("Private/local addresses are not accepted")
    return cleaned


def looks_like_stream_or_page(url: str) -> bool:
    """Heuristically decide whether plain HTTP is unlikely to be a file."""
    lowered = url.lower()
    if ".m3u8" in lowered:
        return True
    path = urlparse(lowered).path
    return not any(path.endswith(suffix) for suffix in (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg"))


async def download_http_source(
    url: str,
    destination: Path,
    timeout: float = 600,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
) -> Path:
    """Download a direct file URL with ``httpx`` streaming."""
    cleaned = validate_source_url(url)
    logger.info("Downloading direct video URL (host=%s)", urlparse(cleaned).hostname)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, max_redirects=5) as client:
            async with client.stream("GET", cleaned) as response:
                if response.status_code >= 400:
                    raise DownloadError(f"Source returned HTTP {response.status_code}")
                declared = response.headers.get("content-length")
                if declared is not None:
                    try:
                        if int(declared) > max_bytes:
                            raise DownloadError(
                                f"File is too large ({int(declared) // (1024 * 1024)} MB; limit {max_bytes // (1024 * 1024)} MB)"
                            )
                    except ValueError:
                        pass
                total = 0
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("wb") as handle:
                    async for chunk in response.aiter_bytes(_HTTP_CHUNK_SIZE):
                        total += len(chunk)
                        if total > max_bytes:
                            raise DownloadError(
                                f"File exceeds the {max_bytes // (1024 * 1024)} MB limit"
                            )
                        handle.write(chunk)
    except DownloadError:
        raise
    except httpx.HTTPError as exc:
        raise DownloadError(f"Download failed: {sanitize_error(str(exc))}") from exc
    if not destination.exists() or destination.stat().st_size == 0:
        raise DownloadError("Downloaded file is empty")
    logger.info("Direct download finished (%d bytes)", destination.stat().st_size)
    return destination


async def download_with_ytdlp(
    url: str,
    destination: Path,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
) -> Path:
    """Download HLS/M3U8 or video pages with ``yt-dlp`` (no DRM bypass)."""
    cleaned = validate_source_url(url)
    try:
        import yt_dlp
    except ImportError as exc:
        raise DownloadError(
            "yt-dlp is not installed. Install it with: pip install yt-dlp"
        ) from exc
    logger.info("Downloading with yt-dlp (host=%s)", urlparse(cleaned).hostname)
    destination.parent.mkdir(parents=True, exist_ok=True)
    options = {
        "format": "mp4/best",
        "outtmpl": str(destination),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": max_bytes,
    }

    def _run() -> None:
        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.download([cleaned])

    try:
        await asyncio.to_thread(_run)
    except DownloadError:
        raise
    except Exception as exc:
        raise DownloadError(f"yt-dlp download failed: {sanitize_error(str(exc))}") from exc
    if not destination.exists() or destination.stat().st_size == 0:
        raise DownloadError("yt-dlp did not produce a video file")
    if destination.stat().st_size > max_bytes:
        raise DownloadError(f"File exceeds the {max_bytes // (1024 * 1024)} MB limit")
    logger.info("yt-dlp download finished (%d bytes)", destination.stat().st_size)
    return destination


async def download_movie_source(
    url: str,
    destination: Path,
    timeout: float = 600,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
) -> Path:
    """Download an owner-supplied URL, picking HTTP or yt-dlp automatically."""
    cleaned = validate_source_url(url)
    if looks_like_stream_or_page(cleaned):
        return await download_with_ytdlp(cleaned, destination, max_bytes=max_bytes)
    return await download_http_source(cleaned, destination, timeout=timeout, max_bytes=max_bytes)