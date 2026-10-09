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
from toad.core.input_events import SelectTarget
from toad.core_event_carrier import CoreEventMessage
from toad.core import session_requests

import os
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, cast

from agent_comms.ui_model.changes import Changes
from agent_comms.ui_model.sidebar import ChannelRowModel, SidebarModel
from textual.binding import Binding
from textual._cells import cell_len
from textual.content import Content
from textual.dom import DOMNode
from textual.reactive import reactive
from textual.widgets import Static


from agent_comms.mro_dispatch import handles
from toad.core.events import SessionChangedEvent
from toad.core.events import SessionSelected, ThreadActionsChanged, CoordinationObserved
from toad.core_event_carrier import CoreEventReceiver
from toad.navigation_target import NavigationOwner, channel_target, thread_target
from toad.widgets.session_sidebar import ThreadStatusRow
from toad.widgets.session_sort import SessionSort
from toad.widgets.sidebar_tree import SidebarDisclosure, SidebarGroup, TargetTree
from toad.widgets.side_bar import SidebarVisibilityObserver
from toad.navigation_target import NavigationTarget

if TYPE_CHECKING:
    from agent_comms.comms import Comms
    from toad.app import ToadApp




class ChannelDisclosure(SidebarDisclosure):
    pass


class ChannelUnread(Static):
    DEFAULT_CSS = "ChannelUnread { width: auto; height: 1; color: $accent; pointer: pointer; }"

    def on_click(self, event) -> None:
        if event.button == 1:
            event.stop()
            self.query_ancestor(ChannelGroup).row.action_open_selected()


class ChannelGroup(SidebarGroup):
    """A view of one channel row of the sidebar model and the thread rows it lists."""
    DEFAULT_CSS = """
    ChannelGroup { height: auto; }
    ChannelGroup > HorizontalGroup { height: 1; }
    ChannelGroup .channel-header { height: 1; width: 1fr; text-wrap: nowrap; text-overflow: ellipsis; }
    ChannelGroup .channel-members { height: auto; margin-left: 2; }
    """

    def __init__(self, row: CommsRow, *, expanded: bool):
        row.add_class("channel-header")
        self.members: dict[str, ThreadRow] = {}
        self.channel: ChannelRowModel | None = None
        self.sort_control = SessionSort(channel=row.target_name)
        self.unread_badge = ChannelUnread(markup=False)
        self.unread_badge.display = False
        super().__init__(row, expanded=expanded,
                         controls=(self.unread_badge, self.sort_control),
                         disclosure_type=ChannelDisclosure)

    @property
    def sidebar(self) -> CommsSidebar:
        return self.query_ancestor(CommsSidebar)

    def on_mount(self) -> None:
        self.sync_members()

    def present(self, channel: ChannelRowModel) -> None:
        """Paint the channel header from its model row."""
        previous, self.channel = self.channel, channel
        row = self.row
        if previous is None or previous.label != channel.label:
            row.set_label(channel.label)
        row.tooltip = channel.tooltip
        row.set_class(channel.active, "-channel-active")
        row.set_class(bool(channel.unread), "-unread")
        if previous is None or previous.unread != channel.unread:
            label = f"({channel.unread})"
            # ASCII digits have fixed cell widths: a count change within the
            # same digit range is paint-only; visibility still owns its layout.
            width_changed = previous is None or len(label) != len(f"({previous.unread})")
            self.unread_badge.update(label, layout=width_changed)
            self.unread_badge.display = bool(channel.unread)
        self.sort_control.update_order(channel.order)

    def toggle_members(self) -> None:
        super().toggle_members()
        sidebar = self.sidebar
        sidebar.navigation.state.expanded[self.row.target_name] = self.expanded
        sidebar.navigation.apply()

    def reveal_members(self) -> None:
        if not self.expanded:
            self.toggle_members()

    def rows_changed(self) -> None:
        self.sidebar.navigation.rows_changed()

    def sync_members(self, changed: frozenset[str] | None = None) -> None:
        """Mount, remove and order member rows; repaint those in ``changed`` (all if None)."""
        channel = self.channel
        if channel is None or not self.member_container.is_attached:
            return  # A new group syncs its members once composed (on_mount).
        sidebar = self.sidebar
        threads = sidebar.model.threads.rows
        wanted = tuple(name for name in channel.members
                       if name in threads and (self.expanded or name in self.members))
        actions = cast("ToadApp", self.app).thread_actions.pending

        def create(name: str) -> ThreadRow:
            row = threads[name]
            return ThreadRow(thread_target(row.execution, name, row.active), name)

        def update(name: str, view: ThreadRow) -> None:
            if changed is not None and name not in changed and view.thread_row is not None:
                return
            row = threads[name]
            view.mode_name = sidebar.open_views.get(name)
            view.target = thread_target(row.execution, name, row.active)
            view.show(row, pinned=name in channel.pinned_members, action_status=actions.get(name))

        self.reconcile_rows(
            wanted, self.members, create, update,
            replace=lambda name, view: (view.thread_row is not None
                                        and view.thread_row.incarnation != threads[name].incarnation))


