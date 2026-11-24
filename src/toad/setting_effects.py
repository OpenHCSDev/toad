"""What the app does when a declared setting changes."""
from __future__ import annotations
from typing import TYPE_CHECKING
from formbridge.forms.declared_fields import DeclaredField

if TYPE_CHECKING:
    from toad.app import ToadApp


from toad.client.history import WireView
from toad.client.history_pager import PagingWindow
from toad.client.prompt_composer import PromptSettingEffects
from toad.client.prompt_stack import SettingVisible
from toad.client.view_layout import LayoutFollower
from toad.setting_declarations import Effect


@Effect
def visibility(app: ToadApp, field: DeclaredField) -> None:
    for widget in Effect.open_widgets(app, SettingVisible):
        if widget.visibility_setting == field.path.value:
            widget.apply_setting_visibility()
    # A shown or hidden row changes the room the prompt's parts take (the info bar's margin
    # reads the footer): each prompt places its input box again.
    for prompt in Effect.open_widgets(app, PromptSettingEffects):
        prompt.place_input_box()


@Effect
def wheel_scroll_rows(app: ToadApp, field: DeclaredField) -> None:
    app.follow_wheel_scroll_rows()


@Effect
def history_buffer_viewports(app: ToadApp, field: DeclaredField) -> None:
    for window in Effect.open_widgets(app, PagingWindow):
        window.apply_buffer_viewports()


@Effect
def conversation_layout(app: ToadApp, field: DeclaredField) -> None:
    for widget in Effect.open_widgets(app, LayoutFollower):
        widget.apply_layout_preferences()


@Effect
def sidebar_filters(app: ToadApp, field: DeclaredField) -> None:
    app.coordination_access.update_sidebar_interest()
    # The session tabs append the unread badge `sidebar.unread_counts` draws (`show_session_tabs`).
    app.update_show_sessions()


@Effect
def theme(app: ToadApp, field: DeclaredField) -> None:
    app.follow_theme()


@Effect
def key_mode(app: ToadApp, field: DeclaredField) -> None:
    app.follow_key_mode()


@Effect
def sessions_bar(app: ToadApp, field: DeclaredField) -> None:
    app.update_show_sessions()


@Effect
def blink_title(app: ToadApp, field: DeclaredField) -> None:
    app.input_attention.update()



@Effect
def message_style(app: ToadApp, field: DeclaredField) -> None:
    for view in Effect.open_widgets(app, WireView):
        view.apply_message_style()
