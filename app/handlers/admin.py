"""Compatibility exports for the existing admin handlers."""

from app.handlers.admin_ads import ads_list, ads_menu, ads_status, ads_view
from app.handlers.admin_channels import channel_conversation, channel_delete_conversation
from app.handlers.admin_jobs import jobs_list, jobs_retry
from app.handlers.admin_movies import movie_conversation, movie_delete_conversation
from app.handlers.admin_panel import admin_command, panel_callback

__all__ = [
    "admin_command",
    "ads_list",
    "ads_menu",
    "ads_status",
    "ads_view",
    "channel_conversation",
    "channel_delete_conversation",
    "jobs_list",
    "jobs_retry",
    "movie_conversation",
    "movie_delete_conversation",
    "panel_callback",
]