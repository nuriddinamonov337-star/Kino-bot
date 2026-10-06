"""Protected ConversationHandlers for movie creation and soft deletion."""

import logging
import tempfile
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from app.config import get_settings
from app.database.models import Movie
from app.database.session import Database
from app.handlers.admin_auth import admin_access
from app.keyboards.admin import CANCEL, cancel, confirm_movie_delete, movie_menu, movie_preview, source_choice
from app.queue import JobQueue
from app.services.admin import create_movie, get_movie_by_code, hard_delete_movie, movie_code_exists
from app.services.reels import create_reel_job_if_absent
from app.utils.sanitize import sanitize_error
from app.video.downloader import DownloadError, download_movie_source, validate_source_url

logger = logging.getLogger(__name__)
SOURCE, CODE, TITLE, DESCRIPTION, POSTER, PREVIEW = range(6)
DELETE_CODE, DELETE_CONFIRM = range(10, 12)
MAX_CODE, MAX_TITLE, MAX_DESCRIPTION = 20, 500, 4000


def _draft(context: ContextTypes.DEFAULT_TYPE) -> dict[str, object]:
    return context.user_data.setdefault("admin_movie_draft", {})


async def _allowed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return await admin_access(update, context)


async def begin_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _allowed(update, context): return ConversationHandler.END
    await update.callback_query.answer()
    _draft(context).clear()
    await update.callback_query.edit_message_text("➕ Kino qo'shish\n\n🎬 Video yuboring/forward qiling yoki URL usulini tanlang.", reply_markup=source_choice())
    return SOURCE


async def choose_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _allowed(update, context): return ConversationHandler.END
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("🎬 Kino videosini yuboring yoki kanaldagi postdan forward qiling.", reply_markup=cancel())
    return SOURCE


async def choose_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _allowed(update, context): return ConversationHandler.END
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("🔗 http/https URL yuboring. Video serverga yuklab olinadi va Telegram'ga yuklanadi (5 GB gacha).", reply_markup=cancel())
    return SOURCE


async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _allowed(update, context): return ConversationHandler.END
    message = update.effective_message
    if message is None or message.video is None: return SOURCE
    draft = _draft(context)
    draft.update(
        telegram_file_id=message.video.file_id,
        telegram_file_unique_id=getattr(message.video, "file_unique_id", None),
        main_channel_message_id=getattr(message, "forward_from_message_id", None) or message.message_id,
    )
    await message.reply_text("Kino kodi? (faqat raqam, 20 belgigacha)", reply_markup=cancel())
    return CODE


# Bot API orqali bitta xabarda yuklash mumkin bo'lgan maksimal hajm.
TELEGRAM_BOT_UPLOAD_LIMIT_BYTES = 50 * 1024 * 1024


async def receive_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _allowed(update, context): return ConversationHandler.END
    message = update.effective_message
    if message is None: return SOURCE
    raw_url = (message.text or "").strip()
    try:
        url = validate_source_url(raw_url)
    except DownloadError:
        await message.reply_text("Faqat to‘liq http/https URL yuboring.")
        return SOURCE
    progress = await message.reply_text("⏳ Video yuklanmoqda, iltimos kuting...")
    tmp_dir = tempfile.TemporaryDirectory(prefix="movie-url-")
    try:
        destination = Path(tmp_dir.name) / "source.mp4"
        await download_movie_source(url, destination)
        size = destination.stat().st_size
        draft = _draft(context)
        draft["source_url"] = url
        if size <= TELEGRAM_BOT_UPLOAD_LIMIT_BYTES:
            await progress.edit_text("⏳ Telegram'ga yuklanmoqda...")
            with destination.open("rb") as handle:
                sent = await context.bot.send_video(
                    chat_id=message.chat_id,
                    video=handle,
                    supports_streaming=True,
                    caption="🎬 Tasdiqlash uchun yuklangan video.",
                )
            file_id = sent.video.file_id if sent.video else None
            if file_id is None:
                raise DownloadError("Telegram file_id qaytarmadi")
            draft["telegram_file_id"] = file_id
            await progress.edit_text(f"✅ Video qabul qilindi ({size // (1024 * 1024)} MB).")
        else:
            logger.info("URL video exceeds Bot API upload limit (%d bytes); keeping source_url only", size)
            await progress.edit_text(
                f"✅ Video serverga yuklandi ({size // (1024 * 1024)} MB). "
                "Hajmi katta bo‘lgani uchun Telegram'ga yuklanmadi — worker qayta ishlashda URL dan oladi."
            )
    except DownloadError as exc:
        logger.warning("URL movie download failed: %s", sanitize_error(str(exc)))
        await progress.edit_text(
            "❌ URL yuklanmadi.\n\n"
            f"Sabab: {sanitize_error(str(exc))}\n\n"
            "Iltimos:\n"
            "• Faqat ochiq va ruxsat etilgan MP4 yoki HLS URL'larni yuboring.\n"
            "• DRM yoki Cloudflare himoyasi bo'lgan saytlar ishlamaydi.\n"
            "• Yoki videoni to'g'ridan-to'g'ri forward qiling."
        )
        return SOURCE
    except TelegramError as exc:
        logger.exception("Telegram upload failed for URL movie")
        await progress.edit_text(f"❌ Telegram'ga yuklashda xatolik: {sanitize_error(str(exc))}. Qayta urinib ko‘ring.")
        return SOURCE
    except Exception:
        logger.exception("Unexpected URL movie intake failure")
        await progress.edit_text("❌ Kutilmagan xatolik yuz berdi. Qayta urinib ko‘ring.")
        return SOURCE
    finally:
        tmp_dir.cleanup()
    await message.reply_text("Kino kodi? (faqat raqam, 20 belgigacha)", reply_markup=cancel())
    return CODE


