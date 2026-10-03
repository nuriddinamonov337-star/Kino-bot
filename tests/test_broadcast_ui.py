"""Tests for broadcast conversation wiring (keyboards, states, registration)."""

from app.handlers.admin_broadcast import _TARGET_MAP, broadcast_conversation
from app.keyboards.admin import broadcast_confirm, broadcast_targets, panel
from app.services.broadcast import BroadcastTarget


def _all_callback_data(markup) -> list[str]:
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def test_panel_has_broadcast_button() -> None:
    assert "adm:broadcast" in _all_callback_data(panel())


def test_target_keyboard_lists_all_targets() -> None:
    data = _all_callback_data(broadcast_targets())
    assert "adm:broadcast:target:users" in data
    assert "adm:broadcast:target:main" in data
    assert "adm:broadcast:target:reels" in data
    assert "adm:broadcast:target:all" in data
    assert "adm:broadcast:target:custom" in data
    assert "adm:cancel" in data


def test_confirm_keyboard_has_send_and_cancel() -> None:
    data = _all_callback_data(broadcast_confirm())
    assert "adm:broadcast:send" in data
    assert "adm:cancel" in data


def test_every_broadcast_target_has_a_handler_choice() -> None:
    assert set(_TARGET_MAP.values()) == set(BroadcastTarget)


def test_conversation_states_and_entry_points() -> None:
    entry_patterns = [handler.pattern.pattern for handler in broadcast_conversation.entry_points]
    assert any("adm:broadcast" in pattern for pattern in entry_patterns)
    assert len(broadcast_conversation.states) == 4  # TARGET, IDS, CONTENT, CONFIRM
    assert broadcast_conversation.fallbacks


def test_conversation_is_registered() -> None:
    import app.handlers as handlers_package

    assert handlers_package.broadcast_conversation is broadcast_conversation