"""User and admin keyboards for the paid advertising system (§12) and the
mandatory-channel subscriber-growth service (§13)."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.database.models import AdStatus


# --------------------------------------------------------------------------- #
# §12 — Paid advertising (user flow)
# --------------------------------------------------------------------------- #
def tariff_menu(week_price: int, month_price: int) -> InlineKeyboardMarkup:
    """Step 2: choose a tariff."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"🔹 1 Week — {week_price:,} so'm", callback_data="ad:tariff:week")],
            [InlineKeyboardButton(f"🔹 1 Month — {month_price:,} so'm", callback_data="ad:tariff:month")],
            [InlineKeyboardButton("❌ Bekor qilish", callback_data="ad:cancel")],
        ]
    )


def tariff_confirm() -> InlineKeyboardMarkup:
    """Step 3: confirm the chosen tariff."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Davom etish", callback_data="ad:continue"),
                InlineKeyboardButton("❌ Bekor qilish", callback_data="ad:cancel"),
            ]
        ]
    )


def preview_confirm() -> InlineKeyboardMarkup:
    """Step 5: confirm the ad preview."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Tasdiqlash", callback_data="ad:confirm"),
                InlineKeyboardButton("❌ Bekor qilish", callback_data="ad:cancel"),
            ]
        ]
    )


def cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor qilish", callback_data="ad:cancel")]])


def admin_review(campaign_id: int) -> InlineKeyboardMarkup:
    """Admin approve/reject buttons for a new ad order."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"ad:admin:approve:{campaign_id}"),
                InlineKeyboardButton("❌ Bekor qilish", callback_data=f"ad:admin:reject:{campaign_id}"),
            ]
        ]
    )


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


def campaign_actions(campaign_id: int, status: AdStatus) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if status is AdStatus.PENDING:
        rows.append(
            [
                InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"ad:admin:approve:{campaign_id}"),
                InlineKeyboardButton("❌ Bekor qilish", callback_data=f"ad:admin:reject:{campaign_id}"),
            ]
        )
    rows.append([InlineKeyboardButton("🔙 Ro‘yxat", callback_data="adm:ads")])
    return InlineKeyboardMarkup(rows)


# --------------------------------------------------------------------------- #
# §13 — Mandatory-channel subscriber growth (user flow)
# --------------------------------------------------------------------------- #
def subscriber_service_menu() -> InlineKeyboardMarkup:
    """User-facing entry: contact admin or cancel."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("👨‍💼 Admin bilan bog‘lanish", callback_data="sub:contact")],
            [InlineKeyboardButton("❌ Bekor qilish", callback_data="sub:cancel")],
        ]
    )


# --------------------------------------------------------------------------- #
# §13 — Mandatory-channel subscriber growth (admin flow)
# --------------------------------------------------------------------------- #
def subscriber_package_menu(prices: dict[int, int]) -> InlineKeyboardMarkup:
    """Admin picks a subscriber package (100/500/1000)."""
    rows = [
        [InlineKeyboardButton(f"{target} ta — {price:,} so'm", callback_data=f"adm:sub:pkg:{target}")]
        for target, price in prices.items()
    ]
    rows.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="adm:sub:cancel")])
    return InlineKeyboardMarkup(rows)


def subscriber_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor qilish", callback_data="adm:sub:cancel")]])
