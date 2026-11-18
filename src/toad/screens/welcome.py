"""What the workspace shows while no tab is open.

The view is not a tab: the tab order selects it when its last tab closes and
at a launch that named no session to resume. It starts no agent; opening an
entry or a new session opens the first tab, which replaces it.
"""

from __future__ import annotations


from metaclass_registry.mro_dispatch import handles
from agent_comms.messaging.channel_targets import NoChannel
from agent_comms.projects.checkouts import Checkout
from formbridge.key_declarations import TextEntryMode
from textual.app import ComposeResult

from toad.widget_actions import NativeMethodKeys, TogglesIrc, WidgetAction
from textual.containers import VerticalGroup, VerticalScroll
from textual.content import Content
from textual.widgets import Static

from toad.client.application_actions import NewSessionAction as _SharedNewSession
from toad.client.welcome import ChannelListing, ThreadListing, WelcomeListing, WelcomeLocation
from toad.welcome_banner import WelcomeBanner
from toad.client.sidebar_lines import WelcomeSectionLine
from toad.core.events import SessionSelected
from toad.format_path import format_path
from toad.navigation_context import NavigationContext, NavigationOwner
from toad.navigation_target import FeedTarget, NavigationTarget
from toad.navigation_target import channel_target, ThreadTarget
from toad.screens.bus_choice import ListsBuses
from toad.screens.session_view import SessionView
from toad.client.session_scope import ProjectSessionOrigin
from toad.thread_identity import ThreadIdentity
from toad.widgets.comms_sidebar import (
    ChannelRow,
    NewSessionButton,
    ThreadStatusRow,
)
from toad.widgets.sidebar_tree import (
    RowReconciliation,
    SidebarGroup,
    TargetMenuTree,
    GroupTitle,
)
from toad.widgets.splash_text import SplashText
from toad.app_node import ToadNode
from toad.native_style import (
    AutoHeight,
    CenteredChildren,
    FullWidth,
    MutedText,
    NoWrap,
    SpacedAbove,
)
from textual.events import Mount
from textual import on

from toad.sidebar_changes import SidebarChange
from toad.widgets.sidebar_tree import CommsRow, ListedRow


class WelcomeTitle(WelcomeBanner, SplashText, MutedText, NoWrap):
    """The app's name, swept into the theme's colours each time the view shows."""


    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = self.styles.height = "auto"

    @on(Mount)
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


class WelcomeHeading(MutedText, Static):
    """How a title line on the splash looks, declared once.

    The look is MutedText; GroupTitle is the separate fact that a sidebar group's title
    renders from its group and toggles its members on activation. A section whose rows are
    not sidebar-model rows wants the look and not the group - and reusing the group variant
    outside a SidebarGroup raises NoMatches from its own header_group, which is how I found
    out it was two facts in one class.
    """


class WelcomeSectionTitle(WelcomeHeading, GroupTitle):
    """A sidebar-group section's title line on the splash: the look, plus its group."""


class WelcomeSection(WelcomeSectionLine, WelcomeListing, SpacedAbove, SidebarGroup[ListedRow]):
    """Some of the sidebar model's rows under a title."""

    def __init__(self) -> None:
        super().__init__(WelcomeSectionTitle(Content(self.TITLE)), expanded=True)
        # Shown once the model lists something for it.
        self.display = False

    def on_mount(self) -> None:
        self.expanded = self.opens()
        super().on_mount()

    @property
    def section_title(self) -> str:
        return self.TITLE

    @property
    def sidebar_state(self):
        return self.app.sidebar_state

    @property
    def member_keys(self):
        return self.listed(self.query_ancestor(WelcomeEntries).model_state.shown)

    def sync_members(self, changed: frozenset[str]) -> None:
        if not self.member_container.is_attached:
            return
        self.display = bool(self.member_keys)
        self.reconcile_rows(changed=changed)


class WelcomeChannels(ChannelListing, WelcomeSection):
    def new_row(self, key):
        return ChannelRow(channel_target(key), key)

    def show_member(self, key, row):
        channel = self.query_ancestor(WelcomeEntries).model_state.shown.channels.rows[
            key
        ]
        text = self.line_text(channel, self.app.settings.sidebar.unread_counts)
        row.set_label(text.label)
        row.tooltip = text.tooltip
        row.refresh_paint()


class WelcomeThreads(ThreadListing, WelcomeSection):
    def new_row(self, key):
        return ThreadStatusRow(ThreadTarget(key), key)

    def show_member(self, key, row):
        thread = self.query_ancestor(WelcomeEntries).model_state.shown.threads.rows[key]
        row.show(thread)


