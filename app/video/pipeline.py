"""End-to-end Reel generation for a claimed ReelJob."""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from telegram import Bot
from telegram.error import TelegramError

from app.ai.client import SCENE_SYSTEM_PROMPT, AimlApiClient, AimlApiError, parse_scene_analysis
from app.config import Settings
from app.database.models import Movie, ReelJob
from app.database.session import Database
from app.services.reels import get_movie, mark_job_completed, mark_job_failed, save_reel
from app.video.processing import (
    VideoProcessingError,
    detect_scenes,
    download_http_source,
    extract_clip,
    make_work_dir,
    probe_duration,
    render_vertical_reel,
    scene_prompt_payload,
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
            await self._notify_admins(f"❌ Reel job {status}: {movie.title}.")

    async def _process_movie(self, movie: Movie) -> int:
        if self._ai is None:
            raise AimlApiError("AIMLAPI keys are not configured")
        if self._settings.reels_channel_id is None:
            raise VideoProcessingError("REELS_CHANNEL_ID is not configured")
        work = make_work_dir(self._settings.video_work_dir)
        try:
            source = Path(work.name) / "source.mp4"
            await self._obtain_source(movie, source)
            duration = await probe_duration(self._settings.ffprobe_binary, source)
            scenes = detect_scenes(source)
            analysis = await self._ai.complete_json(
                system=SCENE_SYSTEM_PROMPT,
                user=(
                    f"Movie title: {movie.title}\nDuration seconds: {duration:.2f}\n"
                    f"{scene_prompt_payload(scenes)}\n"
                    "Return JSON for the most engaging 15-30 second moments."
                ),
            )
            selected = parse_scene_analysis(
                analysis,
                max_scenes=self._settings.reel_max_per_movie,
                min_seconds=self._settings.reel_min_seconds,
                max_seconds=self._settings.reel_max_seconds,
                video_duration=duration,
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
                await render_vertical_reel(self._settings, clip, srt_path, vertical)
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
        if movie.telegram_file_id:
            try:
                telegram_file = await self._bot.get_file(movie.telegram_file_id)
                await telegram_file.download_to_drive(custom_path=str(destination))
                return
            except TelegramError as exc:
                raise VideoProcessingError("Telegram file download failed") from exc
        if movie.source_url:
            await download_http_source(movie.source_url, destination)
            return
        raise VideoProcessingError("Movie has no authorized Telegram file or owner-supplied URL")

    async def _notify_admins(self, text: str) -> None:
        for admin_id in self._settings.admin_ids:
            try:
                await self._bot.send_message(admin_id, text)
            except TelegramError:
                logger.warning("Could not notify admin %s about reel job", admin_id)
