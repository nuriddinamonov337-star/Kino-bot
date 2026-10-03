"""Admin broadcast conversation: target -> content -> preview -> send.

Content is relayed with ``copy_message`` so text, photo, video, document,
animation and audio are all supported without re-uploading. Delivery uses
``app.services.broadcast`` (rate limiting, RetryAfter handling, per-chat
failure collection).
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.config import parse_integer_list
from app.database.session import Database
from app.handlers.admin_auth import admin_access
from app.keyboards.admin import CANCEL, broadcast_confirm, broadcast_targets, cancel, panel
from app.services.broadcast import (
    BroadcastTarget,
    broadcast_to_chats,
    get_active_user_chat_ids,
    resolve_broadcast_targets,
)
from app.utils.sanitize import sanitize_error

logger = logging.getLogger(__name__)

TARGET, IDS, CONTENT, CONFIRM = range(4)

_TARGET_MAP = {
    "users": BroadcastTarget.USERS,
    "main": BroadcastTarget.MAIN_CHANNEL,
    "reels": BroadcastTarget.REELS_CHANNEL,
    "all": BroadcastTarget.ALL,
}

_CONTENT_FILTER = (
    filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL | filters.ANIMATION | filters.AUDIO
) & ~filters.COMMAND


def _draft(context: ContextTypes.DEFAULT_TYPE) -> dict[str, object]:
    return context.user_data.setdefault("admin_broadcast_draft", {})


async def _allowed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return await admin_access(update, context)


async def begin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _allowed(update, context):
        return ConversationHandler.END
    if update.callback_query:
        await update.callback_query.answer()
        _draft(context).clear()
        await update.callback_query.edit_message_text(
            "📤 Xabar yuborish\n\nQayerga yuboriladi?", reply_markup=broadcast_targets()
        )
    return TARGET


async def choose_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _allowed(update, context):
        return ConversationHandler.END
    query = update.callback_query
    if query is None:
        return TARGET
    await query.answer()
    choice = (query.data or "").rsplit(":", 1)[-1]
    if choice == "custom":
        await query.edit_message_text(
            "📝 Qabul qiluvchilarning Telegram ID'larini vergul bilan yuboring.\nMasalan: 123456789, -1001234567890",
            reply_markup=cancel(),
        )
        return IDS
    if choice not in _TARGET_MAP:
        await query.edit_message_text("Noma'lum yo'nalish.", reply_markup=broadcast_targets())
        return TARGET
    _draft(context)["target"] = choice
    await query.edit_message_text(
        "📎 Endi yuboriladigan xabarni yuboring (matn, rasm, video, fayl, animatsiya).",
        reply_markup=cancel(),
    )
    return CONTENT


async def receive_ids(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _allowed(update, context):
        return ConversationHandler.END
    message = update.effective_message
    if message is None:
        return IDS
    try:
        ids = parse_integer_list(message.text or "")
    except (ValueError, TypeError):
        ids = ()
    if not ids:
        await message.reply_text("Hech qanday to'g'ri ID topilmadi. Vergul bilan ajratib qayta yuboring.")
        return IDS
    _draft(context)["target"] = "custom"
    _draft(context)["custom_ids"] = list(ids)
    await message.reply_text(
        f"📎 {len(ids)} ta manzil qabul qilindi. Endi yuboriladigan xabarni yuboring.",
        reply_markup=cancel(),
    )
    return CONTENT


def _describe(message) -> str:
    if message.text:
        text = message.text[:200]
        return f"📝 Matn: {text}{'...' if len(message.text) > 200 else ''}"
    if message.photo:
        return f"🖼 Rasm{(f' — {message.caption[:100]}' if message.caption else '')}"
    if message.video:
        return f"🎬 Video{(f' — {message.caption[:100]}' if message.caption else '')}"
    if message.document:
        name = getattr(message.document, "file_name", "") or "fayl"
        return f"📄 Hujjat: {name}"
    if message.animation:
        return "🎞 Animatsiya (GIF)"
    if message.audio:
        return "🎵 Audio"
    return "📦 Media xabar"


async def receive_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _allowed(update, context):
        return ConversationHandler.END
    message = update.effective_message
    if message is None:
        return CONTENT
    draft = _draft(context)
    draft["source_chat_id"] = message.chat_id
    draft["source_message_id"] = message.message_id
    await message.reply_text("📋 Ko'rinish:")
    try:
        await context.bot.copy_message(
            chat_id=message.chat_id,
            from_chat_id=message.chat_id,
            message_id=message.message_id,
        )
    except Exception as exc:
        logger.warning("Broadcast preview copy failed: %s", sanitize_error(str(exc)))
        await message.reply_text(_describe(message))
    await message.reply_text(
        f"{_describe(message)}\n\nUshbu xabarni yuborishni tasdiqlaysizmi?",
        reply_markup=broadcast_confirm(),
    )
    return CONFIRM


async def confirm_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _allowed(update, context):
        return ConversationHandler.END
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()
    draft = _draft(context)
    target = str(draft.get("target") or "")
    source_chat = draft.get("source_chat_id")
    source_message = draft.get("source_message_id")
    if not target or source_chat is None or source_message is None:
        await query.edit_message_text("Ma'lumot topilmadi. Qaytadan boshlang.", reply_markup=panel())
        context.user_data.pop("admin_broadcast_draft", None)
        return ConversationHandler.END
    database: Database = context.application.bot_data["database"]
    chat_ids: list[int] = []
    if target == "custom":
        chat_ids = [int(item) for item in draft.get("custom_ids", [])]  # type: ignore[union-attr]
    else:
        from app.config import get_settings

        resolved = resolve_broadcast_targets(get_settings(), _TARGET_MAP[target])
        chat_ids = list(resolved.channel_ids)
        if resolved.include_users:
            try:
                async with database.session() as session:
                    chat_ids += await get_active_user_chat_ids(session)
            except Exception:
                logger.exception("Broadcast user lookup failed")
                await query.edit_message_text("Foydalanuvchilar ro'yxatini olishda xatolik.", reply_markup=panel())
                context.user_data.pop("admin_broadcast_draft", None)
                return ConversationHandler.END
    if not chat_ids:
        await query.edit_message_text(
            "Yuboriladigan manzil topilmadi (kanal sozlanmagan yoki faol user yo'q).",
            reply_markup=panel(),
        )
        context.user_data.pop("admin_broadcast_draft", None)
        return ConversationHandler.END
    await query.edit_message_text(f"⏳ Yuborilmoqda... (0/{len(chat_ids)})")

    def factory(chat_id: int):
        async def send():
            return await context.bot.copy_message(
                chat_id=chat_id,
                from_chat_id=int(source_chat),
                message_id=int(source_message),
            )

        return send

    try:
        report = await broadcast_to_chats(factory, chat_ids, delay_between=0.05, max_attempts=4)
    except Exception:
        logger.exception("Broadcast delivery crashed")
        await query.edit_message_text("❌ Yuborishda kutilmagan xatolik.", reply_markup=panel())
        context.user_data.pop("admin_broadcast_draft", None)
        return ConversationHandler.END
    context.user_data.pop("admin_broadcast_draft", None)
    await query.edit_message_text(
        f"✅ Yuborildi: {report.sent} ta\n❌ Xatolik: {report.failed} ta",
        reply_markup=panel(),
    )
    return ConversationHandler.END


async def cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await _allowed(update, context):
        return ConversationHandler.END
    context.user_data.pop("admin_broadcast_draft", None)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Bekor qilindi.", reply_markup=panel())
    return ConversationHandler.END


broadcast_conversation = ConversationHandler(
    entry_points=[CallbackQueryHandler(begin_broadcast, pattern=r"^adm:broadcast$")],
    states={
        TARGET: [CallbackQueryHandler(choose_target, pattern=r"^adm:broadcast:target:(users|main|reels|all|custom)$")],
        IDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ids)],
        CONTENT: [MessageHandler(_CONTENT_FILTER, receive_content)],
        CONFIRM: [CallbackQueryHandler(confirm_send, pattern=r"^adm:broadcast:send$")],
    },
    fallbacks=[CallbackQueryHandler(cancel_flow, pattern=rf"^{CANCEL}$")],
    name="admin_broadcast",
)