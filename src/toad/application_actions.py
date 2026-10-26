"""Textual actions, bindings and palette entries share their declarations."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING
from textual.command import DiscoveryHit, Hit, Hits, Provider
from agent_comms.field_codec import FieldCodec
from toad.preferences import SETTINGS
from toad.widget_actions import (
    ApplicationAction,
    System,
    VimApplicationAction,
    YieldingKey,
)
from toad.widgets.comms_transfer import TransferRequest
from toad.target_commands import TargetContext
from toad.thread_actions import ThreadAction
from agent_comms.errors import RelationViolationError
from agent_comms.cli_verbs.new import NewThreadCliCommand
from agent_comms.channel_targets import ProjectTarget

if TYPE_CHECKING:
    from toad.app import ToadApp


# Declaration order is the order of the menu and the palette.
class NewThreadAction(ApplicationAction):
    """Start a thread in the selected project."""

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


class SettingsAction(ApplicationAction):
    """Edit persistent application preferences."""

    keys = ("ctrl+comma",)

    async def apply(self, app: ToadApp) -> None:
        app.run_worker(partial(self.edit, app))

    async def edit(self, app: ToadApp) -> None:
        from toad.screens.settings import SettingsScreen

        await app.push_screen_wait(SettingsScreen())
        await app.saved_settings.save()


class TransferMenuAction(ApplicationAction):
    """Export wire history or import a thread through Core."""

    def __init__(self, kind: type[TransferRequest]):
        self.kind = kind

    @classmethod
    def offered(cls, app):
        yield from (cls(kind) for kind in TransferRequest.members_with(TransferRequest))

    def label(self, app: ToadApp) -> str:
        return self.kind.title

    @classmethod
    def parse(cls, parameters):
        if len(parameters) != 1:
            raise ValueError("transfer_menu requires one declared transfer kind")
        return cls(FieldCodec.decode(type[TransferRequest], parameters[0]))

    async def apply(self, app: ToadApp) -> None:
        app.transfers.open(self.kind)


class SetFooterAction(System, ApplicationAction):
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


class ToggleFooterAction(ApplicationAction):
    """Toggle the key-shortcut bar at the bottom of Toad."""

    def label(self, app: ToadApp) -> str:
        return (
            "Hide footer shortcut bar"
            if app.settings.ui.footer
            else "Show footer shortcut bar"
        )

    async def apply(self, app: ToadApp) -> None:
        await SetFooterAction(not app.settings.ui.footer).apply(app)


class HelpQuitAction(System, YieldingKey, ApplicationAction):
    keys = ("ctrl+c",)

    async def apply(self, app: ToadApp) -> None:
        app.application.confirm_quit()


class ToggleHelpPanelAction(ApplicationAction):
    """Toggle help for the focused widget and available keys."""

    keys = ("f1",)
    priority = True

    def label(self, app: ToadApp) -> str:
        return "Hide keys help" if app.screen.query("HelpPanel") else "Show keys help"

    async def apply(self, app: ToadApp) -> None:
        if app.screen.query("HelpPanel"):
            app.action_hide_help_panel()
        else:
            app.action_show_help_panel()


class ChannelsAction(ApplicationAction):
    """Reveal channels and focus the selected session."""

    keys = ("ctrl+s",)
    show = True

    async def apply(self, app: ToadApp) -> None:
        app.run_worker(app.session_navigation.reveal)


class DirectMessagesAction(ApplicationAction):
    """Open the most recently selected direct conversation."""

    keys = ("ctrl+shift+d",)

    async def apply(self, app: ToadApp) -> None:
        app.session_navigation.direct_messages()


class VimNavigationAction(VimApplicationAction):
    """Move through the selected conversation without moving focus or redirecting input."""

    @staticmethod
    def conversation(app):
        from toad.widgets.conversation import Conversation

        view = app.selected_session
        return None if view is None else view.query_one_optional(Conversation)

    def available(self, app):
        return super().available(app) and self.conversation(app) is not None


class VimScrollDownAction(VimNavigationAction):
    keys = ("j",)

    async def apply(self, app):
        self.conversation(app).window.action_scroll_down()


class VimScrollUpAction(VimNavigationAction):
    keys = ("k",)

    async def apply(self, app):
        self.conversation(app).window.action_scroll_up()


class VimScrollLeftAction(VimNavigationAction):
    keys = ("h",)

    async def apply(self, app):
        self.conversation(app).window.action_scroll_left()


class VimScrollRightAction(VimNavigationAction):
    keys = ("l",)

    async def apply(self, app):
        self.conversation(app).window.action_scroll_right()


class VimPageDownAction(VimNavigationAction):
    keys = ("ctrl+d",)

    async def apply(self, app):
        self.conversation(app).window.action_page_down()


class VimPageUpAction(VimNavigationAction):
    keys = ("ctrl+u",)

    async def apply(self, app):
        self.conversation(app).window.action_page_up()


class VimLatestAction(VimNavigationAction):
    keys = ("G",)

    async def apply(self, app):
        self.conversation(app).jump_to_latest()


class VimFocusPromptAction(VimNavigationAction):
    """Focus the prompt, ready to type."""

    keys = ("i",)

    async def apply(self, app):
        self.conversation(app).prompt.enter_insert()


class VimNextTabAction(VimNavigationAction):
    """Select the next tab."""

    keys = ("J",)

    async def apply(self, app):
        app.selected_session.navigate_session(+1)


class VimPreviousTabAction(VimNavigationAction):
    """Select the previous tab."""

    keys = ("K",)

    async def apply(self, app):
        app.selected_session.navigate_session(-1)


class QuitAction(ApplicationAction):
    """Save preferences and quit the application."""

    keys = ("ctrl+q",)
    priority = True

    async def apply(self, app: ToadApp) -> None:
        app.application.quit()


class ApplicationCommands(Provider):
    """Discovery and search derive the same capability view; no command roster."""

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for command, label in ApplicationAction.menu(self.app):
            if score := matcher.match(label):
                yield Hit(
                    score,
                    matcher.highlight(label),
                    partial(command.apply, self.app),
                    help=command.summary(),
                )

    async def discover(self) -> Hits:
        for command, label in ApplicationAction.menu(self.app):
            yield DiscoveryHit(label, partial(command.apply, self.app), help=command.summary())
