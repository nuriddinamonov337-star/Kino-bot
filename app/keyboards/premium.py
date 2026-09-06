"""Premium payment keyboard factories."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def premium_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("💎 1 hafta — 10 000 so'm", callback_data="premium:plan:weekly")], [InlineKeyboardButton("💎 1 oy — 15 000 so'm", callback_data="premium:plan:monthly")], [InlineKeyboardButton("🔙 Orqaga", callback_data="premium:back")]])


def receipt_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🧾 Chekni yuborish", callback_data="premium:receipt")], [InlineKeyboardButton("❌ Bekor qilish", callback_data="premium:cancel")]])


def review_keyboard(payment_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"premium:approve:{payment_id}"), InlineKeyboardButton("❌ Rad etish", callback_data=f"premium:reject:{payment_id}")]])