async def receive_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _allowed(update, context): return ConversationHandler.END
    message, code = update.effective_message, (update.effective_message.text or "").strip()
    if not code.isdigit() or len(code) > MAX_CODE:
        await message.reply_text("Kod faqat raqam va 20 belgidan oshmasligi kerak.")
        return CODE
    database: Database = context.application.bot_data["database"]
    async with database.session() as session:
        if await movie_code_exists(session, code):
            await message.reply_text("Bu kod allaqachon mavjud. Boshqa kod yuboring.")
            return CODE
    _draft(context)["code"] = code
    await message.reply_text("Kino nomi? (500 belgigacha)", reply_markup=cancel())
    return TITLE


async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _allowed(update, context): return ConversationHandler.END
    message, title = update.effective_message, (update.effective_message.text or "").strip()
    if not title or len(title) > MAX_TITLE:
        await message.reply_text("Nomi bo‘sh bo‘lmasin va 500 belgidan oshmasin.")
        return TITLE
    _draft(context)["title"] = title
    await message.reply_text("Kino tavsifi? Ixtiyoriy. O‘tkazib yuborish uchun '-' yuboring.", reply_markup=cancel())
    return DESCRIPTION


async def receive_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _allowed(update, context): return ConversationHandler.END
    message, description = update.effective_message, (update.effective_message.text or "").strip()
    if len(description) > MAX_DESCRIPTION:
        await message.reply_text("Tavsif 4000 belgidan oshmasin.")
        return DESCRIPTION
    _draft(context)["description"] = None if description == "-" else description
    await message.reply_text("Poster rasm yuboring yoki o'tkazib yuborish uchun '-' yuboring.", reply_markup=cancel())
    return POSTER


async def _publish_movie_to_main_channel(context: ContextTypes.DEFAULT_TYPE, *, code: str, title: str, description: str | None, poster_file_id: str | None, telegram_file_id: str | None) -> int | None:
    """Post a saved movie to MAIN_CHANNEL. Returns message_id or None. Never raises."""
    channel_id = get_settings().main_channel_id
    if channel_id is None:
        logger.warning("MAIN_CHANNEL_ID is not configured; skipping channel post for movie %s", code)
        return None
    caption = f"🎬 {title}\n🔢 Kod: {code}"
    if description:
        caption += f"\n📝 {description}"
    caption = caption[:1024]
    try:
        if poster_file_id:
            sent = await context.bot.send_photo(chat_id=channel_id, photo=poster_file_id, caption=caption)
        elif telegram_file_id:
            sent = await context.bot.send_video(chat_id=channel_id, video=telegram_file_id, caption=caption, supports_streaming=True)
        else:
            sent = await context.bot.send_message(chat_id=channel_id, text=caption)
        logger.info("Movie %s posted to main channel (message_id=%s)", code, sent.message_id)
        return sent.message_id
    except TelegramError as exc:
        logger.warning("Main channel post failed for movie %s: %s", code, sanitize_error(str(exc)))
        return None
    except Exception:
        logger.exception("Unexpected main channel post failure for movie %s", code)
        return None


def _preview_text(draft: dict[str, object]) -> str:
    """Render the collected draft for admin confirmation (no DB write yet)."""
    title = str(draft.get("title") or "—")
    code = str(draft.get("code") or "—")
    description = draft.get("description")
    has_video = bool(draft.get("telegram_file_id") or draft.get("source_url"))
    lines = [
        "🎬 Kino nomi: " + title,
        "🔢 Kodi: " + code,
        "📝 Tavsif: " + (str(description) if description else "—"),
        "🖼 Poster: " + ("bor" if draft.get("poster_file_id") else "yo‘q"),
        "🎞 Video: " + ("mavjud" if has_video else "yo‘q"),
        "",
        "Saqlashni tasdiqlaysizmi?",
    ]
    return "\n".join(lines)


