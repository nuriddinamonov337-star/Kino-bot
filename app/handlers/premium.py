"""Manual receipt-based Premium purchase and review handlers."""

import logging
from datetime import UTC
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters

from app.config import get_settings
from app.database.models import PaymentPlan, PaymentStatus
from app.database.session import Database
from app.handlers.admin_auth import admin_access
from app.keyboards.menu import main_menu
from app.keyboards.premium import premium_menu, receipt_keyboard, review_keyboard
from app.services.premium import PendingPaymentExists, attach_receipt, cancel_unsubmitted_payment, create_pending_payment, is_premium_active, plan_details, review_payment
from app.services.users import register_or_update_user

logger = logging.getLogger(__name__)
WAITING_RECEIPT = 1


async def show_premium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message, user = update.effective_message, update.effective_user
    if message is None or user is None: return ConversationHandler.END
    database: Database = context.application.bot_data["database"]
    async with database.session() as session:
        async with session.begin(): db_user = await register_or_update_user(session, user)
    text = "Premium tarifini tanlang:"
    if is_premium_active(db_user): text = f"💎 Sizda Premium faol.\nAmal qilish muddati: {db_user.premium_until.astimezone(UTC):%d.%m.%Y %H:%M}\n\n{text}"
    await message.reply_text(text, reply_markup=premium_menu())
    return WAITING_RECEIPT


async def select_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query, user = update.callback_query, update.effective_user
    if query is None or user is None: return ConversationHandler.END
    await query.answer()
    plan = PaymentPlan.WEEKLY if query.data == "premium:plan:weekly" else PaymentPlan.MONTHLY
    settings, database = get_settings(), context.application.bot_data["database"]
    if settings.card_number is None or not settings.card_owner:
        logger.error("Premium card configuration is missing")
        await query.edit_message_text("Karta ma’lumotlari hali sozlanmagan.")
        return ConversationHandler.END
    try:
        async with database.session() as session:
            async with session.begin():
                db_user = await register_or_update_user(session, user)
                payment = await create_pending_payment(session, db_user, plan, settings)
    except PendingPaymentExists:
        await query.edit_message_text("Sizda hali ko‘rib chiqilmagan Premium to‘lovi bor. Avval uning natijasini kuting.")
        return ConversationHandler.END
    except SQLAlchemyError:
        logger.exception("Premium payment creation failed")
        await query.edit_message_text("To‘lov so‘rovi yaratilmadi. Qayta urinib ko‘ring.")
        return ConversationHandler.END
    context.user_data["premium_payment_id"] = payment.id
    label, amount, _ = plan_details(plan, settings)
    await query.edit_message_text(f"💳 To‘lov uchun:\n\nTarif: {label}\nNarx: {amount:,} so‘m\n\nKarta:\n{settings.card_number.get_secret_value()}\n\nKarta egasi:\n{settings.card_owner}\n\nTo‘lovni amalga oshirgach, chekni shu yerga yuboring.", reply_markup=receipt_keyboard())
    return WAITING_RECEIPT


async def request_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None: return ConversationHandler.END
    await query.answer(); await query.edit_message_text("🧾 Chekni photo yoki document qilib yuboring.", reply_markup=receipt_keyboard())
    return WAITING_RECEIPT


async def receive_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message, user = update.effective_message, update.effective_user
    payment_id = context.user_data.get("premium_payment_id")
    if message is None or user is None or payment_id is None:
        return ConversationHandler.END
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id if message.document else None
    if file_id is None: return WAITING_RECEIPT
    database: Database = context.application.bot_data["database"]
    try:
        async with database.session() as session:
            async with session.begin():
                db_user = await register_or_update_user(session, user)
                payment = await attach_receipt(session, payment_id, db_user.id, file_id)
    except SQLAlchemyError:
        logger.exception("Receipt attachment failed")
        await message.reply_text("Chek saqlanmadi. Qayta yuboring."); return WAITING_RECEIPT
    if payment is None:
        await message.reply_text("To‘lov so‘rovi topilmadi yoki ko‘rib chiqilgan."); return ConversationHandler.END
    await message.reply_text("✅ Chekingiz qabul qilindi. Admin tekshiruvini kuting.", reply_markup=main_menu())
    await notify_admins(context, payment, user, message)
    context.user_data.pop("premium_payment_id", None)
    return ConversationHandler.END


