"""Agent-comms channels and remote sessions for Toad's session panel.

IRC semantics for fully-detailed agent threads:

- **Click** a thread row -> opens its DM as a native Toad session.
- **Click** a channel row -> opens that channel as a native Toad session.
- **Right-click** -> context menu: fork, stop, acknowledge, copy name.
- Compact live rows: name, unread badge, and authoritative thread activity.

View, not authority: renders Core's sidebar presentation model
(``agent_comms.ui_model.sidebar``) and acts through ``agent_comms`` operations.
"""

from __future__ import annotations

from agent_comms.ui_model.sidebar import ChannelRowModel, ThreadRowModel
from toad.sidebar_rows import ChannelLineText, ChannelRowFace, ThreadLineText, ThreadRowFace
from toad.client.coordination_panel import CoordinationStateReport, CoordinationStatusView
from toad.widget_actions import ActivationKeys
from textual.content import Content
from agent_comms.display_order import ThreadSort
from toad.client.sort_control import ChannelMemberOrder
from textual.geometry import Region
from textual.widget import Widget
from textual.reactive import reactive
from ui_theme.effects import NEW_MESSAGE
from textual.widgets import Static


from metaclass_registry.mro_dispatch import handles
from toad.core.events import SessionChangedEvent, ThreadIdentityChanged
from toad.thread_identity import SessionIdentity
from toad.widgets.thread_identity import ShowsThreadIdentity
from toad.navigation_target import (
    KnownThreadTarget,
    ThreadTarget,
    channel_target,
)
from toad.client.session_tracker import SidebarSelection
from toad.widgets.selection import HoverSelection
from toad.client.application_actions import NewSessionControl
from toad.widget_actions import OpensSelected
from toad.client.sort_control import ThreadSortForm
from toad.widgets.session_sort import ChannelListSort, CommsSortChoice
from toad.widgets.sidebar_tree import (
    ActiveSegment,
    DetailedRow,
    GroupHeaderLine,
    HeaderSegment,
    SelectsTargets,
    TargetMenuTree,
    SidebarGroup,
    SearchFollower,
    TargetTreeMember,
)
from toad.textual_colours import ChannelAlternateRowToneColour, ChannelRowToneColour
from toad.widgets.side_bar import SideBar, SideBarCollapsible, SidebarPanelWidget, SidebarVisibilityObserver
from toad.app_node import ToadNode
from textual import on
from toad.native_style import (
    AutoHeight,
    FillWidth,
    MutedText,
    NoPadding,
    OneRow,
    PointerCursor,
)
from textual.events import Mount

from toad.sidebar_contracts import ChannelGroupRows, GroupedSidebar
from toad.sidebar_navigation import SidebarNavigation

from toad.widgets.sidebar_tree import CommsRow, ListedRow
from toad.sidebar_changes import SidebarChange
from toad.client.sidebar_models import UnpaintedChannel


class ChannelUnreadSegment(HeaderSegment):
    """The channel's unread count, beside its title; a click opens the channel like the title."""

    def content(self, group: ChannelGroup) -> Content:
        return Content.styled(group.row.badge_stretch(group.row.line_text.badge), "$text-muted")


class ChannelSortSegment(ActiveSegment):
    """The channel's member order; a click opens its menu under this stretch."""

    def content(self, group: ChannelGroup) -> Content:
        return Content.styled(group.row.control_stretch(group.sort_choice.sort_label), "$text-muted")

    async def activate(self, row: GroupHeaderLine) -> None:
        await row.header_group.sort_choice.open_sort()


CHANNEL_SORT = ChannelSortSegment()


class ChannelSortChoice(ChannelMemberOrder, CommsSortChoice[ThreadSort]):
    """A channel's member order, presented by its header line's order stretch."""

    def __init__(self, row: ChannelHeaderRow):
        self.row = row
        super().__init__(ThreadSortForm, row.target_name)

    @property
    def sort_host(self) -> Widget:
        return self.row

    @property
    def sort_anchor(self) -> Region:
        return self.row.segment_region(CHANNEL_SORT)