def _comms_root() -> Path:
    from agent_comms.route_selection import current_root

    return current_root()


def _display_path(path: Path) -> str:
    try:
        return f"~/{path.resolve().relative_to(Path.home())}"
    except ValueError:
        return str(path.resolve())


class CommsRow(CoreEventReceiver, ThreadStatusRow):
    """One interactive row: a channel or a thread."""

    mode_name: str | None = None

    @property
    def target_name(self) -> str:
        return self.target.name

    def show_menu(self, sidebar, offset) -> None:
        sidebar.pointer_select(self, menu=True)
        sidebar.navigation.menu_context(self).show_menu(sidebar, offset)



    DEFAULT_CSS = """
    CommsRow {
        height: auto;
        padding: 0;
    }
    CommsRow.-selected, CommsRow.-selected:hover, CommsRow.-selected:focus {
        background: $accent;
        color: $background !important;
    }
    CommsRow:ansi.-selected, CommsRow:ansi.-selected:hover, CommsRow:ansi.-selected:focus {
        background: ansi_blue;
        color: ansi_bright_white !important;
    }
    CommsRow.-unread { text-style: bold; }
    CommsRow.-current { color: $text; text-style: bold; }
    CommsRow.-current:hover, CommsRow.-current:focus { text-style: bold underline; }
    CommsRow.-channel-active { color: $warning 100%; text-style: bold; }
    """

    BINDINGS = [
        Binding("down", "cursor_down", "Next", show=False),
        Binding("up", "cursor_up", "Previous", show=False),
        Binding("enter", "open_selected", "Open", show=False),
    ]

    can_focus = True
    current = reactive(False, toggle_class="-current")

    def focus_on_click(self) -> bool:
        # Pointer activation navigates; keyboard traversal still owns row focus.
        # Avoid restyling/repainting the departing transcript before Click runs.
        return False

    def __init__(self, target: NavigationTarget, label: str) -> None:
        super().__init__(label)
        self.target = target

    def is_navigation_row(self) -> bool:
        if not self.is_attached or self._pruning or self._closing:
            return False
        group = next((node for node in self.ancestors if isinstance(node, SidebarGroup)), None)
        return group is None or group.admits_row(self)

    @property
    def selected(self) -> bool:
        sidebar = self.sidebar_owner()
        return sidebar is not None and sidebar.selection_for(self) in sidebar.selection_state.selected_targets

    def set_label(self, label: str) -> None:
        self.retire_thread_row()
        self.remove_class("-wire-thread")
        if self.content != label:
            self.update(label)

    def sidebar_owner(self):
        return next((node for node in self.walk_ancestors() if isinstance(node, TargetTree)), None)

    # Row-level actions delegate to the sidebar so keys work even when
    # scrollable ancestors would otherwise consume them.
    def action_cursor_down(self) -> None:
        sidebar = self.sidebar_owner()
        if sidebar is not None:
            sidebar.action_cursor_down()

    def action_cursor_up(self) -> None:
        sidebar = self.sidebar_owner()
        if sidebar is not None:
            sidebar.action_cursor_up()

    def action_open_selected(self) -> None:
        if sidebar := self.sidebar_owner():
            sidebar.remember_row(self)
        screen = self.app.selected_session
        if isinstance(screen, NavigationOwner):
            # The route outlives this row (inactive rosters are retired after
            # presentation). Dispatch through its declared view owner without
            # another message bubbling through each sidebar container.
            self.app.run_worker(
                partial(screen.open_sidebar_target, self.target),
                group="sidebar-open",
            )
        else:
            self.publish_core(SelectTarget(self.target))

    def on_focus(self) -> None:
        """Keep the sidebar cursor in sync with keyboard focus."""
        sidebar = self.sidebar_owner()
        if sidebar is not None:
            rows = sidebar._ordered_rows()
            if self in rows:
                sidebar.focus_row(self)

    def on_click(self, event) -> None:
        if event.button == 3:
            return  # right click handled by context menu in CommsSidebar
        if sidebar := self.sidebar_owner():
            if event.ctrl or event.shift:
                event.stop()
                sidebar.pointer_select(self, control=event.ctrl, shift=event.shift)
                return
        self.action_open_selected()


