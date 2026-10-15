"""What the app does when a setting takes a value, declared on the setting."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from toad.app import ToadApp
    from toad.setting_choices import SessionBar


@dataclass(frozen=True)
class Effect:
    """`Annotated` metadata on a setting: called with the app and the new value."""

    apply: Callable[[ToadApp, Any], None]


@Effect
def history_buffer_viewports(app: ToadApp, value: int) -> None:
    from toad.widgets.history_anchor import HistoryWindow

    for view in app.workspace_sessions.views.values():
        for window in view.query(HistoryWindow):
            window.presentation_budget = replace(window.presentation_budget, buffer_viewports=value)
            window.request_preparation()


@Effect
def conversation_layout(app: ToadApp, value: object) -> None:
    """Lay the conversation out again; it reads the settings itself."""
    from toad.widgets.conversation import Conversation

    for view in app.workspace_sessions.views.values():
        for conversation in view.query(Conversation):
            conversation.apply_layout_preferences()


@Effect
def sidebar_spinner_frames_per_second(app: ToadApp, value: int) -> None:
    app.busy_rows.cadence_changed()


@Effect
def diff_style(app: ToadApp, value: object) -> None:
    """Existing line renderers prepare again with the new diff preference."""
    app.colours.variables_changed(app.colours.variables)
    app.theme_changed_signal.publish(app.current_theme)


@Effect
def sidebar_filters(app: ToadApp, value: bool) -> None:
    app.coordination_access.update_sidebar_interest()


@Effect
def theme(app: ToadApp, value: str) -> None:
    app.colours.choose(value)


@Effect
def compact_input(app: ToadApp, value: bool) -> None:
    app.set_class(value, "-compact-input")


@Effect
def footer(app: ToadApp, value: bool) -> None:
    app.set_class(not value, "-hide-footer")


@Effect
def status_line(app: ToadApp, value: bool) -> None:
    app.set_class(not value, "-hide-status-line")


@Effect
def agent_title(app: ToadApp, value: bool) -> None:
    app.set_class(not value, "-hide-agent-title")


@Effect
def info_bar(app: ToadApp, value: bool) -> None:
    app.set_class(not value, "-hide-info-bar")


@Effect
def thoughts(app: ToadApp, value: bool) -> None:
    app.set_class(not value, "-hide-thoughts")


@Effect
def sessions_bar(app: ToadApp, value: type[SessionBar]) -> None:
    app.update_show_sessions()


@Effect
def blink_title(app: ToadApp, value: bool) -> None:
    app.terminal_attention.update()
