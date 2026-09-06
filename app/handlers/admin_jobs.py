"""Admin ReelJob status and retry callbacks."""

from uuid import UUID

from telegram import Update
from telegram.ext import ContextTypes

from app.database.models import ReelJobStatus
from app.database.session import Database
from app.handlers.admin_auth import admin_only
from app.keyboards.admin import jobs_list_menu
from app.queue import JobQueue
from app.services.reels import list_reel_jobs, retry_failed_job


@admin_only
async def jobs_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int | None = None) -> None:
    query = update.callback_query
    if query is None:
        return
    if page is None:
        page = max(0, int((query.data or "adm:jobs:0").rsplit(":", 1)[-1]))
    database: Database = context.application.bot_data["database"]
    async with database.session() as session:
        jobs, total = await list_reel_jobs(session, page)
    lines = [f"🎞 Reel joblar ({total})"]
    for job in jobs:
        title = job.movie.title if job.movie else "?"
        error = f" | {job.error}" if job.error else ""
        lines.append(f"{job.status.value} | {title} | urinish {job.attempts}{error}")
    last_failed = [job.id for job in jobs if job.status is ReelJobStatus.FAILED]
    try:
        await query.answer()
    except Exception:
        pass
    await query.edit_message_text(
        "\n".join(lines) if jobs else "Joblar yo‘q.",
        reply_markup=jobs_list_menu(page, total, last_failed),
    )


@admin_only
async def jobs_retry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    try:
        job_id = UUID((query.data or "").split(":")[2])
    except (IndexError, ValueError):
        await query.answer("Noto‘g‘ri job.", show_alert=True)
        return
    database: Database = context.application.bot_data["database"]
    async with database.session() as session:
        async with session.begin():
            job = await retry_failed_job(session, job_id)
    if job is None:
        await query.answer("Qayta urinish mumkin emas.", show_alert=True)
        return
    queue: JobQueue | None = context.application.bot_data.get("queue")
    if queue is not None:
        await queue.enqueue(job.id)
    await query.answer("Job navbatga qaytarildi.")
    await jobs_list(update, context, page=0)