class ChannelGroup(ChannelGroupRows, SidebarGroup["ThreadRow"]):
    """A view of one channel row of the sidebar model and the thread rows it lists."""
    navigation_header = True
    trailing_segments = (ChannelUnreadSegment(), CHANNEL_SORT)

    def __init__(self, row: ChannelHeaderRow, *, expanded: bool):
        self.channel: ChannelRowModel = UnpaintedChannel(row.target_name)
        self.sort_choice = ChannelSortChoice(row)
        super().__init__(row, expanded=expanded)

    @property
    def sidebar(self) -> CommsSidebar:
        return self.query_ancestor(CommsSidebar)

    def present(self, channel: ChannelRowModel) -> frozenset[str]:
        """Paint the header and return members whose channel pin changed."""
        previous, self.channel = self.channel, channel
        row = self.row
        row.present_channel(channel, counts=self.app.settings.sidebar.unread_counts)
        if row.is_mounted and (previous.active != channel.active or previous.unread != channel.unread):
            row.run_effect(NEW_MESSAGE)
        self.sort_choice.update_order(channel.order)
        if (previous.unread != channel.unread or previous.order is not channel.order
                or previous.summary() != channel.summary()):
            # The badge, the order and the detail line are painted stretches, not layout.
            row.refresh(layout=False)
        return previous.pinned_members ^ channel.pinned_members

    def members_toggled(self) -> None:
        """The channel's open state is the sidebar navigation's, kept by name."""
        self.sidebar.navigation.state.expanded[self.row.target_name] = self.expanded

    def reveal_members(self) -> None:
        if not self.expanded:
            self.toggle_members()

    def rows_changed(self) -> None:
        self.sidebar.navigation.apply()

    def new_row(self, name: str) -> ThreadRow:
        return ThreadRow(ThreadTarget(name), name)

    def show_member(self, name: str, view: ThreadRow) -> None:
        """Paint one member row from its current model row."""
        sidebar = self.sidebar
        channel = self.channel
        view.show(sidebar.model_state.shown.threads.rows[name], pinned=name in channel.pinned_members)

    def accepts_members(self) -> bool:
        """Attached groups may outlive the model while their sidebar is hidden."""
        return super().accepts_members() and self.sidebar.model_state.shows_model()

    @property
    def member_keys(self):
        return self.sidebar.model_state.shown.channels.rows[self.row.target_name].members

    def sync_members(self, changed: frozenset[str]) -> None:
        if not self.member_container.is_attached:
            return  # A new group syncs once composed (on_mount).
        self.reconcile_rows(changed=changed)

    def repaint_members(self, names: frozenset[str]) -> None:
        """Repaint this group's shown rows among the changed threads ``names``.

        Membership is the channel row's fact: added and removed threads change
        its ``members`` and reach ``sync_members`` as a channel change.
        """
        if not self.accepts_members():
            return
        threads = self.sidebar.model_state.shown.threads.rows
        shown = [(name, view) for name in names
                 if (view := self.rows.get(name)) is not None and name in threads]
        for name, view in shown:
            self.show_member(name, view)


class ChannelRow(ListedRow):
    """A channel's row. Channels alternate on their own hue-stepped pair, so the channel
    list and the thread rows under it read as two families."""

    row_tones = (ChannelRowToneColour, ChannelAlternateRowToneColour)


class ChannelHeaderRow(ChannelRowFace, DetailedRow, GroupHeaderLine, ChannelRow):
    """A channel group's header line: disclosure, the channel's name, unread and order,
    over a second line carrying how many of its agents are up and which tags it covers."""

    line_text = ChannelLineText("", "", "", "")

    def show_channel_text(self, text: ChannelLineText) -> None:
        previous, self.line_text = self.line_text, text
        if previous.label != text.label:
            self.set_label(text.label)
        self.tooltip = text.tooltip

    def detail(self) -> str:
        return self.line_text.summary

    def header_lines(self, line: Content) -> Content:
        return self.with_detail(line)


class ThreadStatusRow(ThreadRowFace, MutedText, DetailedRow, NoPadding, PointerCursor, ListedRow, ToadNode):
    """Thread rows show activity through their glyph and summary, not held ink."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.thread_row: ThreadRowModel | None = None
        self.pinned = False
        self.action_status: str | None = None

    @property
    def busy(self) -> bool:
        return self.thread_row is not None and self.thread_busy(self.thread_row, self.action_status)

    line_text: ThreadLineText | None = None

    def detail(self) -> str:
        """The shared line text's second row (ThreadRowFace); none before the first paint."""
        if self.thread_row is None or self.line_text is None:
            return ""
        return self.line_text.detail

    def show(self, row: ThreadRowModel, *, pinned: bool = False) -> None:
        """Render the model with this app's pin and pending action."""
        app = self.app
        row = app.session_navigation.thread_row(row)
        action_status = app.thread_actions.pending.get(row.name)
        if (row, pinned, action_status) == (self.thread_row, self.pinned, self.action_status):
            return
        previous = self.thread_row
        self.thread_row, self.pinned, self.action_status = row, pinned, action_status
        # The drawn row knows the thread's birth: opening it asks Core nothing first.
        self.target = KnownThreadTarget(row.name, row.incarnation)
        self.present_thread(row, pinned=pinned, action_status=action_status,
                            counts=app.settings.sidebar.unread_counts)
        if self.is_mounted and previous is not None and (
                previous.status.is_working() != row.status.is_working() or previous.unread != row.unread):
            self.run_effect(NEW_MESSAGE)

    def show_thread_text(self, text: ThreadLineText) -> None:
        self.line_text = text
        self.tooltip = Content(text.tooltip)
        title = self.activity_content(Content(text.name), self.busy, prefix=Content(text.prefix))
        self.update(self.with_detail(title), layout=False)

    def set_label(self, label: str) -> None:
        self.retire_thread_row()
        super().set_label(label)

    def retire_thread_row(self) -> None:
        self.stop_effect()
        self.thread_row = None

    def redraw(self) -> None:
        # The name wave paints only the label line (ViewLabel.render_line, y == 0). A finished
        # effect stays in self.effects, so ask each effect whether it is still in motion.
        # While the wave is the only one moving, repaint its line; a moving text fade paints every line.
        wave_only = self.effect_phase(self.name_wave).in_motion and not any(
            self.effect_phase(fade).in_motion for fade in self.text_fades)
        if wave_only:
            self.repaint_region(Region(0, 0, self.size.width, 1))
            return
        super().redraw()