class ThreadRow(CommsRow):
    """A retained wire thread row, with an optional currently open native view."""

    def action_open_selected(self) -> None:
        if self.mode_name is None or cast("ToadApp", self.app).session_tracker.get_session(self.mode_name) is None:
            super().action_open_selected()
        else:
            if sidebar := self.sidebar_owner():
                sidebar.remember_row(self)
            self.app.select_session(self.mode_name)


class NewSessionButton(Static):
    """Create another agent session for the current project."""

    DEFAULT_CSS = """
    NewSessionButton {
        width: 1fr;
        height: 1;
        padding: 0;
        color: $text-muted;
        pointer: pointer;
    }
    NewSessionButton:hover,
    NewSessionButton:focus {
        background: $surface-lighten-2;
        color: $text;
    }
    NewSessionButton:ansi:hover,
    NewSessionButton:ansi:focus {
        background: ansi_bright_white;
        color: ansi_black;
        text-style: bold;
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

    def action_create(self) -> None:
        source_mode = cast("ToadApp", self.app).selected_mode
        self.app.session_navigation.events.publish(session_requests.SessionCreate(source_mode))

    def on_mouse_up(self, event) -> None:
        if event.button == 1:
            self.action_create()

    def _sidebar(self):
        return next((node for node in self.walk_ancestors() if isinstance(node, CommsSidebar)), None)

    def on_focus(self) -> None:
        if (sidebar := self._sidebar()) is not None:
            sidebar._cursor = -1

    def action_cursor_down(self) -> None:
        if (sidebar := self._sidebar()) is not None:
            sidebar.action_cursor_down()

    def action_cursor_up(self) -> None:
        if (sidebar := self._sidebar()) is not None:
            rows = sidebar._ordered_rows()
            if rows:
                sidebar._cursor = len(rows)
                sidebar.action_cursor_up()


class CoordinationStatus(Static):
    """Compact diagnostics for the persistent coordination wire."""

    DEFAULT_CSS = """
    CoordinationStatus {
        height: auto;
        padding: 0;
        color: $text-muted;
    }
    """

    def __init__(self, thread: str = "") -> None:
        super().__init__()
        self.thread = thread
        self.refresh_status()

    def set_thread(self, thread: str) -> None:
        self.thread = thread
        self.refresh_status()

    def refresh_status(self) -> None:
        try:
            root = _comms_root()
        except (OSError, ValueError, RuntimeError) as error:
            self.update(f"Wire unavailable: {error}")
            self.tooltip = "Invalid Comms route"
            return
        backend = os.environ.get("AGENT_COMMS_AGENT_BIN", "pi")
        thread = self.thread or "connecting..."
        self.update(
            Content.assemble(
                "Wire: ",
                (_display_path(root), "$text"),
                (" · persistent", "$success"),
                f"\nThread: {thread}",
                f"\nACP/session · {Path(backend).name}",
            )
        )
        args = os.environ.get(
            "AGENT_COMMS_AGENT_ARGS",
            "--print --no-session --provider openrouter --model z-ai/glm-5.3-flash",
        )
        self.tooltip = (
            "Coordination state persists in the shared wire; the stdio ACP transport "
            "is scoped to this Toad session.\n\n"
            f"AGENT_COMMS_ROOT={root.resolve()}\n"
            f"AGENT_COMMS_AGENT_BIN={backend}\n"
            f"AGENT_COMMS_AGENT_ARGS={args}\n"
            f"AGENT_COMMS_REPLY_WINDOW={os.environ.get('AGENT_COMMS_REPLY_WINDOW', '8.0')}\n"
            f"AGENT_COMMS_NO_REPLY_WINDOW={os.environ.get('AGENT_COMMS_NO_REPLY_WINDOW', '2.5')}\n"
            f"AGENT_COMMS_REPLY_QUIET={os.environ.get('AGENT_COMMS_REPLY_QUIET', '1.5')}"
        )


class CommsSidebar(CoreEventReceiver, SidebarVisibilityObserver, TargetTree):
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
    selected: reactive[str] = reactive("", init=False)
    session_thread: reactive[str] = reactive("", init=False)

    def __init__(self, session_thread: str = "", *,
                 observe: bool = True, **kwargs):
        super().__init__(**kwargs)
        from toad.sidebar_navigation import SidebarNavigation
        self.session_thread = session_thread
        self.can_focus = True
        self._cursor = 0
        self.navigation = SidebarNavigation(self)
        self.enabled = observe
        self.service: Comms | None = None
        self.model: SidebarModel | None = None
        self.groups: dict[str, ChannelGroup] = {}
        self.new_session: NewSessionButton | None = None
        # Thread name -> the mode of the tab that has it open.
        self.open_views: dict[str, str] = {}
        # Model changes arrived while this view was hidden or disabled.
        self.stale = False

    def accepts_publication(self) -> bool:
        """The mounted widget owns the legality of writing its presentation."""
        return (self.is_attached and not self._closing and not self._pruning
                and self.app.is_running and self.screen.is_current)

    def accepts_observation(self) -> bool:
        from toad.widgets.side_bar import SideBar

        return (self.enabled and self.accepts_publication()
                and not self.query_ancestor(SideBar).collapsed)

    @property
    def shows_model(self) -> bool:
        return self.model is not None and self.model.snapshot is not None and not self.stale

    async def on_mount(self) -> None:
        from toad.screens.comms import CommsScreen
        from toad.screens.workspace import WorkspaceScreen

        app = self.app
        try:
            service = await app.preparation.run_thread(lambda: app.coordination_access.service)
        except (OSError, ValueError, RuntimeError):
            self.display = False
            return
        screen = self.screen
        if isinstance(screen, CommsScreen) and not screen.belongs_to_wire(service.root):
            self.display = False
            return
        self.subscribe_core(app.session_tracker.events)
        self.observe_core(app.events)
        self.observe_core(app.coordination_access.events)
        await self.navigation.prepare()
        if isinstance(screen, WorkspaceScreen):
            screen.frame_presentation.defer(self, self.navigation.start)
        self.attach(service)

    def on_unmount(self) -> None:
        self.app.coordination_access.show_sidebar(self, False)
        self.unsubscribe()

    def unsubscribe(self) -> None:
        if self.model is not None:
            self.model.channels.unsubscribe(self.channels_changed)
            self.model.threads.unsubscribe(self.threads_changed)

    def attach(self, service: Comms) -> None:
        """Render ``service``'s shared model; another service's rows are retired first."""
        observed = self.app.coordination_access.observation
        if observed is None or observed.service is not service or observed.sidebar is self.model:
            return  # A newer observed service attaches on its CoordinationObserved.
        self.unsubscribe()
        self.service, self.model = service, observed.sidebar
        self.model.channels.subscribe(self.channels_changed)
        self.model.threads.subscribe(self.threads_changed)
        self.display = False
        self.navigation.reset()
        if self.groups:
            self.remove_children(list(self.groups.values()))
            self.groups.clear()
            self.navigation.rows_changed()
        self.stale = True
        self.present()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.present()

    def channels_changed(self, changes: Changes[str]) -> None:
        if self.accepts_observation() and not self.stale:
            self.sync(channels=frozenset((*changes.added, *changes.changed)), threads=frozenset(),
                      reorder=bool(changes.added or changes.removed or changes.order is not None))
        else:
            self.stale = True
            self.present()

    def threads_changed(self, changes: Changes[str]) -> None:
        if self.accepts_observation() and not self.stale:
            self.sync(channels=frozenset(),
                      threads=frozenset((*changes.added, *changes.removed, *changes.changed)))
        else:
            self.stale = True
            self.present()

    def present(self) -> None:
        """Reconcile everything with the model once this view shows it again."""
        shown = self.model is not None and self.accepts_observation()
        self.app.coordination_access.show_sidebar(self, shown)
        if shown and self.stale and self.model.snapshot is not None:
            self.stale = False
            self.sync(channels=None, threads=None, reorder=True)

    def sync(self, *, channels: frozenset[str] | None, threads: frozenset[str] | None,
             reorder: bool = False) -> None:
        """Apply model changes; ``None`` means every channel or thread changed."""
        from toad.widgets.session_sort import ChannelListSort
        from toad.widgets.side_bar import SideBarCollapsible

        model = self.model
        assert model is not None
        rows = model.channels.rows
        if threads is None or threads:
            self.open_views = self.find_open_views()
        if self.new_session is None:
            self.new_session = NewSessionButton()
            self.mount(self.new_session)
        removed = [key for key in self.groups if key not in rows]
        if removed:
            self.remove_children([self.groups.pop(key) for key in removed])
        added = []
        for key, channel in rows.items():
            group = self.groups.get(key)
            if group is None:
                row = CommsRow(channel_target(key), key)
                group = self.groups[key] = ChannelGroup(row, expanded=self.navigation.state.expanded.get(
                    key, row.target.expanded_by_default))
                group.present(channel)  # Its members sync once it is mounted.
                added.append(group)
            elif channels is None or key in channels:
                # Membership, pins or order changed: every member row is current.
                group.present(channel)
                group.sync_members()
            elif threads is None or not threads.isdisjoint(channel.members):
                group.sync_members(threads)
        if added:
            self.mount(*added)
        if removed or added or reorder:
            ordered = [self.new_session, *(self.groups[key] for key in rows)]
            if [child for child in self.children if not child._pruning] != ordered:
                positions = {widget: index for index, widget in enumerate(ordered)}
                self.sort_children(key=lambda child: positions.get(child, len(positions)))
            self.navigation.rows_changed()
        panel = self.query_ancestor(SideBarCollapsible)
        control = panel.header_control
        assert isinstance(control, ChannelListSort)
        control.update_order(model.channel_order)
        self.navigation.apply()
        self.sync_current()
        # Full row text is retained; the panel grows to the widest content.
        panel.styles.min_width = self.content_width()
        self.display = True
        if not self.navigation.ready.is_set() and self.screen.is_current:
            self.call_after_refresh(self.navigation.finish, self.navigation.revision)

    def content_width(self) -> int:
        model = self.model
        assert model is not None
        widest = max((cell_len(name) + 12 for name in model.channels.rows), default=0)
        widest = max(widest, max((cell_len(text) + 8 for row in model.threads.rows.values()
                                  for text in (row.label, row.summary)), default=0))
        return min(widest, 512)

    def find_open_views(self) -> dict[str, str]:
        """Which open tab shows each thread of this service; the first tab claims it."""
        app = self.app
        threads = self.model.threads.rows
        views: dict[str, str] = {}
        for details in app.session_tracker.ordered_sessions:
            screen = app.session_navigation.source(details.mode_name)
            if screen is None or not screen.belongs_to_wire(self.service.root):
                continue  # A same-named thread on another wire is not this open view.
            name = screen._comms_thread
            if name not in threads and screen._agent_session_id in threads:
                name = screen._agent_session_id
            if name in threads and name not in views:
                views[name] = details.mode_name
        return views

    @handles(SessionChangedEvent)
    async def session_changed(self, event: CoreEventMessage) -> None:
        if not self.shows_model:
            return
        self.open_views = self.find_open_views()
        for group in self.groups.values():
            for name, row in group.members.items():
                row.mode_name = self.open_views.get(name)
        self.sync_current()

    @handles(SessionSelected)
    async def session_selected(self, event: CoreEventMessage) -> None:
        self.sync_current()

    @handles(ThreadActionsChanged)
    async def thread_actions_changed(self, event: CoreEventMessage) -> None:
        if self.shows_model and self.accepts_observation():
            for group in self.groups.values():
                group.sync_members()

    @handles(CoordinationObserved)
    async def coordination_observed(self, event: CoreEventMessage) -> None:
        service = self.app.coordination_access.observed_service
        if service is not None and service is not self.service:
            self.attach(service)

    def sidebar_visibility_changed(self) -> None:
        self.present()

    def _ordered_rows(self):
        return self.rows

    @property
    def rows(self) -> list[CommsRow]:
        return [row for group in self.children if isinstance(group, ChannelGroup)
                for row in (group.row, *group.visible_members)
                if row.is_navigation_row()]

    @property
    def selection_state(self):
        return self.navigation.state

    def selection_for(self, row):
        from toad.session_tracker import SidebarSelection
        return SidebarSelection(row.query_ancestor(ChannelGroup).row.target_name, row.target_name)

    def accepts_selection(self) -> bool:
        return not self.navigation.restoring

    def apply_selection(self) -> None:
        self.navigation.selection_applied = False
        self.navigation.apply()

    @property
    def navigation_root(self):
        return self.service.root if self.service is not None else None

    def action_open_selected(self) -> None:
        rows = self.rows
        focused = self.app.focused if self.app else None
        if isinstance(focused, CommsRow) and focused in rows:
            target = focused
            self._cursor = rows.index(target)
        elif 0 <= self._cursor < len(rows):
            target = rows[self._cursor]
        else:
            return
        self._apply_cursor(rows)
        self.remember_row(target)
        target.action_open_selected()

    def on_click(self, event) -> None:
        """Right click anywhere -> menu on the row under the mouse."""
        if event.button != 3:
            return
        event.stop()
        widget, _ = self.screen.get_widget_at(event.screen_x, event.screen_y)
        row = None
        node: DOMNode | None = widget
        while node is not None:
            if isinstance(node, CommsRow):
                row = node
                break
            node = node.parent
        if row is None:
            return
        row.show_menu(self, event.screen_offset)