class WelcomeBuses(SpacedAbove, AutoHeight, ListsBuses, VerticalGroup):
    """The buses this machine can open, on the splash beside its channels and threads.

    Tristan: "I would like it to show the buses as well so that it would list out the buses
    that are available", and then that it "didn't list the other buses on the tailnet". It
    inherits the Open-bus dialog's own listing (ListsBuses), so the rows, the tailnet's
    peers and what choosing one does are the dialog's, not a second set that can drift from
    it - and a bus did not have to become a comms target to get keyboard navigation,
    because BusRows is an OptionList and already has it. The application asks the tailnet
    once per window, so showing the splash again lists its last answer without a sweep.

    Not a WelcomeSection: those read their keys from the sidebar model, and a bus is not in
    it.
    """

    def compose(self) -> ComposeResult:
        yield WelcomeHeading(Content("Buses"))
        yield self.bus_rows()


class WelcomeEntries(FullWidth, AutoHeight, SpacedAbove, TargetMenuTree):
    """New session, channels, threads and buses: the rows the sidebar opens, plus the buses
    this machine can open."""


    def __init__(self) -> None:
        super().__init__()
        self.navigation_groups = (WelcomeChannels(), WelcomeThreads())

    def compose(self) -> ComposeResult:
        yield StartSessionButton()
        yield from self.navigation_groups
        yield WelcomeBuses()

    def accepts_observation(self) -> bool:
        return self.is_attached and self.query_ancestor(WelcomeScreen).is_current

    def row_menu_context(self, row: CommsRow):
        return row.target.menu_context(self, channel=NoChannel())

    @RowReconciliation.sync
    def sync(self, *, change: SidebarChange, reorder: bool = False) -> None:
        channel_list, thread_list = self.navigation_groups
        change.apply_welcome(channel_list, thread_list)

    @handles(SessionSelected)
    async def present_selected(self, event: SessionSelected) -> None:
        self.present()


class WelcomeColumn(AutoHeight, VerticalScroll):
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = 64
        self.styles.max_width = "100%"
        self.styles.max_height = "100%"


class WelcomeNote(MutedText, SpacedAbove, Static):
    """The project line and the key hints."""


class WelcomeLocationNote(WelcomeLocation, WelcomeNote):
    """The welcome's location line (`WelcomeLocation`): the project this TUI works in."""

    def __init__(self, app, project) -> None:
        self.project = project
        super().__init__(self.location_line(app), markup=False)

    def location(self, app) -> str:
        return format_path(self.project)


class WelcomeAction(WidgetAction, affix="Action"):
    """What the welcome view does on its own keys."""


class WelcomeStartSession(WelcomeAction):
    """Textual's welcome binds `n` to a WelcomeAction so the screen's own key system
    picks it up; the body lives on the shared `NewSessionAction` in
    `toad.client.application_actions`, so Qt's Welcome button and this `n` key fire
    the same ClientApplication-owned action."""

    title = "New session"
    keys = {TextEntryMode: ("n",)}
    show = True

    async def apply(self, context: WelcomeScreen) -> None:
        await _SharedNewSession().apply(context.app)


class StartSessionButton(NewSessionButton):
    """The welcome view's New Session is this launch's, as its n key is; the sidebar's
    makes another native thread."""

    action = _SharedNewSession


class WelcomeScreen(
    NativeMethodKeys,
    TogglesIrc,
    NavigationOwner,
    ProjectSessionOrigin,
    CenteredChildren,
    SessionView,
    ToadNode,
    actions=(WelcomeAction,),
    can_focus=False,
):
    AUTO_FOCUS = "WelcomeEntries StartSessionButton"


    def __init__(self) -> None:
        super().__init__()
        app = self.app
        self.project_path = app.project_dir

    def compose(self) -> ComposeResult:
        with WelcomeColumn(can_focus=False):
            yield WelcomeTitle()
            yield WelcomeLocationNote(self.app, self.project_path.path)
            yield WelcomeEntries()
            # Hints come from the app so Qt can supply its own gesture string;
            # see `ToadApp.welcome_hints` / `QtToadApp.welcome_hints`.
            yield WelcomeNote(self.app.welcome_hints)

    @property
    def navigation_context(self) -> NavigationContext:
        assert self.id is not None
        return NavigationContext(
            self.app, self.id, self.project_path, self.thread_identity.thread_name()
        )

    def read_history_identity(self, project: Checkout) -> ThreadIdentity:
        observed = self.app.coordination_access.observation.observed()
        return ThreadIdentity(
            observed.user_identity(project).incarnation, str(observed.root)
        )

    async def prepare_history_origin(self) -> None:
        app = self.app
        project = self.project_path
        with self.changing_identity():
            self._identity = await app.preparation.run_thread(self.read_history_identity, project)

    async def open_sidebar_target(self, target: NavigationTarget) -> None:
        await self.prepare_history_origin()
        await super().open_sidebar_target(target)

    async def prepare_presentation(self) -> None:
        await super().prepare_presentation()
        # The view's frame is written first; the effect is built and played after it.
        title = self.query_one(WelcomeTitle)
        self.screen.frame_presentation.defer(title, title.play)

    async def retire_presentation(self) -> None:
        self.query_one(WelcomeTitle).stop_effect()
        await super().retire_presentation()


    async def toggle_irc(self) -> None:
        await self.open_sidebar_target(FeedTarget())
