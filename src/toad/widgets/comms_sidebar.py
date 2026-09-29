"""Agent-comms channels and remote sessions for Toad's session panel.

IRC semantics for fully-detailed agent threads:

- **Click** a thread row -> opens its DM as a native Toad session.
- **Click** a channel row -> opens that channel as a native Toad session.
- **Right-click** -> context menu: fork, stop, acknowledge, copy name.
- Compact live rows: name, unread badge, and authoritative thread activity.

View, not authority: reads the wire (``AGENT_COMMS_ROOT``) directly and
acts through ``agent_comms`` operations.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, cast

from agent_comms.comms import Comms, wire
from agent_comms.presentation import ChannelView, CoordinationSnapshot, ThreadView, WireRevision
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.content import Content
from textual.dom import DOMNode
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from toad.constants import COMMS_REFRESH_INTERVAL

from toad.session_tracker import UnreadPresentation, ExactUnread
from toad import messages
from toad.constants import ALL_COMMS_TARGET
from toad.navigation_target import NavigationOwner
from toad.preferences import SidebarSettings
from toad.session_tracker import (
    SessionDetails,
    SidebarSelection,
    SidebarState,
)
from toad.settings import PreferenceChange
from toad.sidebar_preparation import ThreadRowInput, ThreadRowsWork
from toad.widgets.activity_spinner import FRAMES
from toad.widgets.session_sidebar import ThreadStatusRow
from toad.widgets.session_sort import ChannelListSort, SessionSort
from toad.widgets.sidebar_tree import SidebarDisclosure, SidebarGroup, TargetTree
from toad.widgets.side_bar import SidebarVisibilityObserver
from toad.navigation_target import NavigationTarget, channel_target, person_target
from toad.sidebar_snapshot import SidebarSnapshot

if TYPE_CHECKING:
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
    """A lazy rendering of model-provided membership, never a second thread owner."""
    DEFAULT_CSS = """
    ChannelGroup { height: auto; }
    ChannelGroup > HorizontalGroup { height: 1; }
    ChannelGroup .channel-header { height: 1; width: 1fr; text-wrap: nowrap; text-overflow: ellipsis; }
    ChannelGroup .channel-members { height: auto; margin-left: 2; }
    """

    def __init__(self, row: CommsRow, *, expanded: bool):
        row.add_class("channel-header")
        self._view: ChannelView | None = None
        self._snapshot: SidebarSnapshot | None = None
        self._members: dict[str, ThreadRow] = {}
        self.member_rows: tuple[ThreadRow, ...] = ()
        self._lock = asyncio.Lock()
        self.sort_control = SessionSort(channel=row.target_name)
        self.unread_badge = ChannelUnread(markup=False)
        self.unread_badge.display = False
        self._unread = 0
        self._channel_active = False
        super().__init__(row, expanded=expanded,
                         controls=(self.unread_badge, self.sort_control),
                         disclosure_type=ChannelDisclosure)

    async def update_members(self, view: ChannelView, snapshot: SidebarSnapshot) -> None:
        self._view, self._snapshot = view, snapshot
        self.sort_control.update_order(view.channel.order)
        await self._sync_members()

    def update_unread(self, unread: int) -> None:
        if unread != self._unread:
            label = f"({unread})"
            width_changed = len(label) != len(f"({self._unread})")
            self._unread = unread
            self.row.unread = unread
            # ASCII digits have fixed cell widths. A count change within the
            # same digit range is paint-only; visibility still owns its layout.
            self.unread_badge.update(label, layout=width_changed)
            self.unread_badge.display = bool(unread)

    def update_activity(self, channel_view: ChannelView, all_people: Mapping[str, ThreadView]) -> None:
        """Mark the channel live when any member is working or mid-turn."""
        active = any(
            (person.thread.executing or person.presentation.busy)
            for name in channel_view.members
            if (person := all_people.get(name)) is not None
        )
        if active != self._channel_active:
            self._channel_active = active
            self.row.set_class(active, "-channel-active")

    def toggle_members(self) -> None:
        super().toggle_members()
        self.query_ancestor(CommsSidebar).navigation.state.expanded[self.row.target_name] = self.expanded

    async def _sync_and_select(self) -> None:
        await self._sync_members()
        if self.is_attached and not self._pruning and not self._closing:
            self.query_ancestor(CommsSidebar).navigation.apply(force=True)

    async def _sync_members(self) -> None:
        async with self._lock:
            if not self.is_mounted or self._view is None or self._snapshot is None:
                return
            wanted = tuple(name for name in self._view.members
                           if name in self._snapshot.all_people) if self.expanded else ()
            app = cast("ToadApp", self.app)
            view, snapshot = self._view, self._snapshot
            inputs = tuple(ThreadRowInput(
                snapshot.all_people[name],
                unread=person_target(snapshot.all_people[name]).unread(snapshot.wire),
                pinned=name in view.pinned_members,
                action_status=app.thread_actions.pending.get(name),
            ) for name in wanted)
            results = await app.preparation.submit(ThreadRowsWork(inputs)) if inputs else ()
            if (not self.is_attached or self._pruning or self._closing
                    or self._view is not view or self._snapshot is not snapshot):
                return
            prepared_rows = dict(zip(wanted, results))
            # A tab may close while immutable row text is being prepared. The
            # shared roster survives that close; project live view routes only
            # after the await, rather than restoring a retired mode from a DTO.
            current = self.query_ancestor(CommsSidebar).observation.project(snapshot.wire)
            modes = {name: mode for mode, name in current.session_threads.items()}

            def create(name):
                person = self._snapshot.all_people[name]
                return ThreadRow(person_target(person), name)

            def update(name, row):
                # The thread is the row identity. Opening/closing one of its
                # views changes navigation, not its content widget or geometry.
                row.mode_name = modes.get(name)
                row.target = person_target(self._snapshot.all_people[name])
                row.apply_thread_preparation(prepared_rows[name])
                row.current = row.mode_name == app.selected_mode

            self.member_rows = await self.reconcile_rows(
                wanted, self._members, create, update)


    async def present(self, view: ChannelView,
                               snapshot: SidebarSnapshot) -> None:
        row = self.row
        sidebar = self.query_ancestor(CommsSidebar)
        if row.is_attached:
            row.tooltip = f"{len(view.members)} threads · tags: {', '.join(sorted(view.channel.tags)) or 'all'}"
            group = self
            expanded = sidebar.navigation.state.expanded.get(row.target_name, row.target.expanded_by_default)
            if group.expanded != expanded:
                group.expanded = expanded
                # The glyph has fixed dimensions. Mounting/removing members
                # owns the layout change, not repainting an unchanged arrow
                # on every wire snapshot (which reflows the transcript too).
                group.disclosure.update("▾" if expanded else "▸", layout=False)
            await group.update_members(view, snapshot)


def _comms_root() -> Path:
    from toad.comms_root import current_root

    return current_root()


def _display_path(path: Path) -> str:
    try:
        return f"~/{path.resolve().relative_to(Path.home())}"
    except ValueError:
        return str(path.resolve())


class SelectTarget(Message):
    """User picked a view target: a channel, a DM peer, or the session."""

    def __init__(self, target: NavigationTarget) -> None:
        self.target = target
        super().__init__()


class CommsRow(ThreadStatusRow):
    """One interactive row: a channel or a thread."""

    mode_name: str | None = None

    @property
    def target_name(self) -> str:
        return self.target.name

    def show_menu(self, sidebar, offset) -> None:
        if self.mode_name is None:
            sidebar._select(self)
        self.target.show_menu(sidebar, offset, mode_name=self.mode_name, channel=self.query_ancestor(ChannelGroup).row.target_name)



    DEFAULT_CSS = """
    CommsRow {
        height: auto;
        padding: 0;
    }
    CommsRow.-unread { text-style: bold; }
    CommsRow.-current { color: $text; text-style: bold; }
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

    def __init__(self, target: NavigationTarget, label: str, unread: int = 0) -> None:
        super().__init__(label)
        self.target = target
        self._label = label
        self.unread = unread

    @property
    def selected(self) -> bool:
        sidebar = self._sidebar()
        return sidebar is not None and sidebar.selected == self.target_name

    def set_label(self, label: str) -> None:
        if label != self._label:
            self._label = label
            self.update(label)

    def _sidebar(self):
        parent = self.parent
        while parent is not None and not isinstance(parent, TargetTree):
            parent = parent.parent
        return parent

    # Row-level actions delegate to the sidebar so keys work even when
    # scrollable ancestors would otherwise consume them.
    def action_cursor_down(self) -> None:
        sidebar = self._sidebar()
        if sidebar is not None:
            sidebar.action_cursor_down()

    def action_cursor_up(self) -> None:
        sidebar = self._sidebar()
        if sidebar is not None:
            sidebar.action_cursor_up()

    def action_open_selected(self) -> None:
        if sidebar := self._sidebar():
            sidebar.navigation.remember(self)
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
            self.post_message(SelectTarget(self.target))

    def on_focus(self) -> None:
        """Keep the sidebar cursor in sync with keyboard focus."""
        sidebar = self._sidebar()
        if sidebar is not None:
            rows = sidebar._ordered_rows()
            if self in rows:
                sidebar.focus_row(self)

    def on_click(self, event) -> None:
        if event.button == 3:
            return  # right click handled by context menu in CommsSidebar
        self.action_open_selected()


