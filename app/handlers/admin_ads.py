"""Admin advertising campaign review callbacks (§12)."""

from __future__ import annotations

import logging

from sqlalchemy.exc import SQLAlchemyError
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app.config import get_settings
from app.database.models import AdCampaign, AdStatus
from app.database.session import Database
from app.handlers.admin_auth import admin_only
from app.keyboards.advertising import admin_ads_menu, ads_list_nav, campaign_actions
from app.services.advertising import (
    approve_campaign,
    get_campaign,
    list_campaigns,
    reject_campaign,
    tariff_label,
    tariff_times_per_day,
    tariff_total_posts,
)

logger = logging.getLogger(__name__)


def _format_campaign(campaign: AdCampaign) -> str:
    settings = get_settings()
    username = f"@{campaign.user.username}" if campaign.user and campaign.user.username else "username yo‘q"
    telegram_id = campaign.user.telegram_id if campaign.user else "?"
    return (
        "📢 Reklama kampaniyasi\n\n"
        f"🆔 #{campaign.id}\n"
        f"👤 {username} | ID: {telegram_id}\n"
        f"📦 Tarif: {tariff_label(campaign.tariff)}\n"
        f"💰 Narxi: {campaign.price:,} so'm\n"
        f"📊 Kuniga: {tariff_times_per_day(campaign.tariff, settings)} marta\n"
        f"🔢 Jami: {tariff_total_posts(campaign.tariff, settings)} marta\n"
        f"📈 Joylashtirilgan: {campaign.posted_count}/{campaign.total_posts}\n"
        f"📌 Holat: {campaign.status.value}\n\n"
        f"📝 Matn: {campaign.caption or '(matn yo‘q)'}"
    )


@admin_only
async def ads_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("📣 Reklama so‘rovlari", reply_markup=admin_ads_menu())


@admin_only
async def ads_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    _, _, kind, page_text = (query.data or "").split(":")
    page = max(0, int(page_text))
    status = AdStatus.PENDING if kind == "pending" else None
    database: Database = context.application.bot_data["database"]
    async with database.session() as session:
        campaigns, total = await list_campaigns(session, status, page)
    lines = [f"📣 So‘rovlar ({total})"]
    lines += [
        f"#{item.id} | {item.status.value} | {tariff_label(item.tariff)} | {item.posted_count}/{item.total_posts}"
        for item in campaigns
    ]
    await query.answer()
    await query.edit_message_text(
        "\n".join(lines) if campaigns else "So‘rovlar yo‘q.",
        reply_markup=ads_list_nav(kind, page, total),
    )


@admin_only
async def ads_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    try:
        campaign_id = int((query.data or "").split(":")[2])
    except (IndexError, ValueError):
        await query.answer("Noto‘g‘ri so‘rov.", show_alert=True)
        return
    database: Database = context.application.bot_data["database"]
    async with database.session() as session:
        campaign = await get_campaign(session, campaign_id)
    if campaign is None:
        await query.answer("Topilmadi.", show_alert=True)
        return
    await query.answer()
    await query.edit_message_text(
        _format_campaign(campaign),
        reply_markup=campaign_actions(campaign.id, campaign.status),
    )


@admin_only
async def ads_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Approve or reject a campaign from the admin notification buttons."""
    query = update.callback_query
    if query is None:
        return
    parts = (query.data or "").split(":")
    try:
        action, campaign_id = parts[2], int(parts[3])
    except (IndexError, ValueError):
        await query.answer("Noto‘g‘ri amal.", show_alert=True)
        return
    database: Database = context.application.bot_data["database"]
    settings = get_settings()
    try:
        async with database.session() as session:
            async with session.begin():
                if action == "approve":
                    campaign = await approve_campaign(session, campaign_id, settings=settings)
                else:
                    campaign = await reject_campaign(session, campaign_id)
    except SQLAlchemyError:
        logger.exception("Advertising review failed")
        await query.answer("Yangilanmadi.", show_alert=True)
        return
    if campaign is None:
        await query.answer("Kampaniya topilmadi yoki allaqachon ko‘rib chiqilgan.", show_alert=True)
        return
    await query.answer("Bajarildi.")

    if campaign.status is AdStatus.ACTIVE:
        await query.edit_message_text(
            _format_campaign(campaign) + "\n\n✅ Tasdiqlandi. Joylashtirish boshlandi.",
            reply_markup=campaign_actions(campaign.id, campaign.status),
        )
        user_text = (
            "✅ Reklamangiz tasdiqlandi!\n\n"
            "Reklama joylashtirish jarayoni boshlandi.\n\n"
            f"📦 Tarif: {tariff_label(campaign.tariff)}\n"
            f"📢 Kuniga: {tariff_times_per_day(campaign.tariff, settings)} marta\n"
            f"🔢 Jami: {tariff_total_posts(campaign.tariff, settings)} marta"
        )
    else:
        await query.edit_message_text(
            _format_campaign(campaign) + "\n\n❌ Bekor qilindi.",
            reply_markup=campaign_actions(campaign.id, campaign.status),
        )
        contact = f"@{settings.admin_username}" if settings.admin_username else "admin"
        user_text = (
            "❌ Reklamangiz tasdiqlanmadi.\n\n"
            f"Iltimos, admin bilan bog‘laning: {contact}"
        )
    if campaign.user is not None:
        try:
            await context.bot.send_message(campaign.user.telegram_id, user_text)
        except TelegramError:
            logger.exception("Failed to notify user %s about ad review", campaign.user.telegram_id)
