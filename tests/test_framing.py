"""Tests for face-aware vertical framing (no real video files needed)."""

import numpy as np
import pytest

from app.video import framing
from app.video.framing import (
    FaceTrack,
    build_vertical_filter,
    clamp_center,
    compute_crop_window,
    detect_faces,
    render_vertical_reel_with_tracking,
    smooth_trajectory,
)


def test_detect_faces_returns_empty_for_blank_frame() -> None:
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    assert detect_faces(blank) == []


def test_smooth_trajectory_averages_and_keeps_length() -> None:
    positions = [0.0, 0.0, 0.0, 10.0, 10.0, 10.0]
    smoothed = smooth_trajectory(positions, window=3)
    assert len(smoothed) == len(positions)
    assert smoothed[0] == pytest.approx(0.0)
    assert smoothed[-1] == pytest.approx(10.0)
    assert all(0.0 <= value <= 10.0 for value in smoothed)
    # transition is gradual, not a step
    assert smoothed[2] < smoothed[3]


def test_smooth_trajectory_edge_cases() -> None:
    assert smooth_trajectory([], window=5) == []
    assert smooth_trajectory([0.7], window=15) == [0.7]
    with pytest.raises(ValueError):
        smooth_trajectory([0.1], window=0)


def test_face_track_center_for_uses_median_window() -> None:
    track = FaceTrack(samples_per_second=2.0, centers=(0.2, 0.3, 0.8, 0.9))
    assert track.center_for(0.0, 1.0) == pytest.approx(0.3)
    assert track.center_for(1.0, 2.0) == pytest.approx(0.85)
    assert track.center_for(5.0, 4.0) is None
    assert FaceTrack(samples_per_second=2.0, centers=()).center_for(0, 10) is None


def test_clamp_center_bounds() -> None:
    assert clamp_center(-0.5) == 0.0
    assert clamp_center(1.5) == 1.0
    assert clamp_center(0.25) == 0.25


def test_static_filter_unchanged_when_no_track() -> None:
    assert (
        build_vertical_filter(None, None)
        == "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"
    )


def test_tracked_filter_centres_on_face() -> None:
    tracked = build_vertical_filter(0.25, None)
    assert "(iw-ow)*0.2500" in tracked
    assert "scale=1080:1920" in tracked
    clamped = build_vertical_filter(9.0, None)
    assert "(iw-ow)*1.0000" in clamped


async def test_render_with_none_track_uses_static_crop(monkeypatch, tmp_path) -> None:
    seen: list[list[str]] = []

    async def fake_run_command(args: list[str], *, timeout: float = 600) -> str:
        seen.append(args)
        return ""

    monkeypatch.setattr("app.video.processing.run_command", fake_run_command)
    await render_vertical_reel_with_tracking(
        "ffmpeg", tmp_path / "in.mp4", None, tmp_path / "out.mp4", face_track=None
    )
    vf = seen[0][seen[0].index("-vf") + 1]
    assert "crop=1080:1920" in vf


async def test_render_with_centre_uses_tracked_crop(monkeypatch, tmp_path) -> None:
    seen: list[list[str]] = []

    async def fake_run_command(args: list[str], *, timeout: float = 600) -> str:
        seen.append(args)
        return ""

    monkeypatch.setattr("app.video.processing.run_command", fake_run_command)
    track = FaceTrack(samples_per_second=2.0, centers=(0.2, 0.2, 0.2))
    await render_vertical_reel_with_tracking(
        "ffmpeg", tmp_path / "in.mp4", None, tmp_path / "out.mp4", face_track=track
    )
    vf = seen[0][seen[0].index("-vf") + 1]
    assert "(iw-ow)*0.2000" in vf


def test_compute_crop_window_returns_none_for_missing_file(tmp_path) -> None:
    assert compute_crop_window(tmp_path / "nope.mp4") is None


def test_face_tracking_flag_defaults_off() -> None:
    from app.config import Settings

    settings = Settings(bot_token="t", database_url="sqlite+aiosqlite://", _env_file=None)
    assert settings.reel_face_tracking is False
    assert settings.face_detection_model == "haar"


async def test_legacy_render_ignores_tracking_by_default(monkeypatch, tmp_path) -> None:
    """processing.render_vertical_reel() without a centre keeps legacy behaviour."""
    import app.video.processing as processing
    from app.config import Settings

    seen: list[list[str]] = []

    async def fake_run_command(args: list[str], *, timeout: float = 600) -> str:
        seen.append(args)
        return ""

    monkeypatch.setattr(processing, "run_command", fake_run_command)
    settings = Settings(bot_token="t", database_url="sqlite+aiosqlite://", _env_file=None)
    await processing.render_vertical_reel(settings, tmp_path / "in.mp4", None, tmp_path / "out.mp4")
    vf = seen[0][seen[0].index("-vf") + 1]
    assert "crop=1080:1920" in vf
    assert framing.build_vertical_filter(None, None) in vf
