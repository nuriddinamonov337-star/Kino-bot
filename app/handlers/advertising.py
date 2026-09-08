"""User advertising request ConversationHandler."""

from __future__ import annotations

import logging

from sqlalchemy.exc import SQLAlchemyError
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from app.config import get_settings
from app.database.models import AdvertisingType
from app.database.session import Database
from app.handlers.access import grant_or_request_subscription
from app.keyboards.advertising import advertising_menu, cancel
from app.keyboards.menu import main_menu
from app.services.advertising import (
    create_advertising_request,
    get_contact_handle,
    validate_details,
    validate_http_link,
    validate_target_count,
)
from app.services.users import register_or_update_user

logger = logging.getLogger(__name__)

CHOOSE_TYPE, TITLE, LINK, COUNT, DETAILS = range(5)

TYPE_BY_DATA = {
    "ad:type:subscribers": AdvertisingType.SUBSCRIBERS,
    "ad:type:bot": AdvertisingType.BOT,
    "ad:type:channels": AdvertisingType.CHANNELS,
    "ad:type:contact": AdvertisingType.CONTACT,
}


def _draft(context: ContextTypes.DEFAULT_TYPE) -> dict[str, object]:
    return context.user_data.setdefault("ad_draft", {})


async def begin_advertising(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await grant_or_request_subscription(update, context):
        return ConversationHandler.END
    message = update.effective_message
    if message is None:
        return ConversationHandler.END
    await message.reply_text(
        "📢 Reklama\n\nTo‘lov avtomatik emas. So‘rov yuboring — admin ko‘rib chiqadi.",
        reply_markup=advertising_menu(),
    )
    return CHOOSE_TYPE


async def choose_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()
    ad_type = TYPE_BY_DATA.get(query.data or "")
    if ad_type is None:
        return ConversationHandler.END
    draft = _draft(context)
    draft.clear()
    draft["ad_type"] = ad_type
    settings = get_settings()
    if ad_type is AdvertisingType.SUBSCRIBERS:
        await query.edit_message_text(
            f"📢 Obunachi yig‘ish\n\nKanal auditoriyasini kengaytirish xizmati. Avtomatik to‘lov qilinmaydi, so‘rov admin tomonidan ko‘rib chiqiladi.\n\n100 ta — {settings.subscriber_100_price:,} so‘m\n500 ta — {settings.subscriber_500_price:,} so‘m\n1000 ta — {settings.subscriber_1000_price:,} so‘m\n\nKanal nomini yuboring (255 belgigacha).",
            reply_markup=cancel(),
        )
        return TITLE
    if ad_type is AdvertisingType.CHANNELS:
        await query.edit_message_text(
            "📡 Kanallarda reklama\n\nReklamangiz hamkor kanallarda joylashtiriladi. Narx kanal, auditoriya va joylashtirish muddatiga qarab admin tomonidan belgilanadi. So‘rov adminlarga yuboriladi.\n\nReklama qilinadigan kanal nomini yuboring.",
            reply_markup=cancel(),
        )
        return TITLE
    if ad_type is AdvertisingType.CONTACT:
        contact = get_contact_handle(settings.admin_username)
        body = (
            "👨‍💻 Admin bilan bog‘lanish\n\n"
            f"Admin bilan bog‘lanish uchun: {contact or 'admin kontakt ma’lum emas'}\n\n"
            "Yoki quyidagi xabarni yuboring va adminga so‘rov jo‘natilsin."
        )
        await query.edit_message_text(body, reply_markup=cancel())
        return DETAILS
    await query.edit_message_text(
        f"📣 Botda reklama\n\nBot ichida reklama joylashtirish xizmati. Narx reklama hajmi va muddatiga qarab admin tomonidan belgilanadi.\n\nBotda reklama matnini yuboring (5–2000 belgi).",
        reply_markup=cancel(),
    )
    return DETAILS


async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    title = (message.text or "").strip() if message else ""
    if not title or len(title) > 255:
        if message:
            await message.reply_text("Nom 1–255 belgi bo‘lishi kerak.")
        return TITLE
    _draft(context)["channel_title"] = title
    await message.reply_text("Kanal linkini yuboring (https://t.me/...).", reply_markup=cancel())
    return LINK


async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    value = (message.text or "").strip() if message else ""
    try:
        link = validate_http_link(value)
    except ValueError as exc:
        await message.reply_text(str(exc))
        return LINK
    _draft(context)["channel_link"] = link
    if _draft(context)["ad_type"] is AdvertisingType.SUBSCRIBERS:
        await message.reply_text("Kerakli obunachi sonini yuboring.", reply_markup=cancel())
        return COUNT
    await message.reply_text("Reklama tafsilotlarini yuboring (5–2000 belgi).", reply_markup=cancel())
    return DETAILS


async def receive_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    try:
        count = validate_target_count(message.text or "")
    except ValueError as exc:
        await message.reply_text(str(exc))
        return COUNT
    _draft(context)["target_count"] = count
    await message.reply_text("Qo‘shimcha izoh yuboring (5–2000 belgi).", reply_markup=cancel())
    return DETAILS


async def receive_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message, user = update.effective_message, update.effective_user
    if message is None or user is None:
        return ConversationHandler.END
    try:
        details = validate_details(message.text or "")
    except ValueError as exc:
        await message.reply_text(str(exc))
        return DETAILS
    draft = _draft(context)
    ad_type: AdvertisingType = draft["ad_type"]  # type: ignore[assignment]
    database: Database = context.application.bot_data["database"]
    try:
        async with database.session() as session:
            async with session.begin():
                db_user = await register_or_update_user(session, user)
                request = await create_advertising_request(
                    session,
                    db_user,
                    ad_type=ad_type,
                    details=details,
                    channel_title=str(draft.get("channel_title") or "") or None,
                    channel_link=str(draft.get("channel_link") or "") or None,
                    target_count=int(draft["target_count"]) if "target_count" in draft else None,
                )
    except SQLAlchemyError:
        logger.exception("Advertising request save failed")
        await message.reply_text("So‘rov saqlanmadi. Qayta urinib ko‘ring.")
        return ConversationHandler.END
    context.user_data.pop("ad_draft", None)
    await message.reply_text(
        "✅ So‘rovingiz qabul qilindi. Admin tez orada bog‘lanadi. Avtomatik to‘lov yo‘q.",
        reply_markup=main_menu(),
    )
    await _notify_admins(context, user, ad_type, details, str(request.id))
    return ConversationHandler.END


async def _notify_admins(context: ContextTypes.DEFAULT_TYPE, user, ad_type: AdvertisingType, details: str, request_id: str) -> None:
    username = f"@{user.username}" if user.username else "username yo‘q"
    text = (
        f"📣 YANGI REKLAMA SO‘ROVI\n\n"
        f"Turi: {ad_type.value}\n"
        f"👤 {user.full_name}\n{username}\nID: {user.id}\n"
        f"So‘rov: {request_id}\n\n{details[:1500]}"
    )
    for admin_id in get_settings().admin_ids:
        try:
            await context.bot.send_message(admin_id, text)
        except TelegramError:
            logger.exception("Advertising notification failed for admin %s", admin_id)


async def cancel_advertising(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("ad_draft", None)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Bekor qilindi.")
    elif update.effective_message:
        await update.effective_message.reply_text("Bekor qilindi.", reply_markup=main_menu())
    return ConversationHandler.END


advertising_conversation = ConversationHandler(
    entry_points=[MessageHandler(filters.Regex(r"^📢 Reklama$"), begin_advertising)],
    states={
        CHOOSE_TYPE: [CallbackQueryHandler(choose_type, pattern=r"^ad:type:(subscribers|bot|channels|contact)$")],
        TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title)],
        LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
        COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_count)],
        DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_details)],
    },
    fallbacks=[CallbackQueryHandler(cancel_advertising, pattern=r"^ad:cancel$")],
    name="advertising_request",
)
