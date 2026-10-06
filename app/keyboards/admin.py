"""Inline keyboard factories for the admin panel."""

from uuid import UUID

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.database.models import Movie
from app.services.admin import MOVIES_PER_PAGE

CANCEL = "adm:cancel"


def panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎬 Kino boshqaruvi", callback_data="adm:movies")],
            [InlineKeyboardButton("📢 Kanallar", callback_data="adm:channels")],
            [InlineKeyboardButton("💳 Premium to'lovlar", callback_data="adm:payments")],
            [InlineKeyboardButton("📣 Reklama so‘rovlari", callback_data="adm:ads")],
            [InlineKeyboardButton("🎞 Reel joblar", callback_data="adm:jobs:0")],
            [InlineKeyboardButton("📤 Xabar yuborish", callback_data="adm:broadcast")],
            [InlineKeyboardButton("👥 Foydalanuvchilar", callback_data="adm:users")],
            [InlineKeyboardButton("📊 Statistika", callback_data="adm:stats")],
            [InlineKeyboardButton("👨‍💼 Adminlar", callback_data="adm:admins")],
        ]
    )


def payment_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⏳ Kutilayotgan to'lovlar", callback_data="adm:payments:pending:0")],
            [InlineKeyboardButton("📋 To'lovlar tarixi", callback_data="adm:payments:history:0")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="adm:main")],
        ]
    )


def payment_list_menu(kind: str, page: int, total: int) -> InlineKeyboardMarkup:
    row: list[InlineKeyboardButton] = []
    if page > 0:
        row.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"adm:payments:{kind}:{page - 1}"))
    if (page + 1) * 10 < total:
        row.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"adm:payments:{kind}:{page + 1}"))
    rows = [row] if row else []
    rows.append([InlineKeyboardButton("🔙 To'lovlar", callback_data="adm:payments")])
    return InlineKeyboardMarkup(rows)


def movie_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Kino qo'shish", callback_data="adm:movie:add")],
            [InlineKeyboardButton("🗑 Kino o'chirish", callback_data="adm:movie:delete")],
            [InlineKeyboardButton("📋 Kinolar ro'yxati", callback_data="adm:movie:list:0")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="adm:main")],
        ]
    )


def source_choice() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎬 Video yuborish", callback_data="adm:movie:video")],
            [InlineKeyboardButton("🔗 URL kiritish", callback_data="adm:movie:url")],
            [InlineKeyboardButton("❌ Bekor qilish", callback_data=CANCEL)],
        ]
    )


def cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor qilish", callback_data=CANCEL)]])


def broadcast_targets() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👤 Barcha foydalanuvchilarga", callback_data="adm:broadcast:target:users")],
            [InlineKeyboardButton("📢 1-kanalga", callback_data="adm:broadcast:target:main")],
            [InlineKeyboardButton("🎬 2-kanalga", callback_data="adm:broadcast:target:reels")],
            [InlineKeyboardButton("📨 Hammasiga", callback_data="adm:broadcast:target:all")],
            [InlineKeyboardButton("📝 Maxsus ID'larga", callback_data="adm:broadcast:target:custom")],
            [InlineKeyboardButton("❌ Bekor qilish", callback_data=CANCEL)],
        ]
    )


def broadcast_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Yuborish", callback_data="adm:broadcast:send"),
                InlineKeyboardButton("❌ Bekor qilish", callback_data=CANCEL),
            ]
        ]
    )


def movie_preview() -> InlineKeyboardMarkup:
    """Save/Cancel confirmation shown before a movie is written to the database."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("💾 Saqlash", callback_data="adm:movie:save"),
                InlineKeyboardButton("❌ Bekor qilish", callback_data=CANCEL),
            ]
        ]
    )


def confirm_movie_delete(movie_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Ha", callback_data=f"adm:movie:confirm:{movie_id}"),
                InlineKeyboardButton("❌ Yo'q", callback_data="adm:movies"),
            ]
        ]
    )


def movie_list(movies: list[Movie], page: int, total: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if page > 0:
        rows.append([InlineKeyboardButton("⬅️ Oldingi", callback_data=f"adm:movie:list:{page - 1}")])
    if (page + 1) * MOVIES_PER_PAGE < total:
        next_button = InlineKeyboardButton("Keyingi ➡️", callback_data=f"adm:movie:list:{page + 1}")
        if rows:
            rows[-1].append(next_button)
        else:
            rows.append([next_button])
    rows.append([InlineKeyboardButton("🔙 Orqaga", callback_data="adm:movies")])
    return InlineKeyboardMarkup(rows)


def channel_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Kanal qo'shish", callback_data="adm:channel:add")],
            [InlineKeyboardButton("🗑 Kanalni o'chirish", callback_data="adm:channel:delete")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="adm:main")],
        ]
    )


def confirm_channel_delete(channel_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Ha", callback_data=f"adm:channel:confirm:{channel_id}"),
                InlineKeyboardButton("❌ Yo'q", callback_data="adm:channels"),
            ]
        ]
    )


def admin_menu() -> InlineKeyboardMarkup:
    """Admin management submenu (§26)."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Admin qo'shish", callback_data="adm:admin:add")],
            [InlineKeyboardButton("🗑 Adminni o'chirish", callback_data="adm:admin:remove")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="adm:main")],
        ]
    )


def jobs_list_menu(page: int, total: int, failed_job_ids: list[UUID] | None = None) -> InlineKeyboardMarkup:
    row: list[InlineKeyboardButton] = []
    if page > 0:
        row.append(InlineKeyboardButton("⬅️", callback_data=f"adm:jobs:{page - 1}"))
    if (page + 1) * 10 < total:
        row.append(InlineKeyboardButton("➡️", callback_data=f"adm:jobs:{page + 1}"))
    rows = [row] if row else []
    for job_id in failed_job_ids or []:
        rows.append([InlineKeyboardButton("🔁 Qayta urinish", callback_data=f"j:r:{job_id}")])
    rows.append([InlineKeyboardButton("🔙 Orqaga", callback_data="adm:main")])
    return InlineKeyboardMarkup(rows)