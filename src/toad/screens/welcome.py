"""What the workspace shows while no tab is open.

The view is not a tab: the tab order selects it when its last tab closes and
at a launch that named no session to resume. It starts no agent; opening an
entry or a new session opens the first tab, which replaces it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from agent_comms.mro_dispatch import handles
from agent_comms.ui_model.sidebar import SidebarModel
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Static

from toad.constants import ALL_COMMS_TARGET
from toad.core.events import SessionSelected
from toad.core_event_carrier import CoreEventMessage
from toad.format_path import format_path
from toad.navigation_target import FeedTarget, NavigationContext, NavigationOwner, NavigationTarget
from toad.navigation_target import channel_target, ThreadTarget
from toad.screens.session_view import SessionOrigin, SessionView
from toad.widgets.comms_sidebar import CommsRow, NewSessionButton, ThreadStatusRow
from toad.application_actions import NewThreadAction
from toad.widgets.sidebar_tree import RowReconciliation, SidebarGroup, SidebarModelView, TargetTree
from toad.widgets.splash_text import SplashText

if TYPE_CHECKING:
    from toad.app import ToadApp


class WelcomeTitle(SplashText):
    """The app's name, swept into the theme's colours each time the view shows."""

    TEXT = "\n".join((
        " ██████╗ ██████╗ ███╗   ███╗███╗   ███╗███████╗",
        "██╔════╝██╔═══██╗████╗ ████║████╗ ████║██╔════╝",
        "██║     ██║   ██║██╔████╔██║██╔████╔██║███████╗",
        "██║     ██║   ██║██║╚██╔╝██║██║╚██╔╝██║╚════██║",
        "╚██████╗╚██████╔╝██║ ╚═╝ ██║██║ ╚═╝ ██║███████║",
        " ╚═════╝ ╚═════╝ ╚═╝     ╚═╝╚═╝     ╚═╝╚══════╝",
    ))

    DEFAULT_CSS = """
    WelcomeTitle { width: auto; height: auto; color: $text-muted; text-wrap: nowrap; }
    """

    def on_mount(self) -> None:
        self.watch(self.app, "app_focus", self.focus_changed, init=False)

    @property
    def plays(self) -> bool:
        view = self.query_ancestor(WelcomeScreen)
        return self.is_attached and view.is_current and self.app.app_focus

    def focus_changed(self, focused: bool) -> None:
        # An unfocused terminal runs no timer for this view.
        if not focused:
            self.stop_effect()
            self.refresh()


class WelcomeSection(SidebarGroup[CommsRow]):
    """Some of the sidebar model's rows under a title."""

    TITLE = ""
    LIMIT = 8

    DEFAULT_CSS = """
    WelcomeSection { margin: 1 0 0 0; }
    WelcomeSection .section { color: $text-muted; }
    """

    def __init__(self) -> None:
        super().__init__(Static(self.TITLE, classes="section"), expanded=True)
        # Shown once the model lists something for it.
        self.display = False

    def keys(self, model: SidebarModel) -> tuple[str, ...]:
        raise NotImplementedError

    @property
    def member_keys(self):
        model = self.query_ancestor(WelcomeEntries).model_state.shown
        return self.keys(model)[:self.LIMIT]

    def sync_members(self, changed: frozenset[str] | None = None) -> None:
        if not self.member_container.is_attached:
            return
        self.display = bool(self.member_keys)
        self.reconcile_rows(changed=changed)


class WelcomeChannels(WelcomeSection):
    """The channels, in the order chosen for the sidebar."""

    TITLE = "Channels"

    def keys(self, model):
        return tuple(model.channels.rows)

    def new_row(self, key):
        return CommsRow(channel_target(key), key)

    def show_member(self, key, row):
        channel = self.query_ancestor(WelcomeEntries).model_state.shown.channels.rows[key]
        row.set_label(
            f"{channel.label} {channel.unread.label}" if channel.unread.label else channel.label,
        )
        row.tooltip = channel.tooltip
        row.refresh_paint()


class WelcomeThreads(WelcomeSection):
    """The threads of the all-comms channel, in the order chosen for it."""

    TITLE = "Threads"

    def keys(self, model):
        listed = model.channels.rows.get(ALL_COMMS_TARGET)
        return tuple(name for name in (listed.members if listed is not None else ())
                     if name in model.threads.rows)

    def new_row(self, key):
        return ThreadStatusRow(ThreadTarget(key), key)

    def show_member(self, key, row):
        thread = self.query_ancestor(WelcomeEntries).model_state.shown.threads.rows[key]
        row.target = ThreadTarget(key)
        row.show(thread)


class WelcomeEntries(SidebarModelView, TargetTree):
    """New session, channels and threads: the sidebar model's rows, opened as the sidebar opens them."""

    DEFAULT_CSS = """
    WelcomeEntries { width: 100%; height: auto; margin: 1 0 0 0; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.navigation_groups = (WelcomeChannels(), WelcomeThreads())

    def compose(self) -> ComposeResult:
        yield NewSessionButton()
        yield from self.navigation_groups

    async def on_mount(self) -> None:
        app = self.app
        try:
            observed = await app.preparation.run_thread(app.coordination_access.open_current)
            service = observed.service
        except (OSError, ValueError, RuntimeError) as error:
            self.notify(str(error), title="Comms unavailable", severity="error")
            return
        self.attach(observed)

    def accepts_observation(self) -> bool:
        return self.is_attached and self.query_ancestor(WelcomeScreen).is_current

    def accepts_selection(self) -> bool:
        return False  # Rows open; the view keeps no selected set.

    def row_selected(self, row) -> bool:
        return False

    @RowReconciliation.sync
    def sync(self, *, channels: frozenset[str] | None, threads: frozenset[str] | None,
             reorder: bool = False) -> None:
        # A channel change can change which threads are listed and their order.
        channel_list, thread_list = self.navigation_groups
        channel_list.sync_members(channels)
        thread_list.sync_members(threads)

    @handles(SessionSelected)
    async def present_selected(self, event: CoreEventMessage) -> None:
        self.present()


class WelcomeScreen(SessionOrigin, SessionView, NavigationOwner, can_focus=False):
    AUTO_FOCUS = "WelcomeEntries NewSessionButton"

    BINDINGS = [
        Binding("n", "new_session", "New session"),
        Binding("ctrl+g", "toggle_irc", "IRC view"),
    ]

    DEFAULT_CSS = """
    WelcomeScreen { align: center middle; }
    WelcomeScreen > VerticalScroll { width: 64; max-width: 100%; height: auto; max-height: 100%; }
    WelcomeScreen .subtitle { color: $text-muted; margin: 1 0 0 0; }
    WelcomeScreen .hints { color: $text-muted; margin: 1 0 0 0; }
    """

    HINTS = ("[b]n[/b] new session   [b]ctrl+g[/b] channel view   [b]ctrl+b[/b] sidebar\n"
             "[b]↑ ↓[/b] choose   [b]enter[/b] open")

    def __init__(self) -> None:
        super().__init__()
        app = cast("ToadApp", self.app)
        self._agent = app.agent_data
        self.project_path = app.project_dir

    def compose(self) -> ComposeResult:
        agent = f"{self._agent.name} · " if self._agent is not None else ""
        with VerticalScroll(can_focus=False):
            yield WelcomeTitle()
            yield Static(f"{agent}{format_path(self.project_path)}", classes="subtitle", markup=False)
            yield WelcomeEntries()
            yield Static(self.HINTS, classes="hints")

    @property
    def navigation_context(self) -> NavigationContext:
        assert self.id is not None
        return NavigationContext(self.app, self.id, self.project_path, self.thread_identity.thread_name())

    async def open_sidebar_target(self, target: NavigationTarget) -> str:
        app = cast("ToadApp", self.app)
        project = str(self.project_path)
        try:
            from toad.thread_identity import ThreadIdentity
            def identity():
                service = app.coordination_access.open_current().service
                return ThreadIdentity(service.messaging.user_identity(project).incarnation, str(service.root))
            with self.changing_identity():
                self._identity = await app.preparation.run_thread(identity)
        except (OSError, ValueError, RuntimeError) as error:
            self.notify(str(error), title="Comms target unavailable", severity="error")
            return app.selected_mode
        return await super().open_sidebar_target(target)

    async def prepare_presentation(self) -> None:
        await super().prepare_presentation()
        # The view's frame is written first; the effect is built and played after it.
        title = self.query_one(WelcomeTitle)
        self.screen.frame_presentation.defer(title, title.play)

    async def retire_presentation(self) -> None:
        self.query_one(WelcomeTitle).stop_effect()
        await super().retire_presentation()

    async def action_new_session(self) -> None:
        await NewThreadAction().apply(self.app)

    async def action_toggle_irc(self) -> None:
        await self.open_sidebar_target(FeedTarget())
