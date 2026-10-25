"""Textual actions, bindings and palette entries share their declarations."""

from __future__ import annotations

from abc import abstractmethod
from functools import partial
from typing import TYPE_CHECKING, ClassVar
from textual.command import DiscoveryHit, Hit, Hits, Provider
from toad.preferences import SETTINGS
from toad.widget_actions import (
    ApplicationAction,
    KeyboundAction,
    MenuAction,
    VimApplicationAction,
    YieldingKey,
)
from toad.target_commands import TargetContext
from toad.thread_actions import ThreadAction
from agent_comms.errors import RelationViolationError
from agent_comms.cli_commands import NewThreadCliCommand
from agent_comms.channel_targets import ProjectTarget

if TYPE_CHECKING:
    from toad.app import ToadApp


class PaletteAction:
    help: ClassVar[str]

    @abstractmethod
    def label(self, app: ToadApp) -> str: ...


class NewThreadAction(ApplicationAction, MenuAction):
    menu_order = 0
    menu_label = "New thread"

    async def apply(self, app: ToadApp) -> None:
        mode = app.selected_mode
        try:
            project = app.workspace_sessions.origin(mode).require().project_root
        except RelationViolationError:
            project = app.project_dir
        app.run_worker(
            partial(self.collect, app, mode, project),
            group="new-session",
            exclusive=True,
        )

    async def collect(self, app, mode, project):
        def prepare():
            ctx = TargetContext(
                app,
                app.coordination_access.observation.observed().service,
                ProjectTarget(str(project)),
                "",
                project,
                mode,
            )
            definition = next(
                action
                for action in ctx.available_actions()
                if action.declaration is NewThreadCliCommand
            )
            return partial(ThreadAction.collect, ctx, definition)

        open_form = await app.preparation.run_thread(prepare)
        if app.selected_mode == mode:
            open_form()


class SettingsAction(KeyboundAction, ApplicationAction, PaletteAction, MenuAction):
    menu_order = 10
    menu_label = "Settings"
    key = "ctrl+comma"
    description = "Settings"
    tooltip = "Settings screen"
    help = "Edit persistent application preferences"

    def label(self, app: ToadApp) -> str:
        return self.menu_label

    async def apply(self, app: ToadApp) -> None:
        app.run_worker(partial(self.edit, app))

    async def edit(self, app: ToadApp) -> None:
        from toad.screens.settings import SettingsScreen

        await app.push_screen_wait(SettingsScreen())
        await app.saved_settings.save()


class SetFooterAction(ApplicationAction):
    def __init__(self, visible: bool) -> None:
        self.visible = visible

    @classmethod
    def parse(cls, parameters: tuple[object, ...]) -> SetFooterAction:
        match parameters:
            case (bool() as visible,):
                return cls(visible)
        raise ValueError("set_footer requires one boolean")

    async def apply(self, app: ToadApp) -> None:
        app.saved_settings.set(SETTINGS.ui.footer, self.visible)
        await app.saved_settings.save()
        app.notify(
            (
                "Footer shortcut bar shown"
                if self.visible
                else "Footer shortcut bar hidden"
            ),
            title="Interface",
        )


class ToggleFooterAction(ApplicationAction, PaletteAction):
    help = "Toggle the key-shortcut bar at the bottom of Toad"

    def label(self, app: ToadApp) -> str:
        return (
            "Hide footer shortcut bar"
            if app.settings.ui.footer
            else "Show footer shortcut bar"
        )

    async def apply(self, app: ToadApp) -> None:
        await SetFooterAction(not app.settings.ui.footer).apply(app)


class QuitAction(KeyboundAction, ApplicationAction, PaletteAction, MenuAction):
    menu_order = 100
    menu_label = "Exit"
    key = "ctrl+q"
    description = "Quit"
    tooltip = "Quit the app and return to the command prompt."
    priority = True
    help = "Save preferences and quit the application"

    def label(self, app: ToadApp) -> str:
        return "Quit"

    async def apply(self, app: ToadApp) -> None:
        app.application.quit()


