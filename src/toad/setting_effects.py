"""What the app does when a declared setting changes."""
from __future__ import annotations
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING
from toad.forms.declared_views import DeclaredField
from toad.setting_widget import SettingVisibility
from toad.widgets.history_anchor import HistoryWindow

if TYPE_CHECKING:
    from toad.app import ToadApp


@dataclass(frozen=True)
class Effect:
    apply: Callable[[ToadApp, DeclaredField], None]

    @staticmethod
    def open_widgets(app, widget_type):
        roots = (*app.workspace_sessions.views.values(), *app.screen_stack)
        return {widget for root in roots for widget in root.query(widget_type)}


@Effect
def visibility(app: ToadApp, field: DeclaredField) -> None:
    for widget in Effect.open_widgets(app, SettingVisibility):
        if widget.visibility_setting == field.path.value:
            widget.display = field.value


@Effect
def history_buffer_viewports(app: ToadApp, field: DeclaredField) -> None:
    for view in app.workspace_sessions.views.values():
        for window in view.query(HistoryWindow):
            window.presentation_budget = replace(window.presentation_budget, buffer_viewports=field.value)
            window.request_preparation()


@Effect
def conversation_layout(app: ToadApp, field: DeclaredField) -> None:
    from toad.widgets.conversation import Conversation
    for conversation in Effect.open_widgets(app, Conversation):
        conversation.apply_layout_preferences()


@Effect
def diff_style(app: ToadApp, field: DeclaredField) -> None:
    app.colours.variables_changed(app.colours.variables)
    app.theme_changed_signal.publish(app.current_theme)


@Effect
def sidebar_filters(app: ToadApp, field: DeclaredField) -> None:
    app.coordination_access.update_sidebar_interest()


@Effect
def theme(app: ToadApp, field: DeclaredField) -> None:
    app.colours.choose(field.value)


@Effect
def vim_keys(app: ToadApp, field: DeclaredField) -> None:
    from toad.widgets.prompt import PromptTextArea
    for editor in Effect.open_widgets(app, PromptTextArea):
        editor.apply_keyboard_profile()
    app.refresh_bindings()


@Effect
def prompt_layout(app: ToadApp, field: DeclaredField) -> None:
    from toad.widgets.prompt import Prompt
    for prompt in Effect.open_widgets(app, Prompt):
        prompt.refresh(layout=True)


@Effect
def footer(app: ToadApp, field: DeclaredField) -> None:
    visibility.apply(app, field)
    prompt_layout.apply(app, field)


@Effect
def sessions_bar(app: ToadApp, field: DeclaredField) -> None:
    app.update_show_sessions()


@Effect
def blink_title(app: ToadApp, field: DeclaredField) -> None:
    app.terminal_attention.update()
