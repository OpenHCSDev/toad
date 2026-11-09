"""What the workspace shows while no tab is open.

The view is not a tab: the tab order selects it when its last tab closes and
at a launch that named no session to resume. It starts no agent; opening an
entry or a new session opens the first tab, which replaces it.
"""

from __future__ import annotations
from abc import abstractmethod


from metaclass_registry.mro_dispatch import handles
from agent_comms.channel_targets import NoChannel
from agent_comms.projects.checkouts import Checkout
from agent_comms.ui_model.sidebar import SidebarModel
from textual.app import ComposeResult
from textual.document._editing import EditingMode
from toad.widget_actions import NativeMethodKeys, TogglesIrc, WidgetAction
from textual.containers import VerticalGroup, VerticalScroll
from textual.geometry import Offset
from textual.content import Content
from textual.widgets import Static

from toad.constants import ALL_COMMS_TARGET
from toad.core.events import SessionSelected
from toad.format_path import format_path
from toad.navigation_context import NavigationContext, NavigationOwner
from toad.navigation_target import FeedTarget, NavigationTarget
from toad.navigation_target import channel_target, ThreadTarget
from toad.screens.bus_choice import BusRows, ListsBuses
from toad.screens.session_view import SessionView
from toad.session_scope import ProjectSessionOrigin
from toad.thread_identity import ThreadIdentity
from toad.widgets.comms_sidebar import (
    ChannelRow,
    NewSessionButton,
    ThreadStatusRow,
)
from toad.widgets.sidebar_tree import (
    RowReconciliation,
    SidebarGroup,
    TargetTree,
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
from toad.sidebar_model_view import SidebarModelView
from toad.widgets.sidebar_tree import CommsRow, ListedRow


class WelcomeTitle(SplashText, MutedText, NoWrap):
    """The app's name, swept into the theme's colours each time the view shows."""


    TEXT = "\n".join(
        (
            " ██████╗ ██████╗ ███╗   ███╗███╗   ███╗███████╗",
            "██╔════╝██╔═══██╗████╗ ████║████╗ ████║██╔════╝",
            "██║     ██║   ██║██╔████╔██║██╔████╔██║███████╗",
            "██║     ██║   ██║██║╚██╔╝██║██║╚██╔╝██║╚════██║",
            "╚██████╗╚██████╔╝██║ ╚═╝ ██║██║ ╚═╝ ██║███████║",
            " ╚═════╝ ╚═════╝ ╚═╝     ╚═╝╚═╝     ╚═╝╚══════╝",
        )
    )

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


class WelcomeSection(SpacedAbove, SidebarGroup[ListedRow]):
    """Some of the sidebar model's rows under a title."""

    TITLE = ""
    LIMIT = 8

    def __init__(self) -> None:
        super().__init__(WelcomeSectionTitle(Content(self.TITLE)), expanded=True)
        # Shown once the model lists something for it.
        self.display = False

    @abstractmethod
    def keys(self, model: SidebarModel) -> tuple[str, ...]:
        ...

    @property
    def member_keys(self):
        model = self.query_ancestor(WelcomeEntries).model_state.shown
        return self.keys(model)[: self.LIMIT]

    def sync_members(self, changed: frozenset[str]) -> None:
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
        return ChannelRow(channel_target(key), key)

    def show_member(self, key, row):
        channel = self.query_ancestor(WelcomeEntries).model_state.shown.channels.rows[
            key
        ]
        badge = self.app.settings.sidebar.unread_counts.badge(channel.unread)
        row.set_label(f"{channel.label()} {badge}" if badge else channel.label())
        row.tooltip = channel.tooltip()
        row.refresh_paint()


class WelcomeThreads(WelcomeSection):
    """The threads of the all-comms channel, in the order chosen for it."""

    TITLE = "Threads"

    def keys(self, model):
        listed = model.channels.rows.get(ALL_COMMS_TARGET)
        return tuple(
            name
            for name in (listed.members if listed is not None else ())
            if name in model.threads.rows
        )

    def new_row(self, key):
        return ThreadStatusRow(ThreadTarget(key), key)

    def show_member(self, key, row):
        thread = self.query_ancestor(WelcomeEntries).model_state.shown.threads.rows[key]
        row.show(thread)


class WelcomeBuses(SpacedAbove, AutoHeight, ListsBuses, VerticalGroup):
    """The buses this machine can open, on the splash beside its channels and threads.

    Tristan: "I would like it to show the buses as well so that it would list out the buses
    that are available". It inherits the Open-bus dialog's own listing (ListsBuses), so the
    rows, the tailnet discovery and what choosing one does are the dialog's, not a second
    set that can drift from it - and a bus did not have to become a comms target to get
    keyboard navigation, because BusRows is an OptionList and already has it.

    Not a WelcomeSection: those read their keys from the sidebar model, and a bus is not in
    it. The rows come from what this machine holds, and the tailnet's arrive after.
    """

    def __init__(self) -> None:
        super().__init__(ListsBuses.offered_rows())

    def compose(self) -> ComposeResult:
        yield WelcomeHeading(Content("Buses"))
        yield BusRows(*self.bus_options())


class WelcomeEntries(FullWidth, AutoHeight, SpacedAbove, SidebarModelView, TargetTree):
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

    def show_row_menu(self, row: CommsRow, offset: Offset) -> None:
        row.target.menu_context(self, channel=NoChannel()).show_menu(self, offset)

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


class WelcomeAction(WidgetAction, affix="Action"):
    """What the welcome view does on its own keys."""


class NewSessionAction(WelcomeAction):
    """Start this launch's session: its attached agent's, or a native thread."""

    title = "New session"
    keys = {EditingMode: ("n",)}
    show = True

    async def apply(self, context: WelcomeScreen) -> None:
        app = context.app
        navigation = app.session_navigation
        await app.agent_binding.start_session(navigation, navigation.selected_project())


class StartSessionButton(NewSessionButton):
    """The welcome view's New Session is this launch's, as its n key is; the sidebar's
    makes another native thread."""

    async def create(self) -> None:
        await NewSessionAction().apply(self.query_ancestor(WelcomeScreen))


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


    HINTS = (
        "[b]n[/b] new session   [b]ctrl+g[/b] channel view   [b]ctrl+b[/b] sidebar\n"
        "[b]↑ ↓[/b] choose   [b]enter[/b] open"
    )

    def __init__(self) -> None:
        super().__init__()
        app = self.app
        self.project_path = app.project_dir

    def compose(self) -> ComposeResult:
        agent = self.app.agent_binding.welcome_prefix
        with WelcomeColumn(can_focus=False):
            yield WelcomeTitle()
            yield WelcomeNote(f"{agent}{format_path(self.project_path.path)}", markup=False)
            yield WelcomeEntries()
            yield WelcomeNote(self.HINTS)

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
