"""Admin dashboard callbacks that are not part of a data-entry conversation."""

from datetime import UTC, datetime

from telegram import Update
from telegram.ext import ContextTypes

from app.config import get_settings
from app.database.models import PaymentStatus
from app.database.session import Database
from app.handlers.admin_auth import admin_only
from app.keyboards.admin import channel_menu, movie_list, movie_menu, panel, payment_list_menu, payment_menu
from app.services.admin import dashboard_statistics, list_channels, list_database_admins, list_movies
from app.services.premium import list_payments


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
        prefix = "👥 Foydalanuvchilar" if data == "adm:users" else "📊 Statistika"
        extra = f"\n🤖 Bot ishga tushgan: {context.application.bot_data['started_at'].astimezone(UTC):%Y-%m-%d %H:%M UTC}" if data == "adm:stats" else ""
        await _edit(update, f"{prefix}\n\n👥 Jami: {stats['users']}\n🟢 Faol: {stats['active_users']}\n💎 Premium: {stats['premium_users']}\n🎬 Faol kinolar: {stats['active_movies']}\n📢 Majburiy kanallar: {stats['active_channels']}{extra}", reply_markup=panel())
    elif data == "adm:admins":
        async with database.session() as session:
            db_admins = await list_database_admins(session)
        configured = ", ".join(map(str, get_settings().admin_ids)) or "yo‘q"
        stored = ", ".join(str(admin.telegram_id) for admin in db_admins) or "yo‘q"
        await _edit(update, f"👨‍💼 Adminlar\n\nConfig ADMIN_IDS: {configured}\nDatabase: {stored}", reply_markup=panel())
