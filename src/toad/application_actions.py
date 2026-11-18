"""The application actions whose bodies need Textual, declared after the shared ones in
`toad.client.application_actions`, and the palette that offers the whole family."""

from __future__ import annotations

from formbridge.key_declarations import TextEntryMode
from textual.widgets.text_area import VimMode

from functools import partial
from collections.abc import Iterator
from typing import TYPE_CHECKING, Literal, Self
from textual.command import DiscoveryHit, Hit, Hits, Provider
from agent_comms.nominal.field_codec import FieldCodec
from toad.preferences import SETTINGS
from toad.client.application_actions import (
    ApplicationAction,
    ReplacesFrameworkAction,
    System,
    YieldingKey,
)
from toad.widget_actions import VimWorkspaceAction
from toad.widgets.comms_transfer import Transfer, Transfers
from toad.core.session_requests import SessionMove, SessionNavigate
from toad.sidebar_placement import LeftSidebarEdge, RightSidebarEdge, SidebarEdge

if TYPE_CHECKING:
    from toad.app import ToadApp


# OpenBusAction, SettingsAction, TeamAction, KeymapAction hoisted to
# `toad.client.application_actions` so Qt's hamburger menu sees them too.
# Their `apply()` bodies dispatch through polymorphic ClientApplication capabilities
# (`open_bus_switcher`, `edit_settings`, `open_team_board`, `open_keymap_browser`);
# Textual's ToadApp (this app.py) overrides each with its push_screen behaviour.
# Members below remain Textual-only because they target the Textual footer / vim
# mode / url driver.


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

    show = True

    def label(self, app: ToadApp) -> str:
        return (
            "Hide footer shortcut bar"
            if app.settings.ui.footer
            else "Show footer shortcut bar"
        )

    async def apply(self, app: ToadApp) -> None:
        await SetFooterAction(not app.settings.ui.footer).apply(app)


class HelpQuitAction(ReplacesFrameworkAction, System, YieldingKey, ApplicationAction):
    keys = {TextEntryMode: ("ctrl+c",)}

    async def apply(self, app: ToadApp) -> None:
        app.application.confirm_quit()


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
        app.session_navigation.events.publish(SessionMove(app.selected_mode, self.direction))


class VimMoveTabLeftAction(VimMoveTabAction):
    """Move the selected tab left without selecting another tab."""
    keys = {VimMode: ("ctrl+shift+j",)}
    direction = -1


class VimMoveTabRightAction(VimMoveTabAction):
    """Move the selected tab right without selecting another tab."""
    keys = {VimMode: ("ctrl+shift+k",)}
    direction = +1


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
