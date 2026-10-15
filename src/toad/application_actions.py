"""Textual actions, bindings and palette entries share their declarations."""
from __future__ import annotations

from abc import abstractmethod
from functools import partial
from typing import TYPE_CHECKING, ClassVar, Generic, TypeVar

from agent_comms.command import Command
from agent_comms.declared_family import DeclaredFamily
from agent_comms.field_codec import FieldCodec
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider
from toad.preferences import SETTINGS

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
        return Binding(cls.key, FieldCodec.encode(cls), cls.description, tooltip=cls.tooltip,
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


class ApplicationAction(NativeAction, DeclaredFamily, affix="Action"):
    """Application action membership is owned by its declarations."""


class SettingsAction(KeyboundAction, ApplicationAction, PaletteAction):
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
        app.notify("Footer shortcut bar shown" if self.visible else "Footer shortcut bar hidden",
                   title="Interface")


class ToggleFooterAction(ApplicationAction, PaletteAction):
    help = "Toggle the key-shortcut bar at the bottom of Toad"

    def label(self, app: ToadApp) -> str:
        return "Hide footer shortcut bar" if app.settings.ui.footer else "Show footer shortcut bar"

    async def apply(self, app: ToadApp) -> None:
        await SetFooterAction(not app.settings.ui.footer).apply(app)


class QuitAction(KeyboundAction, ApplicationAction, PaletteAction):
    key = "ctrl+q"
    description = "Quit"
    tooltip = "Quit the app and return to the command prompt."
    priority = True
    help = "Save preferences and quit the application"

    def label(self, app: ToadApp) -> str:
        return "Quit"

    async def apply(self, app: ToadApp) -> None:
        app.application.quit()


class HelpQuitAction(KeyboundAction, ApplicationAction):
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


class VimNavigationAction(KeyboundAction, ApplicationAction):
    """Aliases act on the selected view; focus and native input retain custody."""

    @staticmethod
    def conversation(app):
        from toad.widgets.conversation import Conversation
        view = app.selected_session
        return None if view is None else view.query_one_optional(Conversation)

    def available(self, app):
        return (app.settings.ui.vim_keys and app.screen is app.workspace_screen
                and self.conversation(app) is not None)


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
        from textual.widgets.text_area import VimInsert
        conversation = self.conversation(app)
        conversation.prompt.prompt_text_area.editing_mode = VimInsert()
        conversation.focus_prompt(reset_cursor=False, scroll_end=False)


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
                yield Hit(score, matcher.highlight(label), partial(command.apply, self.app),
                          help=command.help)

    async def discover(self) -> Hits:
        for declaration in ApplicationAction.members_with(PaletteAction):
            command = declaration()
            yield DiscoveryHit(command.label(self.app), partial(command.apply, self.app),
                               help=command.help)
