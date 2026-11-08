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

import shlex
from agent_comms.native_arguments import ConfiguredBinary, InheritedArguments
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from agent_comms.ui_model.sidebar import ChannelRowModel
from toad.widget_actions import ActivationKeys
from textual.content import Content
from agent_comms.display_order import ThreadSort
from agent_comms.transport.tools.sidebar import CommsSortChannelTool
from textual.geometry import Offset, Region
from textual.widget import Widget
from textual.reactive import reactive
from ui_theme.effects import NEW_MESSAGE
from textual.widgets import Static
from textual._activation import ContextActivation, PrimaryActivation


from metaclass_registry.mro_dispatch import handles
from toad.core.events import SessionChangedEvent, ThreadIdentityChanged
from toad.core.events import ThreadRowStateChanged, CoordinationObserved
from toad.thread_identity import SessionIdentity
from toad.widgets.thread_identity import ShowsThreadIdentity
from toad.core_event_carrier import CoreEventReceiver
from toad.navigation_target import KnownThreadTarget, NavigationTarget, ThreadTarget, channel_target
from toad.session_tracker import SidebarSelection
from toad.widgets.selection import HoverSelection, ViewLabel
from toad.application_actions import NewThreadAction
from toad.widget_actions import HiddenActions, OpenSelectedAction, OpensSelected
from toad.widgets.session_sort import ChannelListSort, CommsSortChoice, ThreadSortForm
from toad.widgets.sidebar_tree import ActiveSegment, DetailedRow, GroupHeaderLine, HeaderSegment, SelectsTargets, SidebarChange, SidebarGroup, SidebarModelView, SearchFollower, TargetTree, TargetTreeMember, UnpaintedChannel
from toad.tone_paint import AlternatingTone
from toad.textual_colours import ChannelAlternateRowToneColour, ChannelRowToneColour
from toad.widgets.side_bar import SideBar, SideBarCollapsible, SidebarPanelWidget, SidebarVisibilityObserver
from toad.app_node import ToadNode
from toad.native_style import (
    AutoHeight,
    FillWidth,
    MutedText,
    NoPadding,
    OneRow,
    PointerCursor,
)

if TYPE_CHECKING:
    from agent_comms.comms import Comms


class ChannelUnreadSegment(HeaderSegment):
    """The channel's unread count, beside its title; a click opens the channel like the title."""

    def content(self, group: ChannelGroup) -> Content:
        label = group.app.settings.sidebar.unread_counts.badge(group.channel.unread)
        return Content.styled(f" {label}", "$text-muted") if label else Content("")


class ChannelSortSegment(ActiveSegment):
    """The channel's member order; a click opens its menu under this stretch."""

    def content(self, group: ChannelGroup) -> Content:
        return Content.styled(f" {group.sort_choice.sort_label}", "$text-muted")

    async def activate(self, row: GroupHeaderLine) -> None:
        await row.header_group.sort_choice.open_sort()


CHANNEL_SORT = ChannelSortSegment()


class ChannelSortChoice(CommsSortChoice[ThreadSort]):
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

    def order_request(self, order: type[ThreadSort]) -> CommsSortChannelTool:
        return CommsSortChannelTool(name=self.row.target_name, order=order)


class ChannelGroup(SidebarGroup["ThreadRow"]):
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
        if previous.label() != channel.label():
            row.set_label(channel.label())
        row.tooltip = channel.tooltip()
        if row.is_mounted and (previous.active != channel.active or previous.unread != channel.unread):
            row.run_effect(NEW_MESSAGE)
        self.sort_choice.update_order(channel.order)
        if (previous.unread != channel.unread or previous.order is not channel.order
                or previous.summary() != channel.summary()):
            # The badge, the order and the detail line are painted stretches, not layout.
            row.refresh(layout=False)
        return previous.pinned_members ^ channel.pinned_members

    def toggle_members(self) -> None:
        super().toggle_members()
        sidebar = self.sidebar
        sidebar.navigation.state.expanded[self.row.target_name] = self.expanded

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


