"""What the app does when a declared setting changes."""
from __future__ import annotations
from dataclasses import replace
from typing import TYPE_CHECKING
from toad.forms.declared_views import DeclaredField
from toad.setting_widget import SettingVisibility
from toad.widgets.history_anchor import HistoryWindow

if TYPE_CHECKING:
    from toad.app import ToadApp


from toad import setting_declarations


@setting_declarations.Effect
def visibility(app: ToadApp, field: DeclaredField) -> None:
    from toad.widgets.prompt import Prompt
    for widget in setting_declarations.Effect.open_widgets(app, SettingVisibility):
        if widget.visibility_setting == field.path.value:
            widget.display = field.value
    for prompt in setting_declarations.Effect.open_widgets(app, Prompt):
        prompt.refresh(layout=True)


@setting_declarations.Effect
def wheel_scroll_rows(app: ToadApp, field: DeclaredField) -> None:
    app.scroll_sensitivity_y = field.value


@setting_declarations.Effect
def history_buffer_viewports(app: ToadApp, field: DeclaredField) -> None:
    for view in app.workspace_sessions.views.values():
        for window in view.query(HistoryWindow):
            window.presentation_budget = replace(window.presentation_budget, buffer_viewports=field.value)
            window.request_preparation()


@setting_declarations.Effect
def conversation_layout(app: ToadApp, field: DeclaredField) -> None:
    from toad.widgets.conversation import Conversation
    for conversation in setting_declarations.Effect.open_widgets(app, Conversation):
        conversation.apply_layout_preferences()


@setting_declarations.Effect
def sidebar_filters(app: ToadApp, field: DeclaredField) -> None:
    app.coordination_access.update_sidebar_interest()


@setting_declarations.Effect
def theme(app: ToadApp, field: DeclaredField) -> None:
    app.colours.choose(field.value)


@setting_declarations.Effect
def vim_keys(app: ToadApp, field: DeclaredField) -> None:
    from toad.widgets.prompt import PromptTextArea
    for editor in setting_declarations.Effect.open_widgets(app, PromptTextArea):
        editor.apply_keyboard_profile()
    app.refresh_bindings()


@setting_declarations.Effect
def sessions_bar(app: ToadApp, field: DeclaredField) -> None:
    app.update_show_sessions()


@setting_declarations.Effect
def blink_title(app: ToadApp, field: DeclaredField) -> None:
    app.terminal_attention.update()
