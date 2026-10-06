"""Admin dashboard callbacks that are not part of a data-entry conversation."""

import logging
from datetime import UTC, datetime

from telegram import Update
from telegram.ext import ContextTypes

from app.config import get_settings
from app.database.models import PaymentStatus
from app.database.session import Database
from app.handlers.admin_auth import admin_only
from app.keyboards.admin import admin_menu, channel_menu, movie_list, movie_menu, panel, payment_list_menu, payment_menu
from app.services.admin import (
    add_database_admin,
    dashboard_statistics,
    list_channels,
    list_database_admins,
    list_movies,
    remove_database_admin,
)
from app.services.premium import list_payments

logger = logging.getLogger(__name__)


async def _edit(update: Update, text: str, **kwargs: object) -> None:
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(text, **kwargs)
    elif update.effective_message:
        await update.effective_message.reply_text(text, **kwargs)


@admin_only
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _edit(update, "👨‍💼 Admin panel", reply_markup=panel())


@admin_only
async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    data = query.data or ""
    database: Database = context.application.bot_data["database"]
    if data == "adm:main":
        await _edit(update, "👨‍💼 Admin panel", reply_markup=panel())
    elif data == "adm:movies":
        await _edit(update, "🎬 Kino boshqaruvi", reply_markup=movie_menu())
    elif data == "adm:channels":
        await _edit(update, "📢 Majburiy kanallar\n\nBot kanallarni tekshirishi uchun kanalga admin qilib qo‘shilgan bo‘lishi kerak.", reply_markup=channel_menu())
    elif data == "adm:payments":
        await _edit(update, "💳 Premium to'lovlar", reply_markup=payment_menu())
    elif data.startswith("adm:payments:"):
        _, _, kind, page_text = data.split(":")
        page = max(0, int(page_text))
        async with database.session() as session:
            payments, total = await list_payments(session, PaymentStatus.PENDING if kind == "pending" else None, page)
        lines = [f"{'⏳ Kutilayotgan' if kind == 'pending' else '📋 To‘lovlar tarixi'} ({total} ta)"]
        lines += [f"{payment.user.telegram_id} | {payment.plan} | {payment.amount:,} so'm | {payment.status}" for payment in payments]
        await _edit(update, "\n".join(lines) if payments else "To‘lovlar topilmadi.", reply_markup=payment_list_menu(kind, page, total))
    elif data.startswith("adm:movie:list:"):
        page = max(0, int(data.rsplit(":", 1)[1]))
        async with database.session() as session:
            movies, total = await list_movies(session, page)
        lines = [f"📋 Kinolar ({total} ta)"] + [f"{'🟢' if movie.is_active else '⚫'} {movie.code} — {movie.title}" for movie in movies]
        await _edit(update, "\n".join(lines) if movies else "📋 Kinolar topilmadi.", reply_markup=movie_list(movies, page, total))
    elif data == "adm:channel:list":
        async with database.session() as session:
            channels = await list_channels(session)
        text = "📋 Kanallar\n" + ("\n".join(f"{'🟢' if item.is_active else '⚫'} {item.title} — {item.username or item.chat_id}" for item in channels) if channels else "Kanallar yo‘q.")
        await _edit(update, text, reply_markup=channel_menu())
    elif data in {"adm:users", "adm:stats"}:
        async with database.session() as session:
            stats = await dashboard_statistics(session)
        if data == "adm:users":
            text = (
                "👥 Foydalanuvchilar\n\n"
                f"👥 Jami: {stats['users']}\n"
                f"🟢 Faol: {stats['active_users']}\n"
                f"💎 Premium: {stats['premium_users']}"
            )
        else:
            started = context.application.bot_data.get("started_at")
            started_text = f"\n\n🤖 Bot ishga tushgan: {started.astimezone(UTC):%Y-%m-%d %H:%M UTC}" if started else ""
            text = (
                "📊 To‘liq statistika\n\n"
                f"👥 Foydalanuvchilar: {stats['users']} (faol: {stats['active_users']}, premium: {stats['premium_users']})\n"
                f"🎬 Kinolar: {stats['movies']} (faol: {stats['active_movies']})\n"
                f"📢 Majburiy kanallar: {stats['active_channels']}\n"
                f"🎞 Reels: {stats['reels']}\n"
                f"⚙️ Reel joblar: {stats['reel_jobs']} (kutilmoqda: {stats['pending_jobs']}, xato: {stats['failed_jobs']})\n"
                f"💳 To‘lovlar: {stats['approved_payments']} tasdiqlangan, {stats['pending_payments']} kutilmoqda\n"
                f"💰 Tushum: {stats['revenue']:,} so'm\n"
                f"📣 Reklama so‘rovlari: {stats['ad_requests']} (kutilmoqda: {stats['pending_ads']})"
                f"{started_text}"
            )
        await _edit(update, text, reply_markup=panel())
    elif data == "adm:admins":
        async with database.session() as session:
            db_admins = await list_database_admins(session)
        configured = ", ".join(map(str, get_settings().admin_ids)) or "yo‘q"
        stored = ", ".join(str(admin.telegram_id) for admin in db_admins) or "yo‘q"
        await _edit(
            update,
            f"👨‍💼 Adminlar\n\nConfig ADMIN_IDS: {configured}\nDatabase: {stored}",
            reply_markup=admin_menu(),
        )
    elif data == "adm:admin:add":
        context.user_data["admin_manage_action"] = "add"
        await _edit(update, "➕ Yangi admin Telegram ID sini yuboring.", reply_markup=admin_menu())
    elif data == "adm:admin:remove":
        context.user_data["admin_manage_action"] = "remove"
        await _edit(update, "🗑 O‘chiriladigan admin Telegram ID sini yuboring.", reply_markup=admin_menu())


@admin_only
async def admin_manage_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the Telegram id typed after 'Admin qo'shish/o'chirish' (§26)."""
    action = context.user_data.get("admin_manage_action")
    if action not in {"add", "remove"}:
        return
    message = update.effective_message
    if message is None:
        return
    raw = (message.text or "").strip()
    if not raw.lstrip("-").isdigit():
        await message.reply_text("Telegram ID faqat raqamlardan iborat bo‘lishi kerak.")
        return
    telegram_id = int(raw)
    database: Database = context.application.bot_data["database"]
    try:
        async with database.session() as session:
            async with session.begin():
                if action == "add":
                    await add_database_admin(session, telegram_id)
                    result = f"✅ Admin qo‘shildi: {telegram_id}"
                else:
                    removed = await remove_database_admin(session, telegram_id)
                    result = f"✅ Admin o‘chirildi: {telegram_id}" if removed else "⚠️ Bu ID database adminlarida topilmadi."
    except Exception:
        logger.exception("Admin management failed")
        await message.reply_text("Amal bajarilmadi. Qayta urinib ko‘ring.")
        return
    context.user_data.pop("admin_manage_action", None)
    await message.reply_text(result, reply_markup=admin_menu())