class ThreadRow(ThreadStatusRow):
    """A retained wire thread row, with an optional currently open native view."""

    def open_selected(self) -> None:
        """Select the tab that already shows this thread; open the thread when none does."""
        app = self.app
        entries = {entry.mode: entry for entry in app.session_navigation.members}
        mode = self.navigation_tree.open_views.get(self.target_name, "")
        if mode in entries and entries[mode].identity in app.session_tracker.sessions:
            self.navigation_tree.remember_row(self)
            app.select_session(mode)
        else:
            super().open_selected()


class NewSessionButton(
    NewSessionControl,
    MutedText,
    FillWidth,
    OneRow,
    NoPadding,
    PointerCursor,
    HoverSelection,
    ActivationKeys,
    TargetTreeMember,
    Static,
):
    """Create another agent session for the current project."""


    can_focus = True

    def __init__(self) -> None:
        super().__init__(self.label)

    @property
    def primary_activation(self):
        return self.create

    async def create(self) -> None:
        await self.start_session(self.app)

class CoordinationStatus(
    CoordinationStatusView,
    MutedText,
    NoPadding,
    ShowsThreadIdentity,
    SidebarPanelWidget,
    Static,
):
    """Compact diagnostics for the persistent coordination wire."""


    def show_report(self, report: CoordinationStateReport) -> None:
        # Textual adds colour to the wire root and the persistence label; both renderers
        # assemble from the same report so the facts are owned once, in one place.
        self.update(
            Content.assemble(
                "Wire: ",
                (report.wire_root, "$text"),
                (" · persistent", "$success"),
                f"\nThread: {report.thread_name}",
                f"\nACP/session · {report.backend_name}",
            )
        )
        self.tooltip = report.tooltip_text()




