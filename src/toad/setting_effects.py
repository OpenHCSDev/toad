"""What the app does when a declared setting changes."""
from __future__ import annotations
from dataclasses import replace
from typing import TYPE_CHECKING
from formbridge.forms.declared_fields import DeclaredField
from toad.setting_widget import SettingVisibility
from toad.widgets.history_anchor import HistoryWindow
from toad.layout_preferences import FollowsLayoutPreferences

if TYPE_CHECKING:
    from toad.app import ToadApp


from toad.setting_declarations import Effect


@Effect
def visibility(app: ToadApp, field: DeclaredField) -> None:
    from toad.widgets.prompt import Prompt
    for widget in Effect.open_widgets(app, SettingVisibility):
        if widget.visibility_setting == field.path.value:
            widget.display = widget.configuration_state.get_resolved_value(field.path.value)
    for prompt in Effect.open_widgets(app, Prompt):
        prompt.refresh(layout=True)


@Effect
def wheel_scroll_rows(app: ToadApp, field: DeclaredField) -> None:
    app.scroll_sensitivity_y = field.value


@Effect
def history_buffer_viewports(app: ToadApp, field: DeclaredField) -> None:
    for window in Effect.open_widgets(app, HistoryWindow):
        value = window.configuration_state.get_resolved_value(field.path.value)
        window.presentation_budget = replace(window.presentation_budget, buffer_viewports=value)
        window.request_preparation()


@Effect
def conversation_layout(app: ToadApp, field: DeclaredField) -> None:
    for widget in Effect.open_widgets(app, FollowsLayoutPreferences):
        widget.apply_layout_preferences()


@Effect
def sidebar_filters(app: ToadApp, field: DeclaredField) -> None:
    app.coordination_access.update_sidebar_interest()


@Effect
def theme(app: ToadApp, field: DeclaredField) -> None:
    app.colours.choose(field.value)


@Effect
def key_mode(app: ToadApp, field: DeclaredField) -> None:
    from toad.widgets.prompt import PromptTextArea
    for editor in Effect.open_widgets(app, PromptTextArea):
        editor.apply_keyboard_profile()
    app.refresh_bindings()


@Effect
def sessions_bar(app: ToadApp, field: DeclaredField) -> None:
    app.update_show_sessions()


@Effect
def blink_title(app: ToadApp, field: DeclaredField) -> None:
    app.terminal_attention.update()