async def finish_movie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Collect the poster and show a preview. Nothing is written to the DB yet."""
    if not await _allowed(update, context): return ConversationHandler.END
    message = update.effective_message
    draft = _draft(context)
    if message.photo:
        draft["poster_file_id"] = message.photo[-1].file_id
    elif (message.text or "").strip() != "-":
        await message.reply_text("Poster uchun rasm yuboring yoki '-' yuboring.")
        return POSTER
    await message.reply_text(_preview_text(draft), reply_markup=movie_preview())
    return PREVIEW


async def save_movie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Persist the draft only after the admin presses 'Saqlash'."""
    if not await _allowed(update, context): return ConversationHandler.END
    query = update.callback_query
    if query is None: return ConversationHandler.END
    await query.answer()
    draft = _draft(context)
    if not draft.get("code") or not draft.get("title"):
        await query.edit_message_text("Ma’lumot to‘liq emas. Qaytadan boshlang.", reply_markup=movie_menu())
        context.user_data.pop("admin_movie_draft", None)
        return ConversationHandler.END
    database: Database = context.application.bot_data["database"]
    try:
        async with database.session() as session:
            async with session.begin():
                movie = await create_movie(session, **draft)
                job, created = await create_reel_job_if_absent(session, movie.id)
                saved = {"id": movie.id, "code": movie.code, "title": movie.title, "description": movie.description, "poster_file_id": movie.poster_file_id, "telegram_file_id": movie.telegram_file_id}
    except IntegrityError:
        logger.exception("Movie creation duplicate or integrity failure")
        await query.edit_message_text("Bu kod allaqachon mavjud. Boshqa kod yuboring.", reply_markup=movie_menu())
        context.user_data.pop("admin_movie_draft", None)
        return ConversationHandler.END
    except Exception:
        logger.exception("Movie creation failed")
        await query.edit_message_text("Kino saqlanmadi. Qayta urinib ko‘ring.", reply_markup=movie_menu())
        context.user_data.pop("admin_movie_draft", None)
        return ConversationHandler.END
    context.user_data.pop("admin_movie_draft", None)
    queue: JobQueue | None = context.application.bot_data.get("queue")
    queued = False
    if created and queue is not None:
        queued = await queue.enqueue(job.id)
    extra = " Reel job navbatga qo‘yildi." if created and queued else " Reel job PostgreSQL’da pending (Redis yo‘q yoki band)."
    if not created:
        extra = " Bu kino uchun Reel job allaqachon mavjud."
    channel_message_id = await _publish_movie_to_main_channel(
        context,
        code=str(saved["code"]),
        title=str(saved["title"]),
        description=saved["description"],  # type: ignore[arg-type]
        poster_file_id=saved["poster_file_id"],  # type: ignore[arg-type]
        telegram_file_id=saved["telegram_file_id"],  # type: ignore[arg-type]
    )
    if channel_message_id is not None:
        try:
            async with database.session() as session:
                async with session.begin():
                    stored = await session.get(Movie, saved["id"])
                    if stored is not None:
                        stored.main_channel_message_id = channel_message_id
        except Exception:
            logger.warning("Movie %s saved but main_channel_message_id could not be stored", saved["code"])
        extra += " Kanalga post yuborildi."
    else:
        extra += " ⚠️ Kanalga post yuborilmadi (logni tekshiring)."
    await query.edit_message_text(f"✅ Kino muvaffaqiyatli saqlandi.{extra}", reply_markup=movie_menu())
    return ConversationHandler.END


async def begin_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _allowed(update, context): return ConversationHandler.END
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("🗑 O‘chirish uchun kino kodini yuboring.", reply_markup=cancel())
    return DELETE_CODE


async def receive_delete_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _allowed(update, context): return ConversationHandler.END
    message, code = update.effective_message, (update.effective_message.text or "").strip()
    if not code.isdigit() or len(code) > MAX_CODE:
        await message.reply_text("Kod faqat raqam bo‘lishi kerak.")
        return DELETE_CODE
    database: Database = context.application.bot_data["database"]
    async with database.session() as session:
        movie = await get_movie_by_code(session, code)
    if movie is None:
        await message.reply_text("Faol kino topilmadi. Boshqa kod yuboring.")
        return DELETE_CODE
    context.user_data["admin_delete_movie_id"] = movie.id
    await message.reply_text(f"🎬 Kino: {movie.title}\nKod: {movie.code}\n\nHaqiqatan o‘chirasizmi?", reply_markup=confirm_movie_delete(movie.id))
    return DELETE_CONFIRM


