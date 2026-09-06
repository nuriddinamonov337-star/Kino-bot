"""Admin advertising request review callbacks."""

from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app.database.models import AdvertisingStatus
from app.database.session import Database
from app.handlers.admin_auth import admin_only
from app.keyboards.advertising import admin_ads_menu, ads_list_nav, request_actions
from app.services.advertising import get_advertising_request, list_advertising_requests, update_advertising_status

STATUS_CODES = {
    "r": AdvertisingStatus.IN_REVIEW,
    "a": AdvertisingStatus.APPROVED,
    "j": AdvertisingStatus.REJECTED,
    "c": AdvertisingStatus.COMPLETED,
    "x": AdvertisingStatus.CANCELLED,
}


def _format_request(request) -> str:
    extra = []
    if request.channel_title:
        extra.append(f"Kanal: {request.channel_title}")
    if request.channel_link:
        extra.append(f"Link: {request.channel_link}")
    if request.target_count:
        extra.append(f"Maqsad: {request.target_count}")
    extra_text = ("\n" + "\n".join(extra)) if extra else ""
    return (
        f"📣 {request.ad_type.value} | {request.status.value}\n"
        f"ID: {request.id}\n"
        f"User: {request.user.telegram_id if request.user else '?'}\n"
        f"{extra_text}\n\n{request.details}"
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
    status = AdvertisingStatus.PENDING if kind == "pending" else None
    database: Database = context.application.bot_data["database"]
    async with database.session() as session:
        requests, total = await list_advertising_requests(session, status, page)
    lines = [f"📣 So‘rovlar ({total})"]
    lines += [f"{item.status.value} | {item.ad_type.value} | {item.id}" for item in requests]
    await query.answer()
    await query.edit_message_text(
        "\n".join(lines) if requests else "So‘rovlar yo‘q.",
        reply_markup=ads_list_nav(kind, page, total),
    )


@admin_only
async def ads_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    try:
        request_id = UUID((query.data or "").split(":")[2])
    except (IndexError, ValueError):
        await query.answer("Noto‘g‘ri so‘rov.", show_alert=True)
        return
    database: Database = context.application.bot_data["database"]
    async with database.session() as session:
        request = await get_advertising_request(session, request_id)
    if request is None:
        await query.answer("Topilmadi.", show_alert=True)
        return
    await query.answer()
    await query.edit_message_text(_format_request(request), reply_markup=request_actions(request.id, request.status))


@admin_only
async def ads_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    parts = (query.data or "").split(":")
    try:
        request_id, code = UUID(parts[2]), parts[3]
        status = STATUS_CODES[code]
    except (IndexError, ValueError, KeyError):
        await query.answer("Noto‘g‘ri holat.", show_alert=True)
        return
    database: Database = context.application.bot_data["database"]
    try:
        async with database.session() as session:
            async with session.begin():
                request = await update_advertising_status(session, request_id, status, update.effective_user.id)
    except SQLAlchemyError:
        await query.answer("Yangilanmadi.", show_alert=True)
        return
    if request is None:
        await query.answer("Topilmadi.", show_alert=True)
        return
    await query.answer("Holat yangilandi.")
    await query.edit_message_text(_format_request(request), reply_markup=request_actions(request.id, request.status))
    try:
        await context.bot.send_message(
            request.user.telegram_id,
            f"📣 Reklama so‘rovingiz holati: {request.status.value}",
        )
    except TelegramError:
        pass