class CommsRow(
    TargetTreeMember, OpensSelected, PrimaryActivation, ContextActivation, CoreEventReceiver, HoverSelection, ViewLabel,
    scopes={HiddenActions: (OpenSelectedAction,)},
):
    """One interactive row: a channel or a thread."""

    text_fades = (NEW_MESSAGE,)

    @property
    def target_name(self) -> str:
        return self.target.name

    def show_menu(self, sidebar: TargetTree, offset: Offset) -> None:
        sidebar.show_row_menu(self, offset)

    def context_activation(self, offset: Offset) -> None:
        self.show_menu(self.navigation_tree, offset)


    can_focus = True

    def focus_on_click(self) -> bool:
        # Pointer activation navigates; keyboard traversal still owns row focus.
        # Avoid restyling/repainting the departing transcript before Click runs.
        return False

    def __init__(self, target: NavigationTarget, label: str) -> None:
        super().__init__(Content(label))
        self.target = target

    def on_mount(self) -> None:
        self.run_effect(NEW_MESSAGE)

    def is_navigation_row(self) -> bool:
        return self.is_attached and not self.is_leaving

    @property
    def current(self) -> bool:
        return self.is_navigation_row() and self.navigation_tree.row_current(self)

    @property
    def selected(self) -> bool:
        return self.is_navigation_row() and self.navigation_tree.row_selected(self)

    @property
    def paint_highlighted(self) -> bool:
        return self.selected or super().paint_highlighted

    def set_label(self, label: str) -> None:
        self.update(Content(label))

    def expand_members(self, expanded: bool) -> None:
        """A member row lists nobody; a group's header line overrides this."""

    @property
    def primary_activation(self):
        return self.open_selected

    def open_selected(self) -> None:
        self.navigation_tree.remember_row(self)
        self.app.run_worker(
            partial(self.app.workspace_sessions.navigation_owner().open_sidebar_target, self.target),
            group="sidebar-open",
        )

    def on_click(self, event) -> None:
        if event.button == 3:
            event.stop()
            self.context_activation(event.screen_offset)
            return
        if event.ctrl or event.shift:
            event.stop()
            self.navigation_tree.pointer_select(self, control=event.ctrl, shift=event.shift)
            return
        self.open_selected()


class ListedRow(CommsRow, AlternatingTone):
    """A row its list orders: it alternates on its family's tone pair."""


class ChannelRow(ListedRow):
    """A channel's row. Channels alternate on their own hue-stepped pair, so the channel
    list and the thread rows under it read as two families."""

    row_tones = (ChannelRowToneColour, ChannelAlternateRowToneColour)


class ChannelHeaderRow(DetailedRow, GroupHeaderLine, ChannelRow):
    """A channel group's header line: disclosure, the channel's name, unread and order,
    over a second line carrying how many of its agents are up and which tags it covers."""

    def detail(self) -> str:
        return self.header_group.channel.summary()

    def header_lines(self, line: Content) -> Content:
        return self.with_detail(line)


class ThreadStatusRow(MutedText, DetailedRow, NoPadding, PointerCursor, ListedRow, ToadNode):
    """Thread rows show activity through their glyph and summary, not held ink."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.thread_row: ThreadRowModel | None = None
        self.pinned = False
        self.action_status: str | None = None

    @property
    def busy(self) -> bool:
        return self.thread_row is not None and (self.action_status is not None or self.thread_row.status.working)

    def detail(self) -> str:
        """A pending action's own status while one runs, else the thread's summary."""
        if self.thread_row is None:
            return ""
        return self.action_status if self.action_status is not None else self.thread_row.summary

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
        self.tooltip = Content("\n".join(value for value in (
            row.name, self.detail(), row.unread.detail,
            "Pinned in this channel" if pinned else None, *row.model.texts(),
        ) if value))
        shown = self.app.settings.sidebar.unread_counts.badge(row.unread)
        badge = f"{shown} " if shown else ""
        title = self.activity_content(Content(row.label), self.busy,
                                      prefix=Content.assemble(badge, "* " if self.pinned else ""))
        self.update(self.with_detail(title), layout=False)
        if self.is_mounted and previous is not None and (
                previous.status.working != row.status.working or previous.unread != row.unread):
            self.run_effect(NEW_MESSAGE)

    def set_label(self, label: str) -> None:
        self.retire_thread_row()
        super().set_label(label)

    def retire_thread_row(self) -> None:
        self.stop_effect()
        self.thread_row = None


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
        super().__init__("+ New Session")

    @property
    def primary_activation(self):
        return self.create

    async def create(self) -> None:
        await NewThreadAction().apply(self.app)

class CoordinationStatus(
    MutedText,
    NoPadding,
    ShowsThreadIdentity,
    SidebarPanelWidget,
    Static,
):
    """Compact diagnostics for the persistent coordination wire."""


    def identity_changed(self, identity: SessionIdentity) -> None:
        root = identity.display_root()
        backend = ConfiguredBinary().configured()
        self.update(
            Content.assemble(
                "Wire: ",
                (root, "$text"),
                (" · persistent", "$success"),
                f"\nThread: {identity.display_thread()}",
                f"\nACP/session · {Path(backend).name}",
            )
        )
        args = shlex.join(InheritedArguments().configured().argv)
        self.tooltip = (
            "Coordination state persists in the shared wire; the stdio ACP transport "
            "is scoped to this Toad session.\n\n"
            f"AGENT_COMMS_ROOT={identity.root_path}\n"
            f"AGENT_COMMS_AGENT_BIN={backend}\n"
            f"AGENT_COMMS_AGENT_ARGS={args}"
        )




class CommsSidebar(
    AutoHeight,
    SidebarModelView,
    SidebarVisibilityObserver,
    SearchFollower,
    SelectsTargets,
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
        from toad.sidebar_navigation import SidebarNavigation
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

    def show_row_menu(self, row: CommsRow, offset: Offset) -> None:
        self.pointer_select(row, menu=True)
        self.navigation.menu_context(row).show_menu(self, offset)

    def accepts_observation(self) -> bool:
        return (self.enabled and self.accepts_publication()
                and not self.query_ancestor(SideBar).collapsed)

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
                    key, row.target.expanded_by_default))
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