async def _delete_main_channel_post(context: ContextTypes.DEFAULT_TYPE, message_id: int | None) -> bool:
    """Delete the movie's post from MAIN_CHANNEL. Returns True on success."""
    channel_id = get_settings().main_channel_id
    if channel_id is None or message_id is None:
        return False
    try:
        await context.bot.delete_message(chat_id=channel_id, message_id=message_id)
        return True
    except TelegramError as exc:
        logger.warning("Main channel post delete failed (message_id=%s): %s", message_id, sanitize_error(str(exc)))
        return False


async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Hard-delete the movie, its Reels/ReelJobs, and its main-channel post."""
    if not await _allowed(update, context): return ConversationHandler.END
    query = update.callback_query
    movie_id = context.user_data.get("admin_delete_movie_id")
    if query is None or movie_id is None or str(movie_id) not in (query.data or ""):
        await query.answer("So‘rov yaroqsiz.", show_alert=True)
        return ConversationHandler.END
    database: Database = context.application.bot_data["database"]
    channel_message_id: int | None = None
    deleted = None
    try:
        async with database.session() as session:
            async with session.begin():
                deleted = await hard_delete_movie(session, movie_id)
                if deleted is not None:
                    channel_message_id = deleted.main_channel_message_id
    except IntegrityError as exc:
        # Foreign-key or constraint failure: the transaction is rolled back by
        # the ``session.begin()`` context manager, so nothing is left half-done.
        logger.exception("Movie hard delete hit an integrity error")
        await query.answer()
        await query.edit_message_text(
            "❌ Kinoni o‘chirib bo‘lmadi (bog‘liq yozuvlar bilan ziddiyat).\n"
            f"Sabab: {sanitize_error(str(exc))[:200]}\n"
            "Iltimos, qayta urinib ko‘ring yoki administratorga murojaat qiling.",
            reply_markup=movie_menu(),
        )
        return ConversationHandler.END
    except Exception as exc:
        logger.exception("Movie hard delete failed")
        await query.answer()
        await query.edit_message_text(
            f"❌ O‘chirishda xatolik yuz berdi: {sanitize_error(str(exc))[:200]}",
            reply_markup=movie_menu(),
        )
        return ConversationHandler.END
    context.user_data.pop("admin_delete_movie_id", None)
    if deleted is None:
        await query.answer()
        await query.edit_message_text("Kino topilmadi yoki avval o‘chirilgan.", reply_markup=movie_menu())
        return ConversationHandler.END
    post_removed = await _delete_main_channel_post(context, channel_message_id)
    extra = " Kanal posti ham o‘chirildi." if post_removed else ""
    await query.answer()
    await query.edit_message_text(f"✅ Kino butunlay o‘chirildi (reels va joblar bilan).{extra}", reply_markup=movie_menu())
    return ConversationHandler.END


async def cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _allowed(update, context): return ConversationHandler.END
    context.user_data.pop("admin_movie_draft", None)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Bekor qilindi.", reply_markup=movie_menu())
    return ConversationHandler.END


movie_conversation = ConversationHandler(
    entry_points=[CallbackQueryHandler(begin_add, pattern=r"^adm:movie:add$")],
    states={SOURCE: [CallbackQueryHandler(choose_video, pattern=r"^adm:movie:video$"), CallbackQueryHandler(choose_url, pattern=r"^adm:movie:url$"), MessageHandler(filters.VIDEO, receive_video), MessageHandler(filters.TEXT & ~filters.COMMAND, receive_url)], CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_code)], TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title)], DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_description)], POSTER: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, finish_movie)], PREVIEW: [CallbackQueryHandler(save_movie, pattern=r"^adm:movie:save$")]},
    fallbacks=[CallbackQueryHandler(cancel_flow, pattern=rf"^{CANCEL}$")],
    name="admin_movie_add",
)

movie_delete_conversation = ConversationHandler(
    entry_points=[CallbackQueryHandler(begin_delete, pattern=r"^adm:movie:delete$")],
    states={DELETE_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_delete_code)], DELETE_CONFIRM: [CallbackQueryHandler(confirm_delete, pattern=r"^adm:movie:confirm:[0-9a-f-]{36}$")]},
    fallbacks=[CallbackQueryHandler(cancel_flow, pattern=rf"^{CANCEL}$")],
    name="admin_movie_delete",
)