async def notify_admins(context: ContextTypes.DEFAULT_TYPE, payment, user, receipt_message) -> None:
    settings = get_settings(); label, amount, _ = plan_details(payment.plan, settings)
    username = f"@{user.username}" if user.username else "username yo‘q"
    text = f"💳 YANGI PREMIUM TO‘LOV\n\n👤 {user.full_name}\n{username}\nTelegram ID: {user.id}\n\n💎 Tarif: {label}\n💰 Summa: {amount:,} so‘m\n🕐 Vaqt: {payment.created_at.astimezone(UTC):%d.%m.%Y %H:%M UTC}"
    for admin_id in settings.admin_ids:
        try:
            if receipt_message.photo: await context.bot.send_photo(admin_id, receipt_message.photo[-1].file_id, caption=text, reply_markup=review_keyboard(str(payment.id)))
            else: await context.bot.send_document(admin_id, receipt_message.document.file_id, caption=text, reply_markup=review_keyboard(str(payment.id)))
        except TelegramError:
            logger.exception("Premium payment notification failed for admin %s", admin_id)


async def review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await admin_access(update, context): return
    query = update.callback_query
    if query is None: return
    parts = (query.data or "").split(":")
    try: action, payment_id = parts[1], UUID(parts[2])
    except (IndexError, ValueError): await query.answer("Noto‘g‘ri to‘lov so‘rovi.", show_alert=True); return
    database: Database = context.application.bot_data["database"]
    try:
        async with database.session() as session:
            async with session.begin(): payment = await review_payment(session, payment_id, update.effective_user.id, action == "approve")
    except SQLAlchemyError:
        logger.exception("Premium review failed"); await query.answer("To‘lov yangilanmadi.", show_alert=True); return
    if payment is None:
        await query.answer("Bu to‘lov allaqachon ko‘rib chiqilgan.", show_alert=True); return
    await query.answer("To‘lov tasdiqlandi." if action == "approve" else "To‘lov rad etildi.")
    try:
        if action == "approve": await context.bot.send_message(payment.user.telegram_id, f"✅ To‘lov tasdiqlandi!\n\n💎 Premium faollashtirildi.\n📅 Amal qilish muddati: {payment.user.premium_until.astimezone(UTC):%d.%m.%Y %H:%M}\n\nRahmat!")
        else: await context.bot.send_message(payment.user.telegram_id, "❌ Premium to‘lovingiz rad etildi.\n\nAgar xato bo‘lgan deb hisoblasangiz, admin bilan bog‘laning.")
    except TelegramError:
        logger.exception("Could not notify Premium payment user")
    await query.edit_message_reply_markup(reply_markup=None)


async def cancel_premium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    payment_id, user = context.user_data.pop("premium_payment_id", None), update.effective_user
    if payment_id and user:
        database: Database = context.application.bot_data["database"]
        async with database.session() as session:
            async with session.begin():
                from app.services.users import register_or_update_user
                db_user = await register_or_update_user(session, user)
                await cancel_unsubmitted_payment(session, payment_id, db_user.id)
    if query: await query.answer(); await query.edit_message_text("Bekor qilindi.")
    return ConversationHandler.END


premium_conversation = ConversationHandler(entry_points=[MessageHandler(filters.Regex(r"^💎 Premium$"), show_premium)], states={WAITING_RECEIPT: [CallbackQueryHandler(select_plan, pattern=r"^premium:plan:(weekly|monthly)$"), CallbackQueryHandler(request_receipt, pattern=r"^premium:receipt$"), MessageHandler(filters.PHOTO | filters.Document.ALL, receive_receipt)]}, fallbacks=[CallbackQueryHandler(cancel_premium, pattern=r"^premium:(cancel|back)$")], name="premium_purchase")
