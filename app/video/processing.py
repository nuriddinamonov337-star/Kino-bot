"""Authorized video acquisition, scene detection, transcription, and FFmpeg rendering."""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from app.config import Settings
from app.utils.sanitize import sanitize_error
from app.video.downloader import DownloadError
from app.video.downloader import download_http_source as _fetch_http_source

logger = logging.getLogger(__name__)

TranscribeFn = Callable[[Path], list[dict[str, object]]]


class VideoProcessingError(Exception):
    """Raised when an authorized source cannot be processed."""


async def run_command(args: list[str], *, timeout: float = 600) -> str:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError as exc:
        process.kill()
        raise VideoProcessingError("Video command timed out") from exc
    if process.returncode != 0:
        message = stderr.decode("utf-8", errors="replace")
        raise VideoProcessingError(sanitize_error(message or "Video command failed"))
    return stdout.decode("utf-8", errors="replace")


def make_work_dir(root: Path) -> tempfile.TemporaryDirectory[str]:
    root.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix="reel-", dir=str(root))


async def download_http_source(url: str, destination: Path, timeout: float = 300) -> None:
    """Download an owner-supplied URL (validated, size-limited). No access-control bypass."""
    try:
        await _fetch_http_source(url, destination, timeout=timeout)
    except DownloadError as exc:
        raise VideoProcessingError(str(exc)) from exc


async def probe_duration(ffprobe: str, path: Path) -> float:
    output = await run_command(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        timeout=60,
    )
    try:
        return float(output.strip())
    except ValueError as exc:
        raise VideoProcessingError("Unable to read video duration") from exc


def detect_scenes(path: Path) -> list[tuple[float, float]]:
    """Split the authorized file into scenes with PySceneDetect."""
    try:
        from scenedetect import ContentDetector, SceneManager, open_video
    except ImportError as exc:
        raise VideoProcessingError("PySceneDetect is not installed") from exc
    video = open_video(str(path))
    manager = SceneManager()
    manager.add_detector(ContentDetector())
    manager.detect_scenes(video)
    scenes = manager.get_scene_list()
    result = [(scene[0].get_seconds(), scene[1].get_seconds()) for scene in scenes]
    if not result:
        duration = float(video.duration.get_seconds()) if video.duration else 0.0
        if duration <= 0:
            raise VideoProcessingError("No scenes were detected")
        result = [(0.0, duration)]
    return result


def transcribe_clip(path: Path, model_name: str) -> list[dict[str, object]]:
    try:
        import whisper
    except ImportError as exc:
        raise VideoProcessingError("Whisper is not installed") from exc
    model = whisper.load_model(model_name)
    result = model.transcribe(str(path), language="uz", fp16=False)
    segments = result.get("segments") or []
    cleaned: list[dict[str, object]] = []
    for segment in segments:
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        cleaned.append(
            {
                "start": float(segment.get("start") or 0),
                "end": float(segment.get("end") or 0),
                "text": text,
            }
        )
    return cleaned


def write_srt(segments: list[dict[str, object]], destination: Path) -> None:
    lines: list[str] = []
    for index, segment in enumerate(segments, start=1):
        start = _srt_timestamp(float(segment["start"]))
        end = _srt_timestamp(float(segment["end"]))
        text = str(segment["text"]).replace("\n", " ")
        lines.extend([str(index), f"{start} --> {end}", text, ""])
    destination.write_text("\n".join(lines), encoding="utf-8")


def _srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


async def extract_clip(ffmpeg: str, source: Path, start: float, end: float, destination: Path) -> None:
    await run_command(
        [
            ffmpeg,
            "-y",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(source),
            "-t",
            f"{max(0.1, end - start):.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            str(destination),
        ],
        timeout=180,
    )


async def render_vertical_reel(
    settings: Settings,
    source: Path,
    srt_path: Path | None,
    destination: Path,
    face_center_x: float | None = None,
) -> None:
    """Render a 9:16 reel; static centre crop unless ``face_center_x`` is given.

    ``face_center_x`` is a normalised ``[0, 1]`` horizontal face centre for
    this clip (see ``app.video.framing``). ``None`` keeps the exact legacy
    static-crop behaviour. The import is local to avoid a module cycle.
    """
    if face_center_x is not None:
        from app.video.framing import render_vertical_reel_with_tracking

        await render_vertical_reel_with_tracking(
            settings.ffmpeg_binary, source, srt_path, destination, face_track=face_center_x
        )
        return
    filters = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
    if srt_path is not None and srt_path.exists():
        escaped = str(srt_path).replace("\\", "/").replace(":", "\\:")
        filters = f"{filters},subtitles='{escaped}'"
    await run_command(
        [
            settings.ffmpeg_binary,
            "-y",
            "-i",
            str(source),
            "-vf",
            filters,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-shortest",
            str(destination),
        ],
        timeout=300,
    )


def scene_prompt_payload(scenes: list[tuple[float, float]]) -> str:
    lines = ["Detected scenes (start-end seconds):"]
    for start, end in scenes[:80]:
        lines.append(f"{start:.2f}-{end:.2f}")
    return "\n".join(lines)


def cleanup_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
