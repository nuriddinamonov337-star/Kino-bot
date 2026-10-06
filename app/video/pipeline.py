"""End-to-end Reel generation for a claimed ReelJob."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import UUID

from telegram import Bot
from telegram.error import TelegramError

from app.ai.client import AimlApiClient, AimlApiError
from app.config import Settings
from app.database.models import Movie, ReelJob
from app.database.session import Database
from app.services.reels import get_movie, mark_job_completed, mark_job_failed, save_reel
from app.utils.sanitize import sanitize_error
from app.video.moments import select_moments, select_moments_by_windows
from app.video.processing import (
    VideoProcessingError,
    detect_scenes,
    download_http_source,
    extract_clip,
    make_work_dir,
    probe_duration,
    render_vertical_reel,
    transcribe_clip,
    write_srt,
)

logger = logging.getLogger(__name__)


class ReelPipeline:
    def __init__(self, settings: Settings, database: Database, bot: Bot) -> None:
        self._settings = settings
        self._database = database
        self._bot = bot
        self._ai: AimlApiClient | None = None
        if settings.aimlapi_key_values:
            self._ai = AimlApiClient(
                keys=settings.aimlapi_key_values,
                base_url=settings.aimlapi_base_url,
                model=settings.aimlapi_model,
                timeout=settings.aimlapi_timeout,
                cooldown_seconds=settings.aimlapi_key_cooldown_seconds,
                fallback_model=settings.aimlapi_fallback_model,
            )

    async def run_job(self, job_id: UUID) -> None:
        async with self._database.session() as session:
            job = await session.get(ReelJob, job_id)
            movie = await get_movie(session, job.movie_id) if job else None
        if job is None or movie is None:
            logger.error("Reel job or movie is missing")
            return
        try:
            created = await self._process_movie(movie)
            async with self._database.session() as session:
                async with session.begin():
                    await mark_job_completed(session, job_id)
            await self._notify_admins(f"✅ Reels tayyor: {movie.title} ({created} ta).")
        except Exception as exc:
            logger.exception("Reel job failed")
            async with self._database.session() as session:
                async with session.begin():
                    failed = await mark_job_failed(
                        session,
                        job_id,
                        str(exc),
                        retry=True,
                        max_attempts=self._settings.reel_job_max_attempts,
                        backoff_seconds=self._settings.worker_retry_backoff_seconds,
                        max_backoff_seconds=self._settings.worker_retry_backoff_max_seconds,
                    )
            status = failed.status.value if failed else "failed"
            reason = sanitize_error(str(exc))[:300]
            await self._notify_admins(f"❌ Reel job {status}: {movie.title}.\nSabab: {reason}")

    async def _process_movie(self, movie: Movie) -> int:
        strategy = (self._settings.reel_moment_strategy or "auto").lower()
        if self._ai is None and strategy in ("metadata", "transcript"):
            raise AimlApiError("AIMLAPI keys are not configured")
        if self._settings.reels_channel_id is None:
            raise VideoProcessingError("REELS_CHANNEL_ID is not configured")
        work = make_work_dir(self._settings.video_work_dir)
        try:
            source = Path(work.name) / "source.mp4"
            await self._obtain_source(movie, source)
            duration = await probe_duration(self._settings.ffprobe_binary, source)
            face_track = await self._maybe_build_face_track(source)
            # §16-17: scene analysis (PySceneDetect + AI) runs BEFORE Whisper.
            # Only the transcript strategy needs a full-movie transcript up front;
            # every other strategy selects moments from scene boundaries first and
            # transcribes just the chosen clips afterwards.
            scenes = detect_scenes(source)
            use_windows = (
                self._ai is not None
                and strategy in ("auto", "transcript")
                and duration > self._settings.reel_use_windows_threshold
            )
            transcript = await self._maybe_transcribe_full(source, duration, strategy, use_windows)
            if use_windows and transcript:
                # Uzoq filmlar: 5 daqiqalik oynalar bo‘yicha moment tanlash.
                logger.info(
                    "Uzoq film (%.0fs): oynali moment tanlash ishlatiladi (window=%ds)",
                    duration,
                    self._settings.reel_window_seconds,
                )
                try:
                    selected = await select_moments_by_windows(
                        transcript,
                        ai_complete=self._ai.complete_json,
                        max_count=self._settings.reel_max_per_movie,
                        window_seconds=self._settings.reel_window_seconds,
                        min_duration=self._settings.reel_window_min_duration,
                        max_duration=self._settings.reel_window_max_duration,
                        max_retries=self._settings.reel_window_max_retries,
                    )
                except AimlApiError as exc:
                    logger.warning(
                        "Oynali tanlash muvaffaqiyatsiz (%s); oddiy usulga o‘tiladi",
                        sanitize_error(str(exc)),
                    )
                    selected = await select_moments(
                        scenes,
                        duration=duration,
                        max_count=self._settings.reel_max_per_movie,
                        strategy=strategy,
                        ai_complete=self._ai.complete_json,
                        transcript=transcript,
                        title=movie.title,
                        min_seconds=self._settings.reel_min_seconds,
                        max_seconds=self._settings.reel_max_seconds,
                    )
            else:
                selected = await select_moments(
                    scenes,
                    duration=duration,
                    max_count=self._settings.reel_max_per_movie,
                    strategy=strategy,
                    ai_complete=self._ai.complete_json if self._ai else None,
                    transcript=transcript,
                    title=movie.title,
                    min_seconds=self._settings.reel_min_seconds,
                    max_seconds=self._settings.reel_max_seconds,
                )
            logger.info(
                "Scene analysis selected %d moment(s) for %s (strategy=%s, transcript=%s, windows=%s)",
                len(selected),
                movie.title,
                strategy,
                "yes" if transcript else "no",
                "yes" if use_windows else "no",
            )
            created = 0
            for index, scene in enumerate(selected, start=1):
                clip = Path(work.name) / f"clip-{index}.mp4"
                vertical = Path(work.name) / f"reel-{index}.mp4"
                await extract_clip(self._settings.ffmpeg_binary, source, scene.start, scene.end, clip)
                srt_path = None
                try:
                    segments = transcribe_clip(clip, self._settings.whisper_model)
                    if segments:
                        srt_path = Path(work.name) / f"clip-{index}.srt"
                        write_srt(segments, srt_path)
                except VideoProcessingError:
                    logger.warning("Whisper failed for one clip; continuing without subtitles")
                face_center = face_track.center_for(scene.start, scene.end) if face_track else None
                await render_vertical_reel(self._settings, clip, srt_path, vertical, face_center_x=face_center)
                caption = f"{movie.title}\n{scene.reason}"
                with vertical.open("rb") as handle:
                    message = await self._bot.send_video(
                        chat_id=self._settings.reels_channel_id,
                        video=handle,
                        caption=caption[:1024],
                        supports_streaming=True,
                    )
                file_id = message.video.file_id if message.video else None
                if file_id is None:
                    raise VideoProcessingError("Telegram did not return a video file_id")
                async with self._database.session() as session:
                    async with session.begin():
                        await save_reel(
                            session,
                            movie_id=movie.id,
                            telegram_file_id=file_id,
                            caption=caption,
                            start_seconds=scene.start,
                            end_seconds=scene.end,
                            reason=scene.reason,
                        )
                created += 1
            if created == 0:
                raise VideoProcessingError("No Reels were produced")
            return created
        finally:
            work.cleanup()

    async def _obtain_source(self, movie: Movie, destination: Path) -> None:
        """Fetch the movie video, preferring the Telegram ``file_id``.

        If the Telegram download fails (stale ``file_id``, revoked access, file
        forwarded from a chat the bot cannot read, etc.) we log the exact reason
        and fall back to the owner-supplied ``source_url``. When both fail we
        raise a clear, admin-facing error.
        """
        telegram_error: str | None = None
        if movie.telegram_file_id:
            try:
                telegram_file = await self._bot.get_file(movie.telegram_file_id)
                await telegram_file.download_to_drive(custom_path=str(destination))
                return
            except TelegramError as exc:
                telegram_error = sanitize_error(str(exc))
                logger.warning(
                    "Telegram file download failed for movie %s (file_id=%s, unique_id=%s): %s",
                    movie.code,
                    movie.telegram_file_id,
                    movie.telegram_file_unique_id,
                    telegram_error,
                )
            except Exception as exc:  # noqa: BLE001 - defensive: never crash the worker
                telegram_error = sanitize_error(str(exc))
                logger.exception(
                    "Unexpected error downloading Telegram file for movie %s (file_id=%s)",
                    movie.code,
                    movie.telegram_file_id,
                )
        if movie.source_url:
            logger.info("Falling back to source_url for movie %s", movie.code)
            try:
                await download_http_source(movie.source_url, destination)
                return
            except Exception as exc:  # noqa: BLE001 - surface a clear message
                logger.warning("source_url download failed for movie %s: %s", movie.code, sanitize_error(str(exc)))
                raise VideoProcessingError(
                    "Video yuklanmadi. Sabab: "
                    f"{sanitize_error(str(exc))}. Iltimos, kinoni qayta forward qiling yoki URL yuboring."
                ) from exc
        if telegram_error is not None:
            raise VideoProcessingError(
                "Video yuklanmadi. Sabab: "
                f"{telegram_error}. Iltimos, kinoni qayta forward qiling yoki URL yuboring."
            )
        raise VideoProcessingError(
            "Video yuklanmadi. Sabab: kino uchun Telegram fayl ham, URL ham yo‘q. "
            "Iltimos, kinoni qayta forward qiling yoki URL yuboring."
        )

    async def _maybe_build_face_track(self, source: Path):
        """Build a face-centre track when enabled; ``None`` means static crop."""
        if not self._settings.reel_face_tracking:
            return None
        try:
            from app.video.framing import FaceTrackingError, compute_crop_window

            return await asyncio.to_thread(
                compute_crop_window, source, (1080, 1920)
            )
        except FaceTrackingError as exc:
            logger.warning("Face tracking disabled for this job: %s", exc)
            return None
        except Exception:
            logger.exception("Face-track scan crashed; falling back to static crop")
            return None

    async def _maybe_transcribe_full(
        self, source: Path, duration: float, strategy: str, use_windows: bool = False
    ):
        """Transcribe the whole movie for the transcript/window strategies.

        Short movies (<= ``REEL_TRANSCRIPT_MAX_DURATION``) are transcribed as
        before. Long movies are only transcribed when the window-based path is
        active (``use_windows``), because that path needs the full transcript to
        split it into 5-minute windows.
        """
        if strategy not in ("auto", "transcript"):
            return None
        if duration > self._settings.reel_transcript_max_duration and not use_windows:
            logger.info(
                "Movie is %.0fs; skipping full transcription (limit %ds)",
                duration,
                self._settings.reel_transcript_max_duration,
            )
            return None
        try:
            segments = await asyncio.to_thread(transcribe_clip, source, self._settings.whisper_model)
            return segments or None
        except VideoProcessingError:
            logger.warning("Full-movie transcription failed; continuing without transcript")
            return None

    async def _notify_admins(self, text: str) -> None:
        for admin_id in self._settings.admin_ids:
            try:
                await self._bot.send_message(admin_id, text)
            except TelegramError:
                logger.warning("Could not notify admin %s about reel job", admin_id)
