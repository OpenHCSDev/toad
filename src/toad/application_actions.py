"""Textual actions, bindings and palette entries share their declarations."""
from __future__ import annotations

from abc import abstractmethod
from functools import partial
from typing import TYPE_CHECKING, ClassVar, Generic, TypeVar

from agent_comms.command import Command
from agent_comms.declared_family import DeclaredFamily
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider
from toad.preferences import UiSettings

if TYPE_CHECKING:
    from toad.app import ToadApp


class KeyboundAction:
    key: ClassVar[str]
    description: ClassVar[str] = ""
    tooltip: ClassVar[str] = ""
    show: ClassVar[bool] = False
    priority: ClassVar[bool] = False
    system: ClassVar[bool] = False
    group: ClassVar[Binding.Group | None] = None
    key_display: ClassVar[str | None] = None

    @classmethod
    def binding(cls) -> Binding:
        return Binding(cls.key, cls.declared_name, cls.description, tooltip=cls.tooltip,
                       show=cls.show, priority=cls.priority, system=cls.system,
                       group=cls.group, key_display=cls.key_display)


    @classmethod
    def bindings(cls):
        return (cls.binding(),)


class PaletteAction:
    help: ClassVar[str]

    @abstractmethod
    def label(self, app: ToadApp) -> str: ...


Context = TypeVar("Context")


class NativeAction(Command, Generic[Context]):
    """Only the Textual boundary decodes an external action name."""

    @classmethod
    def parse(cls, parameters: tuple[object, ...]):
        if parameters:
            raise ValueError(f"{cls.declared_name} takes no parameters")
        return cls()

    @classmethod
    def bindings(cls):
        return ()

    def available(self, context: Context) -> bool | None:
        return True

    @abstractmethod
    async def apply(self, context: Context) -> None: ...


class ApplicationAction(NativeAction["ToadApp"], DeclaredFamily, affix="Action"):
    """Application action membership is owned by its declarations."""


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
        from toad.screens.settings import SettingsScreen
        await app.push_screen_wait(SettingsScreen())
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
        UiSettings.footer.toggle(app.settings.ui)
        await SetFooterAction(app.settings.ui.footer).apply(app)


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