class ThreadRow(CommsRow):
    """A retained wire thread row, with an optional currently open native view."""

    def action_open_selected(self) -> None:
        if self.mode_name is None or cast("ToadApp", self.app).session_tracker.get_session(self.mode_name) is None:
            super().action_open_selected()
        else:
            if sidebar := self._sidebar():
                sidebar.navigation.remember(self)
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
        self.app.post_message(messages.SessionCreate(source_mode))

    def on_mouse_up(self, event) -> None:
        if event.button == 1:
            self.action_create()

    def _sidebar(self):
        parent = self.parent
        while parent is not None and not isinstance(parent, CommsSidebar):
            parent = parent.parent
        return parent

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


class CommsSidebar(SidebarVisibilityObserver, TargetTree):
    """One shared channel hierarchy; source, paint and reader intent have owners."""
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

    def __init__(self, session_thread: str = "", selected_target: str = "", *,
                 observe: bool = True, **kwargs):
        super().__init__(**kwargs)
        from toad.sidebar_navigation import SidebarNavigation
        from toad.sidebar_observation import SidebarObservation
        from toad.sidebar_projection import SidebarProjection
        self.session_thread = session_thread
        self.selected = selected_target
        self.can_focus = True
        self._cursor = 0
        self.navigation = SidebarNavigation(self)
        self.observation = SidebarObservation(self, enabled=observe)
        self.projection = SidebarProjection(self)

    def on_mount(self) -> None:
        self.projection.mount()
        self.observation.mount()

    def sidebar_visibility_changed(self) -> None:
        self.projection.sync_spinner()

    def _ordered_rows(self):
        return self.projection.rows

    def action_open_selected(self) -> None:
        rows = self.projection.rows
        focused = self.app.focused if self.app else None
        if isinstance(focused, CommsRow) and focused in rows:
            target = focused
            self._cursor = rows.index(target)
        elif 0 <= self._cursor < len(rows):
            target = rows[self._cursor]
        else:
            return
        self._apply_cursor(rows)
        self.navigation.remember(target)
        self.selected = target.target_name
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

    def _select(self, row: CommsRow) -> None:
        row.focus()
