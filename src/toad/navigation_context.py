"""Navigation context and its owning capability, without UI imports."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from agent_comms.projects.checkouts import Checkout
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from toad.app import ToadApp


@dataclass(frozen=True)
class NavigationContext:
    app: ToadApp
    owner_mode: str
    project_path: Checkout
    actor: str


class NavigationDestination(ABC):
    """What a navigating view opens: each sidebar row's target."""

    def selected(self, owner: NavigationOwner) -> None:
        """Apply view-specific selection intent before beginning navigation."""

    @abstractmethod
    async def open(self, context: NavigationContext) -> str: ...


class NavigationScope:
    """An ancestor its descendants open targets through."""

    @property
    @abstractmethod
    def navigation_owner(self) -> NavigationOwner: ...


class NavigationOwner:
    """A view that navigates: it supplies context, targets supply behavior, App owns execution.

    Only a navigating view shows the shared channels sidebar, and that sidebar's rows
    open through it.
    """

    shows_channels = True

    @property
    def navigation_owner(self) -> NavigationOwner:
        return self

    @property
    @abstractmethod
    def navigation_context(self) -> NavigationContext: ...

    _last_direct: NavigationDestination | None = None
    """The direct conversation this view last opened, for "open my last DM" (Ctrl+Shift+D)."""

    def remember_direct_target(self, target: NavigationDestination) -> None:
        """A direct conversation was selected in this view: it is the one the next
        "open the last DM" returns to. (Textual's main screen kept the name and opened it;
        Qt's views said the command was unavailable, with the same key bound.)"""
        self._last_direct = target

    async def open_sidebar_target(self, target: NavigationDestination) -> None:
        target.selected(self)
        await target.open(self.navigation_context)

    @property
    def navigation_app(self) -> ToadApp:
        """The app this owner's notices go to."""
        return self.navigation_context.app

    async def open_direct_messages(self) -> None:
        """Open the direct conversation this view last opened; say so when it has none."""
        if self._last_direct is None:
            self.navigation_app.show_info(
                "Choose Direct messages from an agent's context menu", "Direct messages"
            )
            return
        await self.open_sidebar_target(self._last_direct)


class NavigationUnavailable(RuntimeError):
    """Navigation was asked for while no navigating view is selected."""


class NoNavigationOwner(NavigationOwner):
    """The owner the workspace answers while no navigating view is selected: a file preview, or
    no view at all. It refuses instead of reaching a closed view.
    """

    shows_channels = False

    def __init__(self, app: ToadApp) -> None:
        self.app = app

    @property
    def navigation_app(self) -> ToadApp:
        return self.app

    @property
    def navigation_context(self) -> NavigationContext:
        raise NavigationUnavailable("No navigating view is selected")

    async def open_sidebar_target(self, target: NavigationDestination) -> None:
        """A target asked of no navigating view is refused with a notice, not a traceback."""
        self.app.show_info("Nothing opens from this view", "Navigation")

    async def open_direct_messages(self) -> None:
        """No view here has a direct conversation to return to, nor ever opened one."""
        self.app.show_info("Direct messages are unavailable from this view", "Direct messages")


class HomeNavigation(NavigationOwner):
    """Home (the welcome, while no tab is open) navigates as the reader at home: the
    welcome's mode, its project and the reader's own thread. Textual's `WelcomeScreen` and
    Qt's `QtWelcomeOrigin`."""

    @property
    def navigation_context(self) -> NavigationContext:
        from toad.constants import WELCOME
        return NavigationContext(self.app, WELCOME, self.project_path, self.thread_identity.thread_name())

    async def open_sidebar_target(self, target: NavigationDestination) -> None:
        """Home reads who the reader is, off the loop, before it opens anything
        (`HomeSessionOrigin.prepare_history_origin`, which every class of this family also
        inherits: Textual's `WelcomeScreen` wrote this and Qt's origin did not, and read the
        identity on the GUI thread instead)."""
        await self.prepare_history_origin()
        await super().open_sidebar_target(target)


class ThreadViewNavigation:
    """A view showing one thread navigates as that thread: its target is the thread, and
    what it opens attaches to the view's own tab, in its project, acting as the thread.
    Textual's `MainScreen` and Qt's `QtThreadView` both inherit this, so a thread's
    configuration actions (model, thinking level, service tier) reach both."""

    @property
    @abstractmethod
    def navigation_mode(self) -> str:
        """The tab this view is."""

    @property
    @abstractmethod
    def navigation_project(self) -> Checkout:
        """The project the view's thread works in."""

    @property
    def navigation_target(self):
        from toad.navigation_target import ThreadTarget
        return ThreadTarget(self.thread_identity.thread_name())

    @property
    def navigation_context(self) -> NavigationContext:
        return NavigationContext(self.app, self.navigation_mode, self.navigation_project,
                                 self.thread_identity.thread_name())


class ConversationViewNavigation:
    """A conversation tab (a channel's history) navigates as its conversation: its target is
    the conversation's history destination, and what it opens attaches to home (no session
    owns the tab). Textual's `CommsChatView` and Qt's `ConversationView` both inherit this, so
    a channel's configuration actions reach both."""

    @property
    @abstractmethod
    def navigation_project(self) -> Checkout:
        """The project the tab's threads work in."""

    @property
    def navigation_target(self):
        from toad.navigation_target import HistoryTarget
        names = self.app.coordination_access.observation.observed().sidebar.observation.thread_names()
        return HistoryTarget.for_conversation(self.conversation, names)

    @property
    def navigation_context(self) -> NavigationContext:
        from toad.constants import WELCOME
        return NavigationContext(self.app, WELCOME, self.navigation_project,
                                 self.thread_identity.thread_name())
