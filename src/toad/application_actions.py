"""Textual actions, bindings and palette entries share their declarations."""

from __future__ import annotations

from textual.widgets.text_area import EditingMode, VimMode

from functools import partial
from collections.abc import Iterator
from typing import TYPE_CHECKING, Literal, Self
from textual.command import DiscoveryHit, Hit, Hits, Provider
from agent_comms.nominal.field_codec import FieldCodec
from toad.preferences import SETTINGS
from toad.screens.keymap import KeymapScreen
from toad.keymap import KeyInvocationId
from toad.widget_actions import (
    ApplicationAction,
    ReplacesFrameworkAction,
    System,
    VimWorkspaceAction,
    YieldingKey,
)
from toad.widgets.comms_transfer import Transfer, Transfers
from toad.core.session_requests import SessionNavigate
from toad.sidebar_placement import LeftSidebarEdge, RightSidebarEdge, SidebarEdge

if TYPE_CHECKING:
    from toad.app import ToadApp


# Declaration order is the order of the menu and the palette.
class NewThreadAction(ApplicationAction):
    """Start a thread in the selected project."""

    async def apply(self, app: ToadApp) -> None:
        navigation = app.session_navigation
        navigation.open_thread_form(navigation.selected_project())


class SettingsAction(ApplicationAction):
    """Edit persistent application preferences."""

    keys = {EditingMode: ("ctrl+comma",)}

    async def apply(self, app: ToadApp) -> None:
        app.run_worker(partial(self.edit, app))

    async def edit(self, app: ToadApp) -> None:
        from toad.screens.settings import SettingsScreen

        await app.push_screen_wait(SettingsScreen())
        await app.saved_settings.save()


class TeamAction(ApplicationAction, declared_name="team"):
    """Open the live team board, including teammates' orders and original evidence."""

    keys = {EditingMode: ("f2",)}

    async def apply(self, app: ToadApp) -> None:
        from toad.screens.team import TeamPage

        app.push_screen(TeamPage())


class TransferMenuAction(ApplicationAction):
    """Export wire history or import a thread through Core."""

    def __init__(self, kind: type[Transfer]) -> None:
        self.kind = kind

    @classmethod
    def offered(cls, app: Transfers) -> Iterator[Self]:
        yield from (cls(kind) for kind in Transfer.members_with(Transfer))

    def label(self, app: Transfers) -> str:
        return self.kind.title

    @classmethod
    def parse(cls, parameters: tuple[object, ...]) -> Self:
        if len(parameters) != 1:
            raise ValueError("transfer_menu requires one declared transfer kind")
        return cls(FieldCodec.decode(type[Transfer], parameters[0]))

    async def apply(self, app: Transfers) -> None:
        app.open_transfer(self.kind)


class OpenUrlAction(System, ApplicationAction):
    """Open a link in the user's browser, through the terminal driver like every other link."""

    def __init__(self, url: str) -> None:
        self.url = url

    @classmethod
    def parse(cls, parameters: tuple[object, ...]) -> OpenUrlAction:
        match parameters:
            case (str() as url,):
                return cls(url)
        raise ValueError("open_url requires one URL")

    def apply(self, app: ToadApp) -> None:
        app.open_url(self.url)


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


class HelpQuitAction(ReplacesFrameworkAction, System, YieldingKey, ApplicationAction):
    keys = {EditingMode: ("ctrl+c",)}

    async def apply(self, app: ToadApp) -> None:
        app.application.confirm_quit()


class KeymapAction(ApplicationAction):
    """Browse keyboard shortcuts and change their keys for each editing mode."""

    keys = {EditingMode: ("f1",)}

    async def apply(self, app: ToadApp) -> None:
        focused = frozenset(KeyInvocationId(invocation.key_identity())
                            for node, bindings in app.screen._binding_chain
                            for _key, binding in bindings if binding.state(app, node)
                            for invocation in binding.invocations())
        app.push_screen(KeymapScreen(focused))


class ChannelsAction(ApplicationAction):
    """Reveal channels and focus the selected session."""

    keys = {EditingMode: ("ctrl+s",)}
    show = True

    async def apply(self, app: ToadApp) -> None:
        app.run_worker(app.session_navigation.reveal)


class DirectMessagesAction(ApplicationAction):
    """Open the most recently selected direct conversation."""

    keys = {EditingMode: ("ctrl+shift+d",)}

    async def apply(self, app: ToadApp) -> None:
        app.session_navigation.direct_messages()


class VimCycleTabAction(VimWorkspaceAction, declared_name=None):
    direction: Literal[-1, 1]

    async def apply(self, app: ToadApp) -> None:
        await SessionNavigate(self.direction).apply(app.session_navigation)


class VimNextTabAction(VimCycleTabAction):
    """Select the next tab."""

    keys = {VimMode: ("K",)}
    direction = +1


class VimPreviousTabAction(VimCycleTabAction):
    """Select the previous tab."""

    keys = {VimMode: ("J",)}
    direction = -1


class VimHistoryAction(VimWorkspaceAction, declared_name=None):
    direction: Literal[-1, 1]

    async def apply(self, app: ToadApp) -> None:
        app.tab_order.navigate(self.direction)


class VimHistoryBackAction(VimHistoryAction):
    """Return to the previously visited tab."""
    keys = {VimMode: ("H",)}
    direction = -1


class VimHistoryForwardAction(VimHistoryAction):
    """Go forward through visited tabs."""
    keys = {VimMode: ("L",)}
    direction = +1


class VimSidebarAction(VimWorkspaceAction, declared_name=None):
    side: type[SidebarEdge]

    async def apply(self, app: ToadApp) -> None:
        app.workspace_chrome.toggle_sidebar(self.side)


class VimLeftSidebarAction(VimSidebarAction):
    """Toggle the sidebars on the left edge."""
    keys = {VimMode: ("ctrl+shift+h",)}
    side = LeftSidebarEdge


class VimRightSidebarAction(VimSidebarAction):
    """Toggle the sidebars on the right edge."""
    keys = {VimMode: ("ctrl+shift+l",)}
    side = RightSidebarEdge


class VimMoveTabAction(VimWorkspaceAction, declared_name=None):
    direction: Literal[-1, 1]

    async def apply(self, app: ToadApp) -> None:
        if entry := app.session_navigation.get(app.selected_mode):
            await app.tab_order.move(entry.identity, self.direction)
            app.session_navigation.publish()


class VimMoveTabLeftAction(VimMoveTabAction):
    """Move the selected tab left without selecting another tab."""
    keys = {VimMode: ("ctrl+shift+j",)}
    direction = -1


class VimMoveTabRightAction(VimMoveTabAction):
    """Move the selected tab right without selecting another tab."""
    keys = {VimMode: ("ctrl+shift+k",)}
    direction = +1


class QuitAction(ReplacesFrameworkAction, ApplicationAction):
    """Save preferences and quit the application."""

    keys = {EditingMode: ("ctrl+q",)}

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
