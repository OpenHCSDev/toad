"""Textual actions, bindings and palette entries share their declarations."""
from __future__ import annotations

from abc import abstractmethod
from functools import partial
from typing import TYPE_CHECKING, ClassVar

from agent_comms.command import Command
from agent_comms.declared_family import DeclaredFamily
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider

if TYPE_CHECKING:
    from toad.app import ToadApp


class KeyboundAction:
    key: ClassVar[str]
    description: ClassVar[str] = ""
    tooltip: ClassVar[str] = ""
    show: ClassVar[bool] = False
    priority: ClassVar[bool] = False
    system: ClassVar[bool] = False

    @classmethod
    def binding(cls) -> Binding:
        return Binding(cls.key, cls.declared_name, cls.description, tooltip=cls.tooltip,
                       show=cls.show, priority=cls.priority, system=cls.system)


class PaletteAction:
    help: ClassVar[str]

    @abstractmethod
    def label(self, app: ToadApp) -> str: ...


class ApplicationAction(Command, DeclaredFamily, affix="Action"):
    """Only the Textual boundary decodes an external action name."""

    @classmethod
    def parse(cls, parameters: tuple[object, ...]) -> ApplicationAction:
        if parameters:
            raise ValueError(f"{cls.declared_name} takes no parameters")
        return cls()

    @abstractmethod
    async def apply(self, app: ToadApp) -> None: ...


class SettingsAction(ApplicationAction, KeyboundAction, PaletteAction):
    key = "f2,ctrl+comma"
    description = "Settings"
    tooltip = "Settings screen"
    help = "Edit persistent application preferences"

    def label(self, app: ToadApp) -> str:
        return "Settings"

    async def apply(self, app: ToadApp) -> None:
        app.run_worker(partial(self.edit, app))

    async def edit(self, app: ToadApp) -> None:
        await app.push_screen_wait("settings")
        await app.settings.save()


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
        app.settings.ui.footer = self.visible
        await app.settings.save()
        app.notify("Footer shortcut bar shown" if self.visible else "Footer shortcut bar hidden",
                   title="Interface")


class ToggleFooterAction(ApplicationAction, PaletteAction):
    help = "Toggle the key-shortcut bar at the bottom of Toad"

    def label(self, app: ToadApp) -> str:
        return "Hide footer shortcut bar" if app.settings.ui.footer else "Show footer shortcut bar"

    async def apply(self, app: ToadApp) -> None:
        await SetFooterAction(not app.settings.ui.footer).apply(app)


class QuitAction(ApplicationAction, KeyboundAction, PaletteAction):
    key = "ctrl+q"
    description = "Quit"
    tooltip = "Quit the app and return to the command prompt."
    priority = True
    help = "Save preferences and quit the application"

    def label(self, app: ToadApp) -> str:
        return "Quit"

    async def apply(self, app: ToadApp) -> None:
        app.application.quit()


class HelpQuitAction(ApplicationAction, KeyboundAction):
    key = "ctrl+c"
    system = True

    async def apply(self, app: ToadApp) -> None:
        app.application.confirm_quit()


class ToggleHelpPanelAction(ApplicationAction, KeyboundAction, PaletteAction):
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


class SessionsAction(ApplicationAction, KeyboundAction, PaletteAction):
    key = "ctrl+s"
    description = "Channels"
    show = True
    help = "Reveal channels and focus the selected session"

    def label(self, app: ToadApp) -> str:
        return "Channels"

    async def apply(self, app: ToadApp) -> None:
        app.run_worker(app.session_navigation.reveal)


class ApplicationCommands(Provider):
    """Discovery and search derive the same capability view; no command roster."""

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for declaration in ApplicationAction.members_with(PaletteAction):
            command = declaration()
            label = command.label(self.app)
            if score := matcher.match(label):
                yield Hit(score, matcher.highlight(label), partial(command.apply, self.app),
                          help=command.help)

    async def discover(self) -> Hits:
        for declaration in ApplicationAction.members_with(PaletteAction):
            command = declaration()
            yield DiscoveryHit(command.label(self.app), partial(command.apply, self.app),
                               help=command.help)
