"""Telegram handler registration."""

from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from app.handlers.admin_ads import ads_list, ads_menu, ads_review, ads_view
from app.handlers.admin_broadcast import broadcast_conversation
from app.handlers.admin_channels import channel_conversation, channel_delete_conversation
from app.handlers.admin_jobs import jobs_list, jobs_retry
from app.handlers.admin_movies import movie_conversation, movie_delete_conversation
from app.handlers.admin_panel import admin_command, admin_manage_message, panel_callback
from app.handlers.advertising import advertising_conversation
from app.handlers.movies import movie_code
from app.handlers.premium import premium_conversation, review_callback
from app.handlers.profile import show_profile
from app.handlers.start import start
from app.handlers.subscriptions import recheck_subscription


def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(premium_conversation)
    application.add_handler(advertising_conversation)
    application.add_handler(movie_conversation)
    application.add_handler(movie_delete_conversation)
    application.add_handler(channel_conversation)
    application.add_handler(channel_delete_conversation)
    application.add_handler(broadcast_conversation)
    application.add_handler(
        CallbackQueryHandler(
            panel_callback,
            pattern=r"^adm:(main|movies|channels|payments|users|stats|admins|admin:(add|remove)|movie:list:\d+|channel:list|payments:(pending|history):\d+)$",
        )
    )
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_manage_message))
    application.add_handler(CallbackQueryHandler(ads_menu, pattern=r"^adm:ads$"))
    application.add_handler(CallbackQueryHandler(ads_list, pattern=r"^adm:ads:(pending|all):\d+$"))
    application.add_handler(CallbackQueryHandler(ads_view, pattern=r"^ad:view:\d+$"))
    application.add_handler(CallbackQueryHandler(ads_review, pattern=r"^ad:admin:(approve|reject):\d+$"))
    application.add_handler(CallbackQueryHandler(jobs_list, pattern=r"^adm:jobs:\d+$"))
    application.add_handler(CallbackQueryHandler(jobs_retry, pattern=r"^j:r:[0-9a-f-]{36}$"))
    application.add_handler(CallbackQueryHandler(recheck_subscription, pattern=r"^subscription:check$"))
    application.add_handler(CallbackQueryHandler(review_callback, pattern=r"^premium:(approve|reject):[0-9a-f-]{36}$"))
    application.add_handler(MessageHandler(filters.Regex(r"^👤 Profil$"), show_profile))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r"^\d{1,20}$"), movie_code))
