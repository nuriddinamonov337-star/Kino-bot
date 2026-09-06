"""Movie-code message handler."""

from telegram import Update
from telegram.ext import ContextTypes

from app.database.session import Database
from app.handlers.access import grant_or_request_subscription
from app.services.movies import find_active_movie_by_code


async def movie_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or message.text is None:
        return
    if not await grant_or_request_subscription(update, context):
        return
    database: Database = context.application.bot_data["database"]
    async with database.session() as session:
        movie = await find_active_movie_by_code(session, message.text.strip())
    if movie is None:
        await message.reply_text("Bunday kino topilmadi.")
        return
    caption = "\n\n".join(part for part in (movie.title, movie.description) if part)
    if movie.telegram_file_id:
        await message.reply_video(video=movie.telegram_file_id, caption=caption or None)
        return
    await message.reply_text(
        (caption + "\n\n" if caption else "") + "Video Telegram fayli sifatida saqlanmagan; faqat ruxsat etilgan manba URL mavjud."
    )