class HelpQuitAction(YieldingKey, KeyboundAction, ApplicationAction):
    key = "ctrl+c"
    system = True

    async def apply(self, app: ToadApp) -> None:
        app.application.confirm_quit()


class ToggleHelpPanelAction(KeyboundAction, ApplicationAction, PaletteAction):
    key = "f1"
    description = "Help"
    priority = True
    help = "Toggle help for the focused widget and available keys"

    def label(self, app: ToadApp) -> str:
        return "Hide keys help" if app.screen.query("HelpPanel") else "Show keys help"

    async def apply(self, app: ToadApp) -> None:
        if app.screen.query("HelpPanel"):
            app.action_hide_help_panel()
        else:
            app.action_show_help_panel()


class SessionsAction(KeyboundAction, ApplicationAction, PaletteAction):
    key = "ctrl+s"
    description = "Channels"
    show = True
    help = "Reveal channels and focus the selected session"

    def label(self, app: ToadApp) -> str:
        return "Channels"

    async def apply(self, app: ToadApp) -> None:
        app.run_worker(app.session_navigation.reveal)


class DirectMessagesAction(KeyboundAction, ApplicationAction, PaletteAction):
    """Reach the pairwise message view without changing thread-row navigation."""

    key = "ctrl+shift+d"
    description = "Direct message"
    tooltip = "Open direct messages"
    help = "Open the most recently selected direct conversation"

    def label(self, app: ToadApp) -> str:
        return "Direct messages"

    async def apply(self, app: ToadApp) -> None:
        app.session_navigation.direct_messages()


class VimNavigationAction(VimApplicationAction):
    """Aliases scroll the selected view without moving focus or redirecting input."""

    @staticmethod
    def conversation(app):
        from toad.widgets.conversation import Conversation

        view = app.selected_session
        return None if view is None else view.query_one_optional(Conversation)

    def available(self, app):
        return super().available(app) and self.conversation(app) is not None


class VimScrollDownAction(VimNavigationAction):
    key = "j"

    async def apply(self, app):
        self.conversation(app).window.action_scroll_down()


class VimScrollUpAction(VimNavigationAction):
    key = "k"

    async def apply(self, app):
        self.conversation(app).window.action_scroll_up()


class VimScrollLeftAction(VimNavigationAction):
    key = "h"

    async def apply(self, app):
        self.conversation(app).window.action_scroll_left()


class VimScrollRightAction(VimNavigationAction):
    key = "l"

    async def apply(self, app):
        self.conversation(app).window.action_scroll_right()


class VimPageDownAction(VimNavigationAction):
    key = "ctrl+d"

    async def apply(self, app):
        self.conversation(app).window.action_page_down()


class VimPageUpAction(VimNavigationAction):
    key = "ctrl+u"

    async def apply(self, app):
        self.conversation(app).window.action_page_up()


class VimLatestAction(VimNavigationAction):
    key = "G"

    async def apply(self, app):
        self.conversation(app).jump_to_latest()


class VimFocusPromptAction(VimNavigationAction):
    key = "i"

    async def apply(self, app):
        self.conversation(app).prompt.enter_insert()


class VimNextTabAction(VimNavigationAction):
    key = "J"

    async def apply(self, app):
        app.selected_session.action_session_next()


class VimPreviousTabAction(VimNavigationAction):
    key = "K"

    async def apply(self, app):
        app.selected_session.action_session_previous()


class ApplicationCommands(Provider):
    """Discovery and search derive the same capability view; no command roster."""

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for declaration in ApplicationAction.members_with(PaletteAction):
            command = declaration()
            label = command.label(self.app)
            if score := matcher.match(label):
                yield Hit(
                    score,
                    matcher.highlight(label),
                    partial(command.apply, self.app),
                    help=command.help,
                )

    async def discover(self) -> Hits:
        for declaration in ApplicationAction.members_with(PaletteAction):
            command = declaration()
            yield DiscoveryHit(
                command.label(self.app),
                partial(command.apply, self.app),
                help=command.help,
            )
