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
from typing import TYPE_CHECKING, cast

from agent_comms.ui_model.sidebar import ChannelRowModel
from textual.binding import Binding
from textual._cells import cell_len
from textual.content import Content
from textual.geometry import Offset
from textual.reactive import reactive
from ui_theme.effects import NEW_MESSAGE
from textual.widgets import Static
from textual._activation import PrimaryActivation
from ui_theme.scheme import AlternateRowToneColour


from agent_comms.mro_dispatch import handles
from toad.core.events import SessionChangedEvent, ThreadIdentityChanged
from toad.core.events import ThreadRowStateChanged, CoordinationObserved
from toad.thread_identity import SessionIdentity
from toad.widgets.thread_identity import ShowsThreadIdentity
from toad.core_event_carrier import CoreEventReceiver
from toad.navigation_target import channel_target, ThreadTarget
from toad.session_tracker import SidebarSelection
from toad.widgets.selection import ChangingText, HoverSelection, ViewLabel
from toad.application_actions import NewThreadAction
from toad.widgets.session_sort import ChannelListSort, SessionSort
from toad.widgets.sidebar_tree import SidebarChange, SidebarGroup, SidebarModelView, SearchFollower, TargetTree, TargetTreeMember, UnpaintedChannel
from toad.widgets.side_bar import SideBar, SideBarCollapsible, SidebarPanelWidget, SidebarVisibilityObserver
from toad.navigation_target import NavigationTarget

if TYPE_CHECKING:
    from agent_comms.comms import Comms
    from toad.app import ToadApp




class ChannelUnread(PrimaryActivation, ChangingText):
    DEFAULT_CSS = "ChannelUnread { width: auto; height: 1; color: $text-muted; pointer: pointer; }"
    text_fades = (NEW_MESSAGE,)

    def on_click(self, event) -> None:
        if event.button == 1:
            event.stop()
            self.primary_activation()

    @property
    def primary_activation(self):
        return self.query_ancestor(ChannelGroup).row.action_open_selected


class ChannelGroup(SidebarGroup["ThreadRow"]):
    """A view of one channel row of the sidebar model and the thread rows it lists."""
    navigation_header = True
    def __init__(self, row: CommsRow, *, expanded: bool):
        self.channel: ChannelRowModel = UnpaintedChannel(row.target_name)
        self.sort_control = SessionSort(channel=row.target_name)
        self.unread_badge = ChannelUnread(markup=False)
        self.unread_badge.display = False
        super().__init__(row, expanded=expanded,
                         controls=(self.unread_badge, self.sort_control))

    @property
    def sidebar(self) -> CommsSidebar:
        return self.query_ancestor(CommsSidebar)

    def present(self, channel: ChannelRowModel) -> None:
        """Paint the channel header from its model row."""
        previous, self.channel = self.channel, channel
        row = self.row
        if previous.label != channel.label:
            row.set_label(channel.label)
        row.tooltip = channel.tooltip
        if row.is_mounted and (previous.active != channel.active or previous.unread != channel.unread):
            row.run_effect(NEW_MESSAGE)
        if previous.unread != channel.unread:
            label = channel.unread.label
            # Equal-width badges need paint only; visibility owns its layout.
            width_changed = cell_len(label) != cell_len(previous.unread.label)
            self.unread_badge.update(label, layout=width_changed)
            self.unread_badge.display = bool(label)
        self.sort_control.update_order(channel.order)

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


class CommsRow(TargetTreeMember, PrimaryActivation, CoreEventReceiver, HoverSelection, ViewLabel):
    """One interactive row: a channel or a thread."""

    text_fades = (NEW_MESSAGE,)
    alternate: reactive[bool] = reactive(False, repaint=False)

    def watch_alternate(self) -> None:
        self.refresh_paint()

    @property
    def tone(self):
        return AlternateRowToneColour if self.alternate else None

    @property
    def target_name(self) -> str:
        return self.target.name

    def show_menu(self, sidebar: TargetTree, offset: Offset) -> None:
        sidebar.show_row_menu(self, offset)



    BINDINGS = [
        Binding("down", "cursor_down", "Next", show=False),
        Binding("up", "cursor_up", "Previous", show=False),
        Binding("enter", "open_selected", "Open", show=False),
    ]

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

    @property
    def primary_activation(self):
        return self.action_open_selected

    def action_open_selected(self) -> None:
        self.navigation_tree.remember_row(self)
        self.app.run_worker(
            partial(self.app.selected_session.open_sidebar_target, self.target),
            group="sidebar-open",
        )

    def on_click(self, event) -> None:
        if event.button == 3:
            event.stop()
            self.show_menu(self.navigation_tree, event.screen_offset)
            return
        if event.ctrl or event.shift:
            event.stop()
            self.navigation_tree.pointer_select(self, control=event.ctrl, shift=event.shift)
            return
        self.action_open_selected()


