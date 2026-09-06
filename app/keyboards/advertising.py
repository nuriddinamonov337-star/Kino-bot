"""User and admin keyboards for advertising requests."""

from uuid import UUID

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.database.models import AdvertisingStatus


def advertising_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📢 Obunachi yig‘ish", callback_data="ad:type:subscribers")],
            [InlineKeyboardButton("📣 Botda reklama", callback_data="ad:type:bot")],
            [InlineKeyboardButton("📡 Kanallarda reklama", callback_data="ad:type:channels")],
            [InlineKeyboardButton("👨‍💻 Admin bilan bog‘lanish", callback_data="ad:type:contact")],
        ]
    )


def cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor qilish", callback_data="ad:cancel")]])


def admin_ads_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⏳ Yangi so‘rovlar", callback_data="adm:ads:pending:0")],
            [InlineKeyboardButton("📋 Barcha so‘rovlar", callback_data="adm:ads:all:0")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="adm:main")],
        ]
    )


def ads_list_nav(kind: str, page: int, total: int) -> InlineKeyboardMarkup:
    row: list[InlineKeyboardButton] = []
    if page > 0:
        row.append(InlineKeyboardButton("⬅️", callback_data=f"adm:ads:{kind}:{page - 1}"))
    if (page + 1) * 10 < total:
        row.append(InlineKeyboardButton("➡️", callback_data=f"adm:ads:{kind}:{page + 1}"))
    rows = [row] if row else []
    rows.append([InlineKeyboardButton("🔙 Reklama", callback_data="adm:ads")])
    return InlineKeyboardMarkup(rows)


def request_actions(request_id: UUID, status: AdvertisingStatus) -> InlineKeyboardMarkup:
    ident = str(request_id)
    rows = [
        [
            InlineKeyboardButton("🔎 Ko‘rish", callback_data=f"a:v:{ident}"),
        ]
    ]
    if status is AdvertisingStatus.PENDING:
        rows.append(
            [
                InlineKeyboardButton("📝 Ko‘rib chiqish", callback_data=f"a:s:{ident}:r"),
                InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"a:s:{ident}:a"),
                InlineKeyboardButton("❌ Rad etish", callback_data=f"a:s:{ident}:j"),
            ]
        )
    elif status is AdvertisingStatus.IN_REVIEW:
        rows.append(
            [
                InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"a:s:{ident}:a"),
                InlineKeyboardButton("❌ Rad etish", callback_data=f"a:s:{ident}:j"),
            ]
        )
    elif status is AdvertisingStatus.APPROVED:
        rows.append(
            [
                InlineKeyboardButton("🏁 Yakunlash", callback_data=f"a:s:{ident}:c"),
                InlineKeyboardButton("🗑 Bekor qilish", callback_data=f"a:s:{ident}:x"),
            ]
        )
    rows.append([InlineKeyboardButton("🔙 Ro‘yxat", callback_data="adm:ads")])
    return InlineKeyboardMarkup(rows)
