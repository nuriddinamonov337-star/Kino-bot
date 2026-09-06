"""Protected ConversationHandlers for movie creation and soft deletion."""

import logging
from urllib.parse import urlparse

from sqlalchemy.exc import IntegrityError
from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from app.database.session import Database
from app.handlers.admin_auth import admin_access
from app.keyboards.admin import CANCEL, cancel, confirm_movie_delete, movie_menu, source_choice
from app.queue import JobQueue
from app.services.admin import create_movie, get_movie_by_code, movie_code_exists, soft_delete_movie
from app.services.reels import create_reel_job_if_absent

logger = logging.getLogger(__name__)
SOURCE, CODE, TITLE, DESCRIPTION, POSTER = range(5)
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
    await update.callback_query.edit_message_text("🔗 http/https URL yuboring. Video hozir yuklanmaydi, faqat metadata saqlanadi.", reply_markup=cancel())
    return SOURCE


async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _allowed(update, context): return ConversationHandler.END
    message = update.effective_message
    if message is None or message.video is None: return SOURCE
    draft = _draft(context)
    draft.update(telegram_file_id=message.video.file_id, main_channel_message_id=getattr(message, "forward_from_message_id", None) or message.message_id)
    await message.reply_text("Kino kodi? (faqat raqam, 20 belgigacha)", reply_markup=cancel())
    return CODE


async def receive_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _allowed(update, context): return ConversationHandler.END
    message = update.effective_message
    url = (message.text or "").strip() if message else ""
    if urlparse(url).scheme not in {"http", "https"} or not urlparse(url).netloc:
        await message.reply_text("Faqat to‘liq http/https URL yuboring.")
        return SOURCE
    _draft(context)["source_url"] = url
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


async def finish_movie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _allowed(update, context): return ConversationHandler.END
    message = update.effective_message
    draft = _draft(context)
    if message.photo:
        draft["poster_file_id"] = message.photo[-1].file_id
    elif (message.text or "").strip() != "-":
        await message.reply_text("Poster uchun rasm yuboring yoki '-' yuboring.")
        return POSTER
    database: Database = context.application.bot_data["database"]
    try:
        async with database.session() as session:
            async with session.begin():
                movie = await create_movie(session, **draft)
                job, created = await create_reel_job_if_absent(session, movie.id)
    except IntegrityError:
        logger.exception("Movie creation duplicate or integrity failure")
        await message.reply_text("Bu kod allaqachon mavjud. Boshqa kod yuboring.")
        return CODE
    except Exception:
        logger.exception("Movie creation failed")
        await message.reply_text("Kino saqlanmadi. Qayta urinib ko‘ring.")
        return ConversationHandler.END
    context.user_data.pop("admin_movie_draft", None)
    queue: JobQueue | None = context.application.bot_data.get("queue")
    queued = False
    if created and queue is not None:
        queued = await queue.enqueue(job.id)
    extra = " Reel job navbatga qo‘yildi." if created and queued else " Reel job PostgreSQL’da pending (Redis yo‘q yoki band)."
    if not created:
        extra = " Bu kino uchun Reel job allaqachon mavjud."
    await message.reply_text(f"✅ Kino muvaffaqiyatli saqlandi.{extra}", reply_markup=movie_menu())
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


async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _allowed(update, context): return ConversationHandler.END
    query = update.callback_query
    movie_id = context.user_data.get("admin_delete_movie_id")
    if query is None or movie_id is None or str(movie_id) not in (query.data or ""):
        await query.answer("So‘rov yaroqsiz.", show_alert=True)
        return ConversationHandler.END
    database: Database = context.application.bot_data["database"]
    try:
        async with database.session() as session:
            async with session.begin():
                deleted = await soft_delete_movie(session, movie_id)
    except Exception:
        logger.exception("Movie soft delete failed")
        await query.answer("Xatolik yuz berdi.", show_alert=True)
        return ConversationHandler.END
    await query.answer()
    await query.edit_message_text("✅ Kino faolsizlantirildi." if deleted else "Kino topilmadi yoki avval o‘chirilgan.", reply_markup=movie_menu())
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
    states={SOURCE: [CallbackQueryHandler(choose_video, pattern=r"^adm:movie:video$"), CallbackQueryHandler(choose_url, pattern=r"^adm:movie:url$"), MessageHandler(filters.VIDEO, receive_video), MessageHandler(filters.TEXT & ~filters.COMMAND, receive_url)], CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_code)], TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title)], DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_description)], POSTER: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, finish_movie)]},
    fallbacks=[CallbackQueryHandler(cancel_flow, pattern=rf"^{CANCEL}$")],
    name="admin_movie_add",
)

movie_delete_conversation = ConversationHandler(
    entry_points=[CallbackQueryHandler(begin_delete, pattern=r"^adm:movie:delete$")],
    states={DELETE_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_delete_code)], DELETE_CONFIRM: [CallbackQueryHandler(confirm_delete, pattern=r"^adm:movie:confirm:[0-9a-f-]{36}$")]},
    fallbacks=[CallbackQueryHandler(cancel_flow, pattern=rf"^{CANCEL}$")],
    name="admin_movie_delete",
)
