"""Preference effects, referenced by the declarations that own them."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.setting_choices import SessionBar


def history_buffer_viewports(app: ToadApp, value: int) -> None:
    from toad.widgets.history_anchor import HistoryWindow

    for view in app.workspace_sessions.views.values():
        for window in view.query(HistoryWindow):
            viewport = window.document_viewport
            viewport.budget = replace(viewport.budget, buffer_viewports=value)
            viewport.request()
            for history in tuple(window.histories):
                history.prepare_scroll()


def conversation_layout(app: ToadApp, value: object) -> None:
    """Invalidate native layout; the renderer reads the original preference tree."""
    from toad.widgets.conversation import Conversation

    for view in app.workspace_sessions.views.values():
        for conversation in view.query(Conversation):
            conversation.apply_layout_preferences()


def sidebar_spinner_frames_per_second(app: ToadApp, value: int) -> None:
    app.workspace_chrome.channels.roster.projection.update_animation_cadence()


def theme(app: ToadApp, value: str) -> None:
    app.theme = value


def compact_input(app: ToadApp, value: bool) -> None:
    app.set_class(value, "-compact-input")


def footer(app: ToadApp, value: bool) -> None:
    app.set_class(not value, "-hide-footer")


def status_line(app: ToadApp, value: bool) -> None:
    app.set_class(not value, "-hide-status-line")


def agent_title(app: ToadApp, value: bool) -> None:
    app.set_class(not value, "-hide-agent-title")


def info_bar(app: ToadApp, value: bool) -> None:
    app.set_class(not value, "-hide-info-bar")


def thoughts(app: ToadApp, value: bool) -> None:
    app.set_class(not value, "-hide-thoughts")


def sessions_bar(app: ToadApp, value: type[SessionBar]) -> None:
    app.update_show_sessions()


def blink_title(app: ToadApp, value: bool) -> None:
    app.terminal_attention.update()