class ThreadStatusRow(CommsRow):
    """Thread rows show activity through their glyph and summary, not held ink."""

    DEFAULT_CSS = "ThreadStatusRow { color: $text-muted; }"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.styles.height = 2
        self.styles.padding = 0
        self.styles.text_wrap = "nowrap"
        self.styles.text_overflow = "ellipsis"
        self.styles.pointer = "pointer"
        self.thread_row: ThreadRowModel | None = None
        self.pinned = False
        self.action_status: str | None = None

    @property
    def busy(self) -> bool:
        return self.thread_row is not None and (self.action_status is not None or self.thread_row.status.working)

    def show(self, row: ThreadRowModel, *, pinned: bool = False) -> None:
        """Render the model with this app's pin and pending action."""
        app = cast("ToadApp", self.app)
        row = app.session_navigation.thread_row(row)
        action_status = app.thread_actions.pending.get(row.name)
        if (row, pinned, action_status) == (self.thread_row, self.pinned, self.action_status):
            return
        previous = self.thread_row
        self.thread_row, self.pinned, self.action_status = row, pinned, action_status
        summary = action_status if action_status is not None else row.summary
        self.tooltip = Content("\n".join(value for value in (
            row.name, summary, row.unread.detail, "Pinned in this channel" if pinned else None, *row.model.texts(),
        ) if value))
        badge = f"{row.unread.label} " if row.unread.label else ""
        title = self.activity_content(row.title, Content(row.label), self.busy,
                                      prefix=Content.assemble(badge, "* " if self.pinned else ""))
        self.update(Content.assemble(title, f"\n  {summary}"), layout=False)
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

    @property
    def mode_name(self) -> str | None:
        return self.navigation_tree.open_views.get(self.target_name)

    def action_open_selected(self) -> None:
        if self.mode_name is None or cast("ToadApp", self.app).session_navigation.session_details(self.mode_name) is None:
            super().action_open_selected()
        else:
            self.navigation_tree.remember_row(self)
            self.app.select_session(self.mode_name)


class NewSessionButton(HoverSelection, TargetTreeMember, Static):
    """Create another agent session for the current project."""

    DEFAULT_CSS = """
    NewSessionButton {
        width: 1fr;
        height: 1;
        padding: 0;
        color: $text-muted;
        pointer: pointer;
    }
    """

    can_focus = True
    BINDINGS = [
        Binding("enter", "create", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("up", "cursor_up", show=False),
    ]

    def __init__(self) -> None:
        super().__init__("+ New Session")

    async def action_create(self) -> None:
        await NewThreadAction().apply(self.app)

    async def on_mouse_up(self, event) -> None:
        if event.button == 1:
            await self.action_create()


class CoordinationStatus(ShowsThreadIdentity, SidebarPanelWidget, Static):
    """Compact diagnostics for the persistent coordination wire."""

    DEFAULT_CSS = """
    CoordinationStatus {
        height: auto;
        padding: 0;
        color: $text-muted;
    }
    """

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
            f"AGENT_COMMS_ROOT={identity.root_path()}\n"
            f"AGENT_COMMS_AGENT_BIN={backend}\n"
            f"AGENT_COMMS_AGENT_ARGS={args}"
        )




class CommsSidebar(SidebarModelView, SidebarVisibilityObserver, SearchFollower, TargetTree):
    """The view of the observed service's sidebar model: channel groups and their threads.

    It mounts or removes groups and rows only for added and removed keys,
    repaints only changed rows and reorders on a changed order. Which tab has a
    thread open and pending thread actions are this view's own UI state.
    """
    DEFAULT_CSS = """
    CommsSidebar { height: auto; padding: 0 0 1 0; }
    CommsSidebar .section { color: $text-muted; padding: 1 0 0 0; }
    CommsSidebar .row-name { color: $text; }
    CommsSidebar .row-detail { color: $text-muted; }
    """
    BINDINGS = [("up", "cursor_up", "Previous"), ("down", "cursor_down", "Next"),
                ("enter", "open_selected", "Open")]
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
        if not self.screen.belongs_to_wire(observed.service.root):
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
                row = CommsRow(channel_target(key), key)
                group = self.groups[key] = ChannelGroup(row, expanded=self.navigation.state.expanded.get(
                    key, row.target.expanded_by_default))
                group.present(rows[key])  # Its members sync once it is mounted.
                await self.mount(group)

    @property
    def member_keys(self):
        return (key for channel in self.model_state.shown.channels.rows.values() for key in channel.members)

    def order_groups(self) -> None:
        """Order the groups admitted by sync; removed channels retire before member work."""
        ordered = (self.new_session, *(self.groups[key] for key in self.model_state.shown.channels.rows if key in self.groups))
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