class CommsSidebar(
    AutoHeight,
    TargetMenuTree,
    SidebarVisibilityObserver,
    SearchFollower,
    SelectsTargets,
    GroupedSidebar,
    OpensSelected,
):
    """The view of the observed service's sidebar model: channel groups and their threads.

    It mounts or removes groups and rows only for added and removed keys,
    repaints only changed rows and reorders on a changed order. Which tab has a
    thread open and pending thread actions are this view's own UI state.
    """
    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.padding = (0, 0, 1, 0)

    GROUP_MOUNT = "sidebar-groups"
    selected: reactive[str] = reactive("", init=False)
    def __init__(self, *, observe: bool = True, **kwargs):
        super().__init__(**kwargs)
        self.can_focus = True
        self.navigation = SidebarNavigation(self)
        self.enabled = observe
        self.groups: dict[str, ChannelGroup] = {}
        # Creates and mounts the model's channel groups this view lacks.
        self._group_mounting = None
        self.new_session: NewSessionButton | None = None
        # Thread name -> the mode of the tab that has it open.
        self.open_views: dict[str, str] = {}

    def accepts_publication(self) -> bool:
        """The mounted widget owns the legality of writing its presentation."""
        return (self.is_attached and not self.is_leaving
                and self.app.is_running and self.screen.is_current)

    def row_menu_context(self, row: CommsRow):
        return self.navigation.menu_context(row)

    def accepts_observation(self) -> bool:
        return (self.enabled and self.accepts_publication()
                and not self.query_ancestor(SideBar).collapsed)

    @on(Mount)
    async def on_mount(self) -> None:
        app = self.app
        self.subscribe_core(app.session_tracker.events)
        await self.navigation.prepare()
        self.screen.start_sidebar_navigation(self)

    def bind_observation(self, observed) -> None:
        if not self.screen.belongs_to_wire(observed.root):
            self.display = False
            return
        super().bind_observation(observed)

    def stop_mounting(self) -> None:
        self.workers.cancel_group(self, self.GROUP_MOUNT)
        self._group_mounting = None

    def sidebar_visibility_changed(self) -> None:
        self.stop_mounting()
        super().sidebar_visibility_changed()

    def model_replaced(self) -> None:
        self.stop_mounting()
        self.display = False
        self.navigation.reset()
        if self.groups:
            self.remove_children(list(self.groups.values()))
            self.groups.clear()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.present()

    def sync(self, *, change: SidebarChange, reorder: bool = False) -> None:
        """Apply the changed rows without rebuilding other groups' members."""
        model = self.model_state.shown
        rows = model.channels.rows
        if self.new_session is None:
            self.new_session = NewSessionButton()
            self.mount(self.new_session)
        removed = [key for key in self.groups if key not in rows]
        if removed:
            self.remove_children([self.groups.pop(key) for key in removed])
        added = any(key not in self.groups for key in rows)
        change.apply_comms(self, rows)
        if self._group_mounting is None or self._group_mounting.is_finished:
            if added:
                self._group_mounting = self.run_worker(self._mount_groups(), group=self.GROUP_MOUNT)
            elif removed or reorder:
                self.order_groups()
        panel = self.query_ancestor(SideBarCollapsible)
        control = panel.header_control
        assert isinstance(control, ChannelListSort)
        control.update_order(model.observation.channel_order())
        change.apply_navigation(self)
        self.display = True
        if not self.navigation.ready.is_set() and self.screen.is_current:
            self.call_after_refresh(self.navigation.finish, self.navigation.revision)

    async def _mount_groups(self) -> None:
        """Create and mount the model's channel groups this view lacks, one at a time, in model order.

        Each group builds its header and member rows in loop turns of its
        own; built together, every group would be built in the same turn.
        The mounted groups are ordered once per pass, not after each mount.
        """
        while self.is_attached:
            missing = [key for key in self.model_state.shown.channels.rows if key not in self.groups]
            if not missing:
                self.order_groups()
                return
            for key in missing:
                rows = self.model_state.shown.channels.rows
                if key not in rows or key in self.groups or not self.is_attached:
                    continue  # Removed or mounted while the previous group mounted.
                row = ChannelHeaderRow(channel_target(key), key)
                group = self.groups[key] = ChannelGroup(row, expanded=self.navigation.state.expanded.get(
                    key, row.opens_expanded()))
                group.present(rows[key])  # Its members sync once it is mounted.
                await self.mount(group)

    @property
    def member_keys(self):
        return (key for channel in self.model_state.shown.channels.rows.values() for key in channel.members)

    def order_groups(self) -> None:
        """Order the groups admitted by sync; removed channels retire before member work."""
        groups = tuple(self.groups[key] for key in self.model_state.shown.channels.rows if key in self.groups)
        for index, group in enumerate(groups):
            group.row.place(index)
        ordered = (self.new_session, *groups)
        live = tuple(child for child in self.children if not child.is_leaving)
        if live != ordered:
            positions = {widget: index for index, widget in enumerate(ordered)}
            self.sort_children(key=lambda child: positions.get(child, len(positions)))
        self.navigation.apply()

    def find_open_views(self) -> dict[str, str]:
        """Which open tab shows each thread of this service; the first tab claims it."""
        app = self.app
        threads = self.model_state.shown.threads.rows
        views: dict[str, str] = {}
        for details in app.session_tracker.ordered_sessions:
            screen = app.session_navigation.source(details.mode_name)
            if screen is None:
                continue
            name = screen.thread_identity.thread_name()
            if (name in threads and name not in views
                    and screen.belongs_to_wire(self.navigation_root)):
                views[name] = details.mode_name
        return views

    @handles(SessionChangedEvent, ThreadIdentityChanged)
    async def session_changed(self, event: SessionChangedEvent | ThreadIdentityChanged) -> None:
        self.open_views = self.find_open_views()

    @property
    def navigation_groups(self):
        return (group for key in self.model_state.shown.channels.rows
                if (group := self.groups.get(key)) is not None and not group.is_leaving)

    @property
    def selection_state(self):
        return self.navigation.state

    def selection_for(self, row):
        return SidebarSelection(row.query_ancestor(ChannelGroup).row.target_name, row.target_name)

    def accepts_selection(self) -> bool:
        return not self.navigation.restoring

    def row_for(self, selection):
        group = self.groups.get(selection.channel)
        if group is None or not group.accepts_navigation():
            return None
        return group.row if selection.target == selection.channel else group.rows.get(selection.target) if group.members_visible else None
