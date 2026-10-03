"""Face-aware vertical framing for Reels.

Pipeline role (see ``app/video/pipeline.py``): while the default path uses a
static centre crop, this module optionally centres each scene on the
speaker's face (OpenShorts-style subject tracking):

1. :func:`compute_crop_window` scans the source video ( Haar cascade,
   ``sample_fps`` frames/second) and builds a smoothed, time-indexed
   :class:`FaceTrack` of horizontal face centres.
2. For every selected scene the pipeline takes the median centre inside
   ``[start, end]`` and renders that clip with a face-centred 9:16 crop.
3. Any failure (no OpenCV, no faces, unreadable file) returns ``None`` and
   the caller silently falls back to the static centre crop, so output is
   always produced.

The crop is stable *within* a scene (one offset per clip) and dynamic
*across* scenes. Per-frame animated crops were deliberately avoided: they
cause motion sickness on dialogue scenes and multiply FFmpeg cost.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920


class FaceTrackingError(Exception):
    """Raised when face tracking is requested but cannot run."""


@dataclass(frozen=True, slots=True)
class FaceTrack:
    """Smoothed horizontal face centres, normalised to ``[0, 1]`` of frame width."""

    samples_per_second: float
    centers: tuple[float, ...]

    def center_for(self, start: float, end: float) -> float | None:
        """Median face centre inside ``[start, end]`` seconds, or ``None``."""
        if not self.centers or end <= start:
            return None
        first = max(0, int(start * self.samples_per_second))
        if end == float("inf"):
            last = len(self.centers)
        else:
            last = min(len(self.centers), int(end * self.samples_per_second) + 1)
        window = [c for c in self.centers[first:last] if c is not None]
        if not window:
            return None
        return float(statistics.median(window))


def detect_faces(frame) -> list[tuple[int, int, int, int]]:
    """Return ``(x, y, w, h)`` face boxes in a BGR frame (Haar cascade).

    Returns an empty list when OpenCV is missing or no faces are found, so
    callers can always fall back to the static crop.
    """
    try:
        import cv2
    except ImportError:
        return []
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    if not cascade_path.exists():
        return []
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    cascade = cv2.CascadeClassifier(str(cascade_path))
    if cascade.empty():
        return []
    boxes = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
    return [(int(x), int(y), int(w), int(h)) for x, y, w, h in boxes]


def smooth_trajectory(positions: list[float], window: int = 15) -> list[float]:
    """Centred moving average; output length equals input length."""
    if window < 1:
        raise ValueError("window must be >= 1")
    if not positions:
        return []
    half = window // 2
    smoothed: list[float] = []
    for i in range(len(positions)):
        part = positions[max(0, i - half) : i + half + 1]
        smoothed.append(sum(part) / len(part))
    return smoothed


def compute_crop_window(
    video_path: Path,
    output_size: tuple[int, int] = (TARGET_WIDTH, TARGET_HEIGHT),
    sample_fps: float = 2.0,
    window: int = 15,
) -> FaceTrack | None:
    """Build a smoothed face-centre track for *video_path*, or ``None``.

    ``None`` means "no usable faces" (or no OpenCV) and the caller must use
    the static centre crop. Never raises for unreadable files.
    """
    _ = output_size  # reserved for future per-target tuning
    try:
        import cv2
    except ImportError as exc:
        raise FaceTrackingError("OpenCV (opencv-python) is not installed") from exc
    capture = cv2.VideoCapture(str(video_path))
    try:
        native_fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
        step = max(1, int(round(native_fps / sample_fps)))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        centers: list[float] = []
        last_known = 0.5
        index = 0
        saw_face = False
        while True:
            grabbed, frame = capture.read()
            if not grabbed or frame is None:
                break
            if index % step == 0:
                boxes = detect_faces(frame)
                if boxes and width > 0:
                    biggest = max(boxes, key=lambda box: box[2] * box[3])
                    last_known = min(1.0, max(0.0, (biggest[0] + biggest[2] / 2) / width))
                    saw_face = True
                centers.append(last_known)
            index += 1
    except Exception as exc:
        logger.warning("Face-track scan failed: %s", exc)
        return None
    finally:
        capture.release()
    if not saw_face or not centers:
        logger.info("No faces found in %s; using static crop", video_path)
        return None
    effective_fps = (native_fps / step) if "native_fps" in dir() else sample_fps
    smoothed = smooth_trajectory(centers, window=window)
    logger.info("Face track built for %s (%d samples)", video_path, len(smoothed))
    return FaceTrack(samples_per_second=effective_fps, centers=tuple(smoothed))


def clamp_center(value: float) -> float:
    return min(1.0, max(0.0, value))


def build_vertical_filter(face_center_x: float | None, srt_path: Path | None) -> str:
    """9:16 filter: face-centred crop when a centre is given, else static crop."""
    if face_center_x is None:
        filters = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
    else:
        fx = clamp_center(face_center_x)
        filters = (
            "crop=w='min(iw,ih*9/16)':h='min(ih,iw*16/9)'"
            f":x='(iw-ow)*{fx:.4f}':y='(ih-oh)/2',"
            "scale=1080:1920,setsar=1"
        )
    if srt_path is not None and srt_path.exists():
        escaped = str(srt_path).replace("\\", "/").replace(":", "\\:")
        filters = f"{filters},subtitles='{escaped}'"
    return filters


async def render_vertical_reel_with_tracking(
    ffmpeg_binary: str,
    source: Path,
    srt_path: Path | None,
    destination: Path,
    face_track: FaceTrack | list[float] | None = None,
    timeout: float = 300,
) -> None:
    """Render a 9:16 reel; face-centred crop when a track/centre is supplied.

    ``face_track`` accepts a :class:`FaceTrack` (median centre is used), a raw
    centre value, or ``None`` for the legacy static crop. Import is local so
    ``app.video.processing`` never gains a hard dependency on this module.
    """
    from app.video.processing import run_command

    if isinstance(face_track, FaceTrack):
        center = face_track.center_for(0, float("inf"))
    elif isinstance(face_track, (int, float)):
        center = float(face_track)
    elif isinstance(face_track, (list, tuple)) and face_track:
        center = float(statistics.median(face_track))
    else:
        center = None
    await run_command(
        [
            ffmpeg_binary,
            "-y",
            "-i",
            str(source),
            "-vf",
            build_vertical_filter(center, srt_path),
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
        timeout=timeout,
    )