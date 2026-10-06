"""User advertising ConversationHandler (§12).

Flow:
1. "📢 Reklama" → choose tariff (week/month).
2. Confirm tariff → send ad content (video/photo/document + caption).
3. Preview → confirm → pay (card details) → send receipt.
4. Receipt is forwarded to admins with approve/reject buttons.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import SQLAlchemyError
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.config import get_settings
from app.database.models import AdTariff
from app.database.session import Database
from app.handlers.access import grant_or_request_subscription
from app.keyboards.advertising import (
    admin_review,
    cancel,
    preview_confirm,
    tariff_confirm,
    tariff_menu,
)
from app.keyboards import main_menu
from app.services.advertising import (
    attach_receipt,
    create_ad_campaign,
    detect_content_type,
    extract_file_id,
    set_admin_message_id,
    tariff_duration_days,
    tariff_label,
    tariff_price,
    tariff_times_per_day,
    tariff_total_posts,
)
from app.services.users import register_or_update_user

logger = logging.getLogger(__name__)

CHOOSE_TARIFF, CONFIRM_TARIFF, RECEIVE_CONTENT, PREVIEW, RECEIVE_RECEIPT = range(5)

TARIFF_BY_DATA = {
    "ad:tariff:week": AdTariff.WEEK,
    "ad:tariff:month": AdTariff.MONTH,
}


def _draft(context: ContextTypes.DEFAULT_TYPE) -> dict[str, object]:
    return context.user_data.setdefault("ad_draft", {})


def _tariff_summary(tariff: AdTariff) -> str:
    settings = get_settings()
    return (
        f"📢 {tariff_label(tariff)} — {tariff_price(tariff, settings):,} so'm\n\n"
        f"⏱ Muddat: {tariff_duration_days(tariff)} kun\n"
        f"📊 Kuniga: {tariff_times_per_day(tariff, settings)} mahal\n"
        f"🔢 Jami: {tariff_total_posts(tariff, settings)} marta"
    )


async def begin_advertising(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await grant_or_request_subscription(update, context):
        return ConversationHandler.END
    message = update.effective_message
    if message is None:
        return ConversationHandler.END
    context.user_data.pop("ad_draft", None)
    settings = get_settings()
    await message.reply_text(
        "📢 Reklama berish\n\nReklama muddati va narxini tanlang:",
        reply_markup=tariff_menu(settings.reklama_week_price, settings.reklama_month_price),
    )
    return CHOOSE_TARIFF


async def choose_tariff(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()
    tariff = TARIFF_BY_DATA.get(query.data or "")
    if tariff is None:
        return ConversationHandler.END
    draft = _draft(context)
    draft.clear()
    draft["tariff"] = tariff
    await query.edit_message_text(_tariff_summary(tariff), reply_markup=tariff_confirm())
    return CONFIRM_TARIFF


async def confirm_tariff(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()
    if (query.data or "") != "ad:continue":
        return ConversationHandler.END
    await query.edit_message_text(
        "📢 Reklamani kiriting:\n\n"
        "Video, rasm, PDF yoki boshqa fayl yuborishingiz mumkin.\n"
        "Reklama matnini ham yuboring (caption yoki alohida xabar).",
        reply_markup=cancel(),
    )
    return RECEIVE_CONTENT


async def receive_content(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    if message is None:
        return RECEIVE_CONTENT
    content_type = detect_content_type(message)
    if content_type is None:
        await message.reply_text(
            "Iltimos, video, rasm yoki fayl (document) yuboring.",
            reply_markup=cancel(),
        )
        return RECEIVE_CONTENT
    file_id = extract_file_id(message, content_type)
    if not file_id:
        await message.reply_text("Fayl aniqlanmadi. Qayta yuboring.", reply_markup=cancel())
        return RECEIVE_CONTENT
    draft = _draft(context)
    draft["content_type"] = content_type
    draft["file_id"] = file_id
    draft["caption"] = message.caption
    tariff: AdTariff = draft["tariff"]  # type: ignore[assignment]
    settings = get_settings()
    caption_text = message.caption or "(matn yo‘q)"
    await message.reply_text(
        "📢 Sizning reklamangiz\n\n"
        f"📝 Matn: {caption_text}\n"
        f"⏱ Muddat: {tariff_label(tariff)}\n"
        f"💰 Narxi: {tariff_price(tariff, settings):,} so'm\n"
        f"📊 Kuniga: {tariff_times_per_day(tariff, settings)} marta\n"
        f"🔢 Jami: {tariff_total_posts(tariff, settings)} marta",
        reply_markup=preview_confirm(),
    )
    return PREVIEW


async def confirm_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()
    if (query.data or "") != "ad:confirm":
        return ConversationHandler.END
    draft = _draft(context)
    tariff: AdTariff = draft["tariff"]  # type: ignore[assignment]
    settings = get_settings()
    card = settings.card_number.get_secret_value() if settings.card_number else "—"
    owner = settings.card_owner or "—"
    await query.edit_message_text(
        "💳 To‘lovni amalga oshiring.\n\n"
        f"Karta: {card}\n"
        f"Karta egasi: {owner}\n"
        f"Summa: {tariff_price(tariff, settings):,} so'm\n\n"
        "To‘lovni amalga oshirgach, chekni yuboring.",
        reply_markup=cancel(),
    )
    return RECEIVE_RECEIPT


async def receive_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message, user = update.effective_message, update.effective_user
    if message is None or user is None:
        return ConversationHandler.END
    if not message.photo:
        await message.reply_text("Iltimos, to‘lov chekini rasm sifatida yuboring.", reply_markup=cancel())
        return RECEIVE_RECEIPT
    draft = _draft(context)
    tariff: AdTariff = draft["tariff"]  # type: ignore[assignment]
    settings = get_settings()
    database: Database = context.application.bot_data["database"]
    try:
        async with database.session() as session:
            async with session.begin():
                db_user = await register_or_update_user(session, user)
                campaign = await create_ad_campaign(
                    session,
                    db_user,
                    tariff=tariff,
                    content_type=draft["content_type"],  # type: ignore[arg-type]
                    file_id=str(draft["file_id"]),
                    caption=draft.get("caption"),  # type: ignore[arg-type]
                    settings=settings,
                )
                await attach_receipt(session, campaign.id, message.photo[-1].file_id)
                campaign_id = campaign.id
    except SQLAlchemyError:
        logger.exception("Advertising campaign save failed")
        await message.reply_text("So‘rov saqlanmadi. Qayta urinib ko‘ring.")
        return ConversationHandler.END
    context.user_data.pop("ad_draft", None)
    await message.reply_text(
        "✅ So‘rovingiz qabul qilindi. Admin tez orada ko‘rib chiqadi.",
        reply_markup=main_menu(),
    )
    await _notify_admins(context, user, campaign_id, draft, message.photo[-1].file_id)
    return ConversationHandler.END


async def _notify_admins(
    context: ContextTypes.DEFAULT_TYPE,
    user,
    campaign_id: int,
    draft: dict[str, object],
    receipt_file_id: str,
) -> None:
    tariff: AdTariff = draft["tariff"]  # type: ignore[assignment]
    settings = get_settings()
    username = f"@{user.username}" if user.username else "username yo‘q"
    caption_text = draft.get("caption") or "(matn yo‘q)"
    text = (
        "📢 Yangi reklama buyurtmasi\n\n"
        f"👤 User: {username}\n"
        f"🆔 ID: {user.id}\n"
        f"📦 Tarif: {tariff_label(tariff)}\n"
        f"💰 Narxi: {tariff_price(tariff, settings):,} so'm\n"
        f"📊 Kuniga: {tariff_times_per_day(tariff, settings)} marta\n"
        f"🔢 Jami: {tariff_total_posts(tariff, settings)} marta\n\n"
        f"📝 Matn: {caption_text}"
    )
    database: Database = context.application.bot_data["database"]
    for admin_id in settings.admin_ids:
        try:
            await context.bot.send_message(admin_id, text)
            await context.bot.send_photo(admin_id, receipt_file_id, caption="🧾 To‘lov cheki")
            sent = await context.bot.send_message(
                admin_id,
                "Reklamani tasdiqlaysizmi?",
                reply_markup=admin_review(campaign_id),
            )
            async with database.session() as session:
                async with session.begin():
                    await set_admin_message_id(session, campaign_id, sent.message_id)
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
        CHOOSE_TARIFF: [CallbackQueryHandler(choose_tariff, pattern=r"^ad:tariff:(week|month)$")],
        CONFIRM_TARIFF: [CallbackQueryHandler(confirm_tariff, pattern=r"^ad:continue$")],
        RECEIVE_CONTENT: [
            MessageHandler(filters.VIDEO | filters.PHOTO | filters.Document.ALL, receive_content)
        ],
        PREVIEW: [CallbackQueryHandler(confirm_preview, pattern=r"^ad:confirm$")],
        RECEIVE_RECEIPT: [MessageHandler(filters.PHOTO, receive_receipt)],
    },
    fallbacks=[CallbackQueryHandler(cancel_advertising, pattern=r"^ad:cancel$")],
    name="advertising_request",
)
