"""Protected mandatory-channel create/delete conversations and the
subscriber-growth campaign flow (§13)."""

import logging
from urllib.parse import urlparse

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from app.config import get_settings
from app.database.session import Database
from app.handlers.admin_auth import admin_access
from app.keyboards.admin import CANCEL, cancel, channel_menu, confirm_channel_delete
from app.keyboards.advertising import subscriber_cancel, subscriber_package_menu
from app.services.admin import (
    create_mandatory_channel,
    get_active_channel,
    soft_delete_channel,
    start_channel_campaign,
)

logger = logging.getLogger(__name__)
IDENTIFIER, CHANNEL_TITLE, INVITE = range(3)
DELETE_IDENTIFIER, DELETE_CONFIRM = range(10, 12)
# Subscriber-growth campaign states
SUB_PACKAGE, SUB_CHANNEL = range(20, 22)


def _valid_identifier(value: str) -> bool:
    return value.startswith("@") and len(value) <= 256 or value.lstrip("-").isdigit()


def _subscriber_prices() -> dict[int, int]:
    settings = get_settings()
    return {
        100: settings.mandatory_100_price,
        500: settings.mandatory_500_price,
        1000: settings.mandatory_1000_price,
    }


# --------------------------------------------------------------------------- #
# Add / delete mandatory channel
# --------------------------------------------------------------------------- #
async def begin_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await admin_access(update, context): return ConversationHandler.END
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("➕ Kanalning chat_id yoki @username qiymatini yuboring. Bot kanalga admin qilib qo‘shilgan bo‘lishi kerak.", reply_markup=cancel())
    return IDENTIFIER


