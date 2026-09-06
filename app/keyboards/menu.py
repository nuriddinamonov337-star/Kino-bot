"""Keyboard factories for the user-facing entry flow."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.database.models import MandatoryChannel


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton("💎 Premium"), KeyboardButton("📢 Reklama")], [KeyboardButton("👤 Profil")]], resize_keyboard=True)


def mandatory_subscription_keyboard(channels: tuple[MandatoryChannel, ...]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for channel in channels:
        url = channel.invite_url or (f"https://t.me/{channel.username}" if channel.username else None)
        if url:
            buttons.append([InlineKeyboardButton(f"📢 {channel.title}", url=url)])
    buttons.append([InlineKeyboardButton("✅ Tekshirish", callback_data="subscription:check")])
    return InlineKeyboardMarkup(buttons)