async def channel_identifier(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await admin_access(update, context): return ConversationHandler.END
    message, value = update.effective_message, (update.effective_message.text or "").strip()
    if not _valid_identifier(value):
        await message.reply_text("chat_id raqam yoki @username yuboring.")
        return IDENTIFIER
    try:
        chat = await context.bot.get_chat(value if value.startswith("@") else int(value))
        bot_user = await context.bot.get_me()
        bot_member = await context.bot.get_chat_member(chat.id, bot_user.id)
    except TelegramError:
        await message.reply_text("Kanal topilmadi yoki botning kanalni tekshirish huquqi yo‘q. Bot kanalga admin qilib qo‘shilganini tekshiring.")
        return IDENTIFIER
    bot_status = getattr(bot_member.status, "value", bot_member.status)
    if str(bot_status).lower() not in {"administrator", "creator", "owner"}:
        await message.reply_text("Bot kanalga admin qilib qo‘shilmagan. Avval botga admin huquqini bering.")
        return IDENTIFIER
    context.user_data["admin_channel_draft"] = {"chat_id": chat.id, "username": (chat.username or value.lstrip("@")) if value.startswith("@") else chat.username}
    await message.reply_text("Kanal nomini yuboring. (255 belgigacha)", reply_markup=cancel())
    return CHANNEL_TITLE


async def channel_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await admin_access(update, context): return ConversationHandler.END
    message, value = update.effective_message, (update.effective_message.text or "").strip()
    if not value or len(value) > 255:
        await message.reply_text("Nom 1–255 belgi bo‘lishi kerak.")
        return CHANNEL_TITLE
    context.user_data["admin_channel_draft"]["title"] = value
    await message.reply_text("Invite URL yuboring yoki '-' yuboring.", reply_markup=cancel())
    return INVITE


async def finish_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await admin_access(update, context): return ConversationHandler.END
    message, value = update.effective_message, (update.effective_message.text or "").strip()
    if value != "-" and (urlparse(value).scheme not in {"http", "https"} or not urlparse(value).netloc):
        await message.reply_text("Invite URL http/https bo‘lishi yoki '-' bo‘lishi kerak.")
        return INVITE
    draft = context.user_data["admin_channel_draft"]
    draft["invite_url"] = None if value == "-" else value
    database: Database = context.application.bot_data["database"]
    try:
        async with database.session() as session:
            async with session.begin(): await create_mandatory_channel(session, **draft)
    except Exception:
        logger.exception("Mandatory channel creation failed")
        await message.reply_text("Kanal saqlanmadi. Qayta urinib ko‘ring.")
        return ConversationHandler.END
    context.user_data.pop("admin_channel_draft", None)
    await message.reply_text("✅ Kanal saqlandi. Bot ushbu kanalda admin bo‘lib qolishi kerak.", reply_markup=channel_menu())
    return ConversationHandler.END


async def begin_delete_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await admin_access(update, context): return ConversationHandler.END
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("🗑 O‘chirish uchun chat_id yoki @username yuboring.", reply_markup=cancel())
    return DELETE_IDENTIFIER


async def receive_delete_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await admin_access(update, context): return ConversationHandler.END
    message, value = update.effective_message, (update.effective_message.text or "").strip()
    if not _valid_identifier(value):
        await message.reply_text("chat_id raqam yoki @username yuboring."); return DELETE_IDENTIFIER
    database: Database = context.application.bot_data["database"]
    async with database.session() as session: channel = await get_active_channel(session, value)
    if channel is None:
        await message.reply_text("Faol kanal topilmadi."); return DELETE_IDENTIFIER
    context.user_data["admin_delete_channel_id"] = channel.id
    await message.reply_text(f"📢 {channel.title}\nHaqiqatan o‘chirasizmi?", reply_markup=confirm_channel_delete(channel.id))
    return DELETE_CONFIRM


async def confirm_channel_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await admin_access(update, context): return ConversationHandler.END
    query, channel_id = update.callback_query, context.user_data.get("admin_delete_channel_id")
    if query is None or channel_id is None or str(channel_id) not in (query.data or ""):
        return ConversationHandler.END
    database: Database = context.application.bot_data["database"]
    try:
        async with database.session() as session:
            async with session.begin(): deleted = await soft_delete_channel(session, channel_id)
    except Exception:
        logger.exception("Mandatory channel soft delete failed")
        await query.answer("Xatolik yuz berdi.", show_alert=True); return ConversationHandler.END
    await query.answer(); await query.edit_message_text("✅ Kanal faolsizlantirildi." if deleted else "Kanal topilmadi.", reply_markup=channel_menu())
    return ConversationHandler.END


async def cancel_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await admin_access(update, context): return ConversationHandler.END
    if update.callback_query:
        await update.callback_query.answer(); await update.callback_query.edit_message_text("Bekor qilindi.", reply_markup=channel_menu())
    return ConversationHandler.END


# --------------------------------------------------------------------------- #
# §13 — Subscriber-growth campaign (admin flow)
# --------------------------------------------------------------------------- #
async def begin_subscriber_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Admin picks a subscriber package."""
    if not await admin_access(update, context): return ConversationHandler.END
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()
    context.user_data.pop("sub_campaign", None)
    await query.edit_message_text(
        "📣 Majburiy kanal qo‘shish\n\nKerakli paketni tanlang:",
        reply_markup=subscriber_package_menu(_subscriber_prices()),
    )
    return SUB_PACKAGE


async def choose_subscriber_package(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await admin_access(update, context): return ConversationHandler.END
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()
    try:
        target = int((query.data or "").rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return ConversationHandler.END
    prices = _subscriber_prices()
    if target not in prices:
        return ConversationHandler.END
    context.user_data["sub_campaign"] = {"target": target, "price": prices[target]}
    await query.edit_message_text(
        f"📣 {target} ta obunachi — {prices[target]:,} so'm\n\n"
        "Endi kanal/guruh username yoki linkini yuboring.\n\n"
        "Misol: @kanal yoki https://t.me/kanal yoki -1001234567890\n\n"
        "MUHIM: Bot kanalda ADMIN bo‘lishi shart!",
        reply_markup=subscriber_cancel(),
    )
    return SUB_CHANNEL


async def receive_subscriber_channel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await admin_access(update, context): return ConversationHandler.END
    message = update.effective_message
    if message is None:
        return SUB_CHANNEL
    value = (message.text or "").strip()
    draft = context.user_data.get("sub_campaign")
    if not draft:
        return ConversationHandler.END
    # Resolve the channel identifier (username, t.me link or numeric id).
    identifier: str | int = value
    if value.startswith("https://t.me/") or value.startswith("http://t.me/"):
        identifier = "@" + value.rstrip("/").rsplit("/", 1)[-1]
    elif value.startswith("t.me/"):
        identifier = "@" + value.rstrip("/").rsplit("/", 1)[-1]
    elif value.startswith("@"):
        identifier = value
    elif value.lstrip("-").isdigit():
        identifier = int(value)
    else:
        await message.reply_text(
            "Kanal topilmadi. @username, https://t.me/... yoki -100... ko‘rinishida yuboring.",
            reply_markup=subscriber_cancel(),
        )
        return SUB_CHANNEL
    try:
        chat = await context.bot.get_chat(identifier)
        bot_user = await context.bot.get_me()
        bot_member = await context.bot.get_chat_member(chat.id, bot_user.id)
    except TelegramError:
        await message.reply_text(
            "❌ Xatolik: kanal topilmadi yoki botning tekshirish huquqi yo‘q.\n\n"
            "Iltimos, botni kanalga admin qilib, qayta urinib ko‘ring.",
            reply_markup=subscriber_cancel(),
        )
        return SUB_CHANNEL
    bot_status = getattr(bot_member.status, "value", bot_member.status)
    if str(bot_status).lower() not in {"administrator", "creator", "owner"}:
        await message.reply_text(
            "❌ Xatolik: bot kanalga admin qilib qo‘shilmagan.\n\n"
            "Iltimos, botni kanalga admin qilib, qayta urinib ko‘ring.",
            reply_markup=subscriber_cancel(),
        )
        return SUB_CHANNEL
    database: Database = context.application.bot_data["database"]
    try:
        async with database.session() as session:
            async with session.begin():
                channel = await start_channel_campaign(
                    session,
                    chat_id=chat.id,
                    title=chat.title or chat.username or str(chat.id),
                    username=chat.username,
                    invite_url=None,
                    target=int(draft["target"]),
                    price=int(draft["price"]),
                )
                title, chat_id, username = channel.title, channel.chat_id, channel.username
    except Exception:
        logger.exception("Subscriber campaign creation failed")
        await message.reply_text("Kanal saqlanmadi. Qayta urinib ko‘ring.", reply_markup=channel_menu())
        return ConversationHandler.END
    context.user_data.pop("sub_campaign", None)
    username_text = f"@{username}" if username else "—"
    await message.reply_text(
        "✅ Majburiy kanal qo‘shildi!\n\n"
        f"📣 Kanal: {title}\n"
        f"🆔 ID: {chat_id}\n"
        f"🔗 Username: {username_text}\n"
        f"🎯 Maqsad: {draft['target']} ta obunachi\n"
        f"💰 Narx: {int(draft['price']):,} so'm\n\n"
        "Endi bot yangi foydalanuvchilarni hisoblaydi.\n"
        f"{draft['target']} taga yetganda kampaniya avtomatik tugaydi.",
        reply_markup=channel_menu(),
    )
    return ConversationHandler.END


async def cancel_subscriber_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await admin_access(update, context): return ConversationHandler.END
    context.user_data.pop("sub_campaign", None)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Bekor qilindi.", reply_markup=channel_menu())
    return ConversationHandler.END


channel_conversation = ConversationHandler(entry_points=[CallbackQueryHandler(begin_add_channel, pattern=r"^adm:channel:add$")], states={IDENTIFIER: [MessageHandler(filters.TEXT & ~filters.COMMAND, channel_identifier)], CHANNEL_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, channel_title)], INVITE: [MessageHandler(filters.TEXT & ~filters.COMMAND, finish_channel)]}, fallbacks=[CallbackQueryHandler(cancel_channel, pattern=rf"^{CANCEL}$")], name="admin_channel_add")
channel_delete_conversation = ConversationHandler(entry_points=[CallbackQueryHandler(begin_delete_channel, pattern=r"^adm:channel:delete$")], states={DELETE_IDENTIFIER: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_delete_channel)], DELETE_CONFIRM: [CallbackQueryHandler(confirm_channel_delete, pattern=r"^adm:channel:confirm:[0-9a-f-]{36}$")]}, fallbacks=[CallbackQueryHandler(cancel_channel, pattern=rf"^{CANCEL}$")], name="admin_channel_delete")
subscriber_campaign_conversation = ConversationHandler(
    entry_points=[CallbackQueryHandler(begin_subscriber_campaign, pattern=r"^adm:sub:add$")],
    states={
        SUB_PACKAGE: [CallbackQueryHandler(choose_subscriber_package, pattern=r"^adm:sub:pkg:(100|500|1000)$")],
        SUB_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_subscriber_channel)],
    },
    fallbacks=[CallbackQueryHandler(cancel_subscriber_campaign, pattern=r"^adm:sub:cancel$")],
    name="admin_subscriber_campaign",
)
