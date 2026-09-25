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

import os
import asyncio
from dataclasses import dataclass
from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, cast

from textual import on
from textual.binding import Binding
from textual.app import ComposeResult
from textual.dom import DOMNode
from textual.message import Message
from textual.reactive import reactive
from textual.content import Content
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option
from textual.widget import Widget

from agent_comms import (
    context_tool_catalog,
    ChannelView, CoordinationSnapshot, ThreadStatus, ThreadView,
    OBSERVATION_INTERVAL, WireRevision,
)
from agent_comms.operations import wire

from toad import messages
from toad.constants import ALL_COMMS_TARGET
from toad.session_tracker import SessionDetails, SidebarSelection, SidebarState
from toad.widgets.session_sidebar import ThreadStatusRow
from toad.widgets.session_sort import ChannelListSort, SessionSort
from toad.widgets.virtual_channel_list import VirtualChannelList, VirtualChoice, styled_row
from toad.widgets.activity_spinner import FRAMES
from toad.widgets.sidebar_tree import SidebarDisclosure, SidebarGroup, TargetTree

if TYPE_CHECKING:
    from toad.app import ToadApp


@dataclass(frozen=True)
class SidebarSnapshot:
    wire: CoordinationSnapshot
    session_threads: Mapping[str, str]
    all_people: Mapping[str, ThreadView]

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
        self.query_ancestor(CommsSidebar).navigation.expanded[self.row.target_name] = self.expanded

    async def _sync_and_select(self) -> None:
        await self._sync_members()
        self.query_ancestor(CommsSidebar).apply_selection(force=True)

    async def _sync_members(self) -> None:
        async with self._lock:
            if not self.is_mounted or self._view is None or self._snapshot is None:
                return
            wanted = tuple(name for name in self._view.members
                           if name in self._snapshot.all_people) if self.expanded else ()
            app = cast("ToadApp", self.app)
            modes = {name: mode for mode, name in self._snapshot.session_threads.items()}

            def create(name):
                person = self._snapshot.all_people[name]
                return ThreadRow(CommsSidebar._person_kind(person), name, name)

            def update(name, row):
                # The thread is the row identity. Opening/closing one of its
                # views changes navigation, not its content widget or geometry.
                row.mode_name = modes.get(name)
                row.kind = CommsSidebar._person_kind(self._snapshot.all_people[name])
                row.update_thread(
                    self._snapshot.all_people[name],
                    unread=(self._snapshot.wire.thread_unread.get(name, 0)
                            if CommsSidebar._person_kind(self._snapshot.all_people[name]) == "thread"
                            else self._snapshot.wire.unread.get(name, 0)),
                    pinned=name in self._view.pinned_members,
                    action_status=app.pending_thread_actions.get(name),
                )
                row.current = row.mode_name == app.current_mode

            self.member_rows = await self.reconcile_rows(
                wanted, self._members, create, update)


def _comms_root() -> Path:
    return Path(os.environ.get("AGENT_COMMS_ROOT", "~/.agent-comms")).expanduser()


def _display_path(path: Path) -> str:
    try:
        return f"~/{path.resolve().relative_to(Path.home())}"
    except ValueError:
        return str(path.resolve())


class SelectTarget(Message):
    """User picked a view target: a channel, a DM peer, or the session."""

    def __init__(self, target: str, kind: str) -> None:
        self.target = target
        self.kind = kind  # "channel" | "dm" | "session"
        super().__init__()


class CommsRow(ThreadStatusRow):
    """One interactive row: a channel or a thread."""

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

    def __init__(self, kind: str, name: str, label: str, unread: int = 0) -> None:
        super().__init__(label)
        self.kind = kind  # "channel" | "dm" | "session"
        self.target_name = name
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
            sidebar.remember_row(self)
        self.post_message(SelectTarget(self.target_name, self.kind))

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

    mode_name: str | None = None

    def action_open_selected(self) -> None:
        if self.mode_name is None:
            super().action_open_selected()
        else:
            if sidebar := self._sidebar():
                sidebar.remember_row(self)
            self.app.switch_mode(self.mode_name)


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
        source_mode = self.screen.id or cast("ToadApp", self.app).current_mode
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
        root = _comms_root()
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


class CommsSidebar(TargetTree):
    """Local and remote sessions with wire channels and live activity.

    Keyboard: up/down move the selection, enter opens the selected
    target in the main pane. Mouse: click selects+opens, right-click
    opens the context menu.
    """

    DEFAULT_CSS = """
    CommsSidebar {
        height: auto;
        padding: 0 0 1 0;
    }
    CommsSidebar .section { color: $text-muted; padding: 1 0 0 0; }
    CommsSidebar .row-name { color: $text; }
    CommsSidebar .row-detail { color: $text-muted; }
    """

    BINDINGS = [
        ("up", "cursor_up", "Previous"),
        ("down", "cursor_down", "Next"),
        ("enter", "open_selected", "Open"),
    ]

    selected: reactive[str] = reactive("", init=False)
    session_thread: reactive[str] = reactive("", init=False)

    class ThreadAction(Message):
        """Context-menu action on a thread."""

        def __init__(self, name: str, action: str) -> None:
            self.name = name
            self.action = action
            super().__init__()

    def __init__(
        self, session_thread: str = "", selected_target: str = "", **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.session_thread = session_thread
        self.selected = selected_target
        self._row_map: dict[tuple[str, str], CommsRow] = {}
        self._virtual = os.environ.get("TOAD_BENCH_VIRTUAL_CHANNELS") == "1"
        self._virtual_targets: dict[str, VirtualChoice] = {}
        self._busy_virtual_rows: dict[int, tuple[str, bool, bool, bool]] = {}
        self._spinner_phase = 0
        self._spinner_timer = None
        self._horizontal_width = 0
        self.can_focus = True
        self._cursor = 0
        # A screen constructs its sidebar before attachment to an App. Resolve
        # the already-retained reader on mount rather than building a second
        # registry/catalog and immediately throwing it away.
        self._wire = None
        self._last_snapshot: SidebarSnapshot | None = None
        self._snapshot_pending = False
        self._snapshot_lock = asyncio.Lock()
        self._presentation_lock = asyncio.Lock()
        self._last_revision: WireRevision | None = None
        self._last_actor = ""
        self._last_filters: tuple[bool, bool] | None = None
        self._last_read_marker_notice: str | None = None
        self._rendered_selection: SidebarSelection | None = None
        self._selected_row: CommsRow | None = None
        self._selection_applied = False
        self._rendered_mode: tuple[str, str | None] | None = None
        self._rendered_expansion: dict[str, bool] = {}
        self._rendered_actions: dict[str, str] = {}
        self.navigation_ready = asyncio.Event()

    def compose(self) -> ComposeResult:
        if self._virtual:
            yield VirtualChannelList()

    @property
    def _restore_navigation(self) -> bool:
        return not self.navigation_ready.is_set()

    @property
    def navigation(self) -> SidebarState:
        return cast("ToadApp", self.app).sidebar_state

    def capture_navigation(self) -> None:
        if not self._restore_navigation:
            channel, panels = self.scroll_containers
            self.navigation.channel_scroll_y = channel.scroll_y
            self.navigation.panel_scroll_y = panels.scroll_y

    @property
    def scroll_containers(self) -> tuple[Widget, Widget]:
        from toad.widgets.side_bar import SideBar, SideBarCollapsible

        panel = self.query_ancestor(SideBarCollapsible)
        panels = panel.query_ancestor(SideBar).query_one("#sidebar-panels")
        return panels, panels

    def prepare_navigation(self) -> None:
        self.navigation_ready.clear()

    def _selection_for(self, row: CommsRow) -> SidebarSelection:
        channel = row.query_ancestor(ChannelGroup).row.target_name
        return SidebarSelection(channel, row.target_name)

    def remember_row(self, row: CommsRow) -> None:
        if self._restore_navigation:
            return
        rows = self._ordered_rows()
        if row in rows:
            self._cursor = rows.index(row)
            self.navigation.selected = self._selection_for(row)
            self.apply_selection()

    def focus_row(self, row: CommsRow) -> None:
        rows = self._ordered_rows()
        if row in rows:
            self._cursor = rows.index(row)

    def apply_selection(self, *, force: bool = False) -> None:
        if self._virtual:
            if self._last_snapshot is not None and (
                force or self._rendered_selection != self.navigation.selected
            ):
                self._rebuild_virtual(self._last_snapshot)
            return
        if (not force and self._selection_applied
                and self._rendered_selection == self.navigation.selected
                and (self._selected_row is None or self._selected_row.is_attached)):
            return
        self._selected_row = None
        for index, row in enumerate(self._ordered_rows()):
            selected = self._selection_for(row) == self.navigation.selected
            row.set_class(selected, "-selected")
            if selected:
                self._selected_row = row
                self._cursor = index
        self._rendered_selection = self.navigation.selected
        self._selection_applied = True

    def restore_scroll(self) -> bool:
        if self._restore_navigation and self.is_attached and self.screen is self.app.screen:
            channel, panels = self.scroll_containers
            before = channel.scroll_y, panels.scroll_y
            channel.scroll_to(y=self.navigation.channel_scroll_y, animate=False, immediate=True)
            panels.scroll_to(y=self.navigation.panel_scroll_y, animate=False, immediate=True)
            return before != (channel.scroll_y, panels.scroll_y)
        return False

    def on_mount(self) -> None:
        self._spinner_timer = self.set_interval(.18, self._animate_busy, pause=True)
        app = cast("ToadApp", self.app)
        # Every mounted tab observes the same wire revision. Retain the app's
        # core reader rather than rebuilding its registry, bus and catalog
        # caches for each independently mounted sidebar.
        root = _comms_root().resolve()
        self._wire = (app.coordination_wire if root == app.coordination_wire.root
                      else wire(root))
        app.session_update_signal.subscribe(self, self._session_updated)
        app.mode_change_signal.subscribe(self, self._mode_changed)
        app.thread_actions_changed.subscribe(self, self._thread_actions_changed)
        app.settings_changed_signal.subscribe(self, self._settings_changed)
        self.set_interval(OBSERVATION_INTERVAL, self._refresh)
        from toad.screens.comms import CommsScreen

        if isinstance(self.screen, CommsScreen) and not self.screen._navigation_applied:
            self.call_after_refresh(self._refresh)
        else:
            self._refresh()
        self._run_test_hook()

    def _sync_spinner(self, snapshot: SidebarSnapshot | None = None) -> None:
        from toad.widgets.side_bar import SideBar

        timer = self._spinner_timer
        if timer is None:
            return
        current = snapshot or self._last_snapshot
        bar = next((node for node in self.ancestors if isinstance(node, SideBar)), None)
        has_busy_rows = (bool(self._busy_virtual_rows) if self._virtual
                         else any(row.has_class("-busy") for row in self.query(ThreadStatusRow)))
        if (self.screen.is_active and bar is not None and not bar.collapsed
                and current is not None and has_busy_rows):
            timer.resume()
        else:
            timer.pause()

    def _animate_busy(self) -> None:
        if not self.screen.is_active or self._last_snapshot is None:
            self._sync_spinner()
            return
        self._spinner_phase = (self._spinner_phase + 1) % len(FRAMES)
        if self._virtual:
            listing = self.query_one_optional(VirtualChannelList)
            if listing is None:
                return
            for index, (source, selected, unread, ansi) in self._busy_virtual_rows.items():
                text = source.replace("⌛ ", f"{FRAMES[self._spinner_phase]} ", 1)
                listing.replace_option_prompt_at_index(index, styled_row(
                    text, selected=selected, ansi=ansi, busy=True, muted=True, unread=unread,
                ))
        else:
            for row in self.query(ThreadStatusRow):
                if row.has_class("-busy"):
                    row.advance_spinner(self._spinner_phase)

    async def _session_updated(self, update: tuple[str, SessionDetails | None]) -> None:
        if not self.is_attached or self.screen is not self.app.screen:
            # One update is published to every mounted sidebar. Inactive rows
            # reconcile from the app's cached projection on activation instead
            # of walking every hidden widget tree for each new/closed tab.
            self._last_revision = None
            return
        mode_name, details = update
        if details is None or self._last_snapshot is None or mode_name not in self._last_snapshot.session_threads:
            self._last_revision = None
            self._refresh()
        self._mode_changed(cast("ToadApp", self.app).current_mode)

    async def sync_sessions(self) -> None:
        """Reconcile tracked rows before a resumed screen can accept input."""
        self._snapshot_pending = True
        async with self._snapshot_lock:
            try:
                revision = self._wire.revision()
                if (self._last_snapshot is not None and revision == self._last_revision
                        and self.visible_filters == self._last_filters):
                    await self._present_snapshot(self._snapshot(self._last_snapshot.wire))
                else:
                    await self._read_snapshot(revision)
            finally:
                self._snapshot_pending = False

    async def _thread_actions_changed(self, _update: None) -> None:
        if not self.is_attached or self.screen is not self.app.screen:
            self._last_revision = None
            return
        if self._last_snapshot is not None and self.is_attached:
            await self._present_snapshot(self._last_snapshot)
        self._last_revision = None
        self._refresh()

    async def present_cached_sessions(self) -> None:
        """Paint the last observed projection; refresh disk state after activation."""
        state = cast("ToadApp", self.app)._sidebar_snapshot
        if state is not None and (
            state.show_stopped, state.show_archived
        ) == self.visible_filters:
            await self._present_snapshot(self._snapshot(state))
        # A cold tab has no last-known projection. Do not read the entire wire
        # synchronously inside prepare_navigation before its first painted frame.
        self.call_after_refresh(self._refresh)

    @property
    def visible_filters(self) -> tuple[bool, bool]:
        settings = cast("ToadApp", self.app).settings
        return settings.get("sidebar.show_stopped", bool), settings.get("sidebar.show_archived", bool)

    def _settings_changed(self, update: tuple[str, object]) -> None:
        if update[0] in {"sidebar.show_stopped", "sidebar.show_archived"}:
            self._last_revision = None
            self._refresh()

    def _mode_changed(self, mode_name: str, *, force: bool = False) -> None:
        from toad.screens.comms import CommsScreen

        if not self.is_attached or self.screen is not self.app.screen:
            return
        target = self.screen.target if isinstance(self.screen, CommsScreen) and self.screen.is_active else None
        if not force and self._rendered_mode == (mode_name, target):
            return
        if self._virtual:
            self._rendered_mode = (mode_name, target)
            if self._last_snapshot is not None:
                self._rebuild_virtual(self._last_snapshot)
            return
        for row in self.query(ThreadRow):
            row.current = row.mode_name == mode_name
        for row in self._row_map.values():
            row.current = row.target_name == target
        self._rendered_mode = (mode_name, target)

    def _run_test_hook(self) -> None:
        """Opt-in test seam: TOAD_COMMS_TEST_TARGET drives the same code
        path a row click takes (SelectTarget -> main pane switch). No-op
        unless the env var is set."""
        target = os.environ.pop("TOAD_COMMS_TEST_TARGET", "")
        if not target:
            return
        if target.startswith("#"):
            self.post_message(SelectTarget(target, "channel"))
        elif self.session_thread and target == self.session_thread:
            self.post_message(SelectTarget(target, "session"))
        else:
            self.post_message(SelectTarget(target, "dm"))

    def _comms_registry_names(self) -> list[str]:
        """Registered thread names on the wire (for view toggles)."""
        try:
            local_threads = cast("ToadApp", self.app).local_coordination_threads()
            return [
                name
                for name in wire(_comms_root()).registry.active_threads()
                if name not in local_threads
            ]
        except Exception:
            return []

    # ─── Data ─────────────────────────────────────────────────────────────────

    def _snapshot(self, state: CoordinationSnapshot | None = None) -> SidebarSnapshot:
        comms = self._wire
        app = cast("ToadApp", self.app)
        if state is None:
            show_stopped, show_archived = self.visible_filters
            state = comms.viewer_snapshot(
                str(app.project_dir), show_stopped=show_stopped, show_archived=show_archived
            )
        all_people = {person.thread.name: person for person in state.threads}
        session_threads: dict[str, str] = {}
        claimed_threads: set[str] = set()
        for details in app.session_tracker.ordered_sessions:
            screen = app._main_session_screen(details.mode_name)
            if screen is None:
                continue
            name = screen._comms_thread
            if name not in all_people and screen._agent_session_id in all_people:
                name = screen._agent_session_id
            if name in all_people and name not in claimed_threads:
                session_threads[details.mode_name] = name
                claimed_threads.add(name)
        return SidebarSnapshot(state, session_threads, all_people)

    @staticmethod
    def _person_kind(person: ThreadView) -> str:
        if person.status in {ThreadStatus.ARCHIVED, ThreadStatus.STOPPED}:
            # A stopped/archived executor has no runnable native owner. Its
            # wire DM stays viewable without implicitly starting it on click.
            return "dm"
        return "thread" if person.thread.session_file or person.thread.pid > 0 else "dm"

    def _refresh(self) -> None:
        if self._snapshot_pending or not self.is_attached:
            return
        try:
            # A refresh timer can fire while a mode's screen stack is being
            # removed during tab closure or application shutdown.
            if not self.is_attached or self.screen is not self.app.screen:
                return
            self.app.coordination_observed.publish(None)
            revision = self._wire.revision()
            if (revision == self._last_revision and self.session_thread == self._last_actor
                    and self.visible_filters == self._last_filters):
                return
            self._snapshot_pending = True
            self.run_worker(self._poll_snapshot(revision))
        except Exception:
            self._snapshot_pending = False
            return

    async def _poll_snapshot(self, revision: WireRevision) -> None:
        async with self._snapshot_lock:
            await self._read_snapshot(revision)

    async def _read_snapshot(self, revision: WireRevision) -> None:
        try:
            actor = self.session_thread
            filters = self.visible_filters
            await cast("ToadApp", self.app).mark_visible_thread_read()
            state = await asyncio.to_thread(
                self._wire.viewer_snapshot, str(cast("ToadApp", self.app).project_dir),
                show_stopped=filters[0], show_archived=filters[1],
            )
            if (not self.is_attached or self.screen is not self.app.screen
                    or actor != self.session_thread or filters != self.visible_filters):
                return
            snapshot = self._snapshot(state)
            if state.read_marker_notice != self._last_read_marker_notice:
                self._last_read_marker_notice = state.read_marker_notice
                if state.read_marker_notice:
                    self.notify(
                        state.read_marker_notice,
                        title="Read positions",
                        severity="warning",
                    )
            cast("ToadApp", self.app)._sidebar_snapshot = state
            self._last_revision, self._last_actor, self._last_filters = revision, actor, filters
            await self._present_snapshot(snapshot)
        except (OSError, ValueError):
            # An external writer may be replacing/recovering the wire. Retry on
            # the next poll without blocking or terminating the view.
            return
        finally:
            self._snapshot_pending = False

    # ─── Rendering ────────────────────────────────────────────────────────────

    async def _present_snapshot(self, snapshot: SidebarSnapshot) -> None:
        async with self._presentation_lock:
            changed = snapshot != self._last_snapshot
            if (changed or self._rendered_expansion != self.navigation.expanded
                    or self._rendered_actions != cast("ToadApp", self.app).pending_thread_actions):
                with self.app.batch_update():
                    await self._rebuild(snapshot)
                if changed:
                    cast("ToadApp", self.app).open_tabs_changed.publish(None)
            else:
                self.apply_selection()
                self._mode_changed(cast("ToadApp", self.app).current_mode)
                self._sync_spinner(snapshot)

    async def _rebuild(self, snapshot: SidebarSnapshot) -> None:
        if self._virtual:
            self._rebuild_virtual(snapshot)
            return
        self._last_snapshot = snapshot
        from toad.widgets.side_bar import SideBarCollapsible

        control = self.query_ancestor(SideBarCollapsible).header_control
        assert isinstance(control, ChannelListSort)
        control.update_order(snapshot.wire.channel_order)
        desired_keys = [
            ("irc" if view.channel.aggregate else "channel", view.channel.name)
            for view in snapshot.wire.channels
        ]
        if not self.query(NewSessionButton):
            await self.mount(NewSessionButton())
        for key in set(self._row_map) - set(desired_keys):
            row = self._row_map.pop(key)
            await row.query_ancestor(ChannelGroup).remove()
        new_groups: list[ChannelGroup] = []
        for key in desired_keys:
            if key not in self._row_map:
                row = self._row_map[key] = CommsRow(*key, key[1])
                new_groups.append(ChannelGroup(
                    row, expanded=self.navigation.expanded.get(key[1], key[0] == "irc"),
                ))
        if new_groups:
            await self.mount(*new_groups)
        for view in snapshot.wire.channels:
            kind = "irc" if view.channel.aggregate else "channel"
            channel_row = self._row_map[(kind, view.channel.name)]
            unread = snapshot.wire.channel_unread.get(view.channel.name, 0)
            channel_row.set_label(f"{'* ' if view.channel.pinned else ''}{view.channel.name}")
            group = channel_row.query_ancestor(ChannelGroup)
            group.update_unread(unread)
            group.update_activity(view, snapshot.all_people)
            channel_row.set_class(bool(unread), "-unread")
            await self._update_channel_group(channel_row, view, snapshot)
        ordered = [self.query_one(NewSessionButton), *(
            self._row_map[key].query_ancestor(ChannelGroup) for key in desired_keys
        )]
        if list(self.children) != ordered:
            positions = {widget: index for index, widget in enumerate(ordered)}
            self.sort_children(key=positions.__getitem__)
        self.apply_selection(force=True)
        self._mode_changed(cast("ToadApp", self.app).current_mode, force=True)
        self._rendered_expansion = dict(self.navigation.expanded)
        self._rendered_actions = dict(cast("ToadApp", self.app).pending_thread_actions)
        self._sync_spinner(snapshot)
        # The ordinary widget-tree roster must retain the same full text as
        # the virtual roster. Only the content grows; the outer sidebar owns
        # both native scrollbars and keeps their geometry at the visible edge.
        widest = max((Content(view.channel.name).cell_length + 12
                      for view in snapshot.wire.channels), default=0)
        widest = max(widest, max((Content(person.presentation.label).cell_length + 8
                                  for person in snapshot.all_people.values()), default=0))
        widest = max(widest, max((Content(person.presentation.summary).cell_length + 8
                                  for person in snapshot.all_people.values()), default=0))
        widest = min(widest, 512)
        panel = self.query_ancestor(SideBarCollapsible)
        if widest != self._horizontal_width:
            self._horizontal_width = widest
            panel.styles.min_width = widest

    def _rebuild_virtual(self, snapshot: SidebarSnapshot) -> None:
        """Project canonical channel/member order into one viewport-painted list."""
        self._last_snapshot = snapshot
        from toad.widgets.side_bar import SideBarCollapsible

        control = self.query_ancestor(SideBarCollapsible).header_control
        assert isinstance(control, ChannelListSort)
        control.update_order(snapshot.wire.channel_order)
        app = cast("ToadApp", self.app)
        modes = {name: mode for mode, name in snapshot.session_threads.items()}
        selected = self.navigation.selected
        busy_rows: dict[int, tuple[str, bool, bool, bool]] = {}
        choices: dict[str, VirtualChoice] = {}
        choices["new-session"] = VirtualChoice("new-session", "", "")
        options: list[Option] = [Option("+ New Session", id="new-session")]
        ansi = app.theme.startswith("ansi-")
        listing = self.query_one(VirtualChannelList)
        width = self.scroll_containers[0].scrollable_content_region.width or 34
        longest = width
        for view in snapshot.wire.channels:
            channel = view.channel.name
            kind = "irc" if view.channel.aggregate else "channel"
            key = f"channel:{channel}"
            choice = choices[key] = VirtualChoice(kind, channel, channel)
            unread = snapshot.wire.channel_unread.get(channel, 0)
            prefix = "▾" if self.navigation.expanded.get(channel, kind == "irc") else "▸"
            name = f"{'* ' if view.channel.pinned else ''}{channel}"
            right = f"{'(' + str(unread) + ') ' if unread else ''}{view.channel.order.label} ▾"
            left = f"{prefix} {name}"
            text = f"{left}{' ' * max(1, width - Content(left).cell_length - Content(right).cell_length)}{right}"
            longest = max(longest, Content(text).cell_length)
            active = any(
                person.thread.executing or person.presentation.busy
                for member in view.members if (person := snapshot.all_people.get(member)) is not None
            )
            row_selected = selected == SidebarSelection(channel, channel)
            options.append(Option(styled_row(text, selected=row_selected, ansi=ansi,
                                             busy=active, unread=bool(unread)), id=key))
            if prefix != "▾":
                continue
            for member in view.members:
                person = snapshot.all_people.get(member)
                if person is None:
                    continue
                mode = modes.get(member)
                member_kind = "session" if mode else self._person_kind(person)
                choice_id = f"member:{channel}:{member}"
                choices[choice_id] = VirtualChoice(member_kind, member, channel, mode)
                badge = (snapshot.wire.thread_unread.get(member, 0) if member_kind == "session"
                         else snapshot.wire.unread.get(member, 0))
                label = person.presentation.label
                action_status = app.pending_thread_actions.get(member)
                summary = " ".join((action_status or person.presentation.summary).splitlines())
                pin = "* " if member in view.pinned_members else ""
                text = f"  {f'({badge}) ' if badge else ''}{pin}{label}\n    {summary}"
                longest = max(longest, *(Content(line).cell_length for line in text.splitlines()))
                row_selected = selected == SidebarSelection(channel, member)
                if person.presentation.busy:
                    busy_rows[len(options)] = (text, row_selected, bool(badge), ansi)
                shown = text.replace("⌛ ", f"{FRAMES[self._spinner_phase]} ", 1) if person.presentation.busy else text
                options.append(Option(styled_row(shown, selected=row_selected, ansi=ansi,
                                                 busy=bool(action_status or person.presentation.busy),
                                                 muted=True, unread=bool(badge)), id=choice_id))
        self.query_ancestor(SideBarCollapsible).styles.min_width = min(longest, 4096)
        old_scroll = listing.scroll_y
        old_ids = [option.id for option in listing.options]
        if old_ids != [option.id for option in options]:
            listing.set_options(options)
            listing.scroll_to(y=old_scroll, animate=False, immediate=True)
        else:
            for index, option in enumerate(options):
                old = listing.get_option_at_index(index).prompt
                if not isinstance(old, Content) or not old.is_same(option.prompt):
                    listing.replace_option_prompt_at_index(index, option.prompt)
        self._virtual_targets = choices
        self._busy_virtual_rows = busy_rows
        self._rendered_selection = selected
        self._rendered_expansion = dict(self.navigation.expanded)
        self._rendered_actions = dict(app.pending_thread_actions)
        self._selection_applied = True
        self._sync_spinner(snapshot)

    def _virtual_toggle(self, channel: str) -> None:
        self.navigation.expanded[channel] = not self.navigation.expanded.get(channel, channel == ALL_COMMS_TARGET)
        if self._last_snapshot is not None:
            self._rebuild_virtual(self._last_snapshot)

    def _virtual_context_menu(self, choice: VirtualChoice, offset) -> None:
        if choice.kind in {"irc", "channel"}:
            self._show_channel_menu(choice.channel, offset)
        elif choice.kind != "new-session":
            self._show_thread_menu(choice.target, offset, mode_name=choice.mode,
                                    channel=choice.channel)

    @on(OptionList.OptionSelected)
    async def on_virtual_option_selected(self, event: OptionList.OptionSelected) -> None:
        if not self._virtual or not isinstance(event.option_list, VirtualChannelList):
            return
        event.stop()
        choice = self._virtual_targets.get(event.option_id or "")
        if choice is None:
            return
        if choice.kind == "new-session":
            self.app.post_message(messages.SessionCreate(self.screen.id or self.app.current_mode))
            return
        self.navigation.selected = SidebarSelection(choice.channel, choice.target)
        self.selected = choice.target
        self.apply_selection(force=True)
        if choice.mode is not None:
            self.app.switch_mode(choice.mode)
        else:
            from toad.screens.comms import CommsScreen
            from toad.screens.main import MainScreen

            # Keep MainScreen/CommsScreen as the native routing owners, but
            # dispatch the already-selected list option to them directly.
            # A second queued SelectTarget message needlessly delays the
            # first channel frame after a pointer click.
            if isinstance(self.screen, MainScreen):
                if choice.kind == "dm":
                    self.screen._last_dm_target = choice.target
                await self.screen._open_comms(choice.target, choice.kind)
            elif isinstance(self.screen, CommsScreen):
                await self.screen._open(choice.target, choice.kind)
            else:
                self.post_message(SelectTarget(choice.target, choice.kind))

    async def _update_channel_group(self, row: CommsRow, view: ChannelView,
                               snapshot: SidebarSnapshot) -> None:
        if row.is_attached:
            row.tooltip = f"{len(view.members)} threads · tags: {', '.join(sorted(view.channel.tags)) or 'all'}"
            group = row.query_ancestor(ChannelGroup)
            expanded = self.navigation.expanded.get(row.target_name, row.kind == "irc")
            if group.expanded != expanded:
                group.expanded = expanded
                # The glyph has fixed dimensions. Mounting/removing members
                # owns the layout change, not repainting an unchanged arrow
                # on every wire snapshot (which reflows the transcript too).
                group.disclosure.update("▾" if expanded else "▸", layout=False)
            await group.update_members(view, snapshot)

    # ─── Keyboard ─────────────────────────────────────────────────────────────

    @property
    def session_rows(self) -> list[ThreadRow]:
        """Mounted thread rows whose authoritative projection has an open view."""
        return [row for row in self.query(ThreadRow) if row.mode_name is not None]

    def _ordered_rows(self) -> list[CommsRow]:
        return [row for group in self.children if isinstance(group, ChannelGroup)
                for row in (group.row, *group.member_rows)]

    def action_cursor_up(self) -> None:
        if self._virtual:
            self.query_one(VirtualChannelList).action_cursor_up()
            return
        super().action_cursor_up()

    def action_cursor_down(self) -> None:
        if self._virtual:
            self.query_one(VirtualChannelList).action_cursor_down()
            return
        super().action_cursor_down()

    def action_open_selected(self) -> None:
        if self._virtual:
            self.query_one(VirtualChannelList).action_select()
            return
        rows = self._ordered_rows()
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
        self.selected = target.target_name
        target.action_open_selected()

    async def focus_current_session(self) -> None:
        """Focus the current session in this authoritative sessions view."""
        await self.sync_sessions()
        if self._virtual:
            current_mode = cast("ToadApp", self.app).current_mode
            listing = self.query_one(VirtualChannelList)
            selected_id = next((key for key, choice in self._virtual_targets.items()
                                if choice.mode == current_mode and choice.channel == ALL_COMMS_TARGET), None)
            if selected_id is None:
                if not self.navigation.expanded.get(ALL_COMMS_TARGET, True):
                    self.navigation.expanded[ALL_COMMS_TARGET] = True
                    if self._last_snapshot is not None:
                        self._rebuild_virtual(self._last_snapshot)
                selected_id = next((key for key, choice in self._virtual_targets.items()
                                    if choice.mode == current_mode), None)
            selected_id = selected_id or f"channel:{ALL_COMMS_TARGET}"
            if selected_id in self._virtual_targets:
                listing.highlighted = listing.get_option_index(selected_id)
                listing.scroll_to_highlight()
                listing.focus()
            return
        rows = self._ordered_rows()
        if not rows:
            return
        current_mode = cast("ToadApp", self.app).current_mode
        if not any(row.mode_name == current_mode for row in self.session_rows):
            aggregate = self._row_map.get(("irc", ALL_COMMS_TARGET))
            if aggregate is not None:
                group = aggregate.query_ancestor(ChannelGroup)
                if not group.expanded:
                    group.toggle_members()
                    await group._sync_members()
                    rows = self._ordered_rows()
        target = next((row for row in self.session_rows if row.mode_name == current_mode), rows[0])
        self._cursor = rows.index(target)
        self._apply_cursor(rows)
        target.focus()

    # ─── Context menu ─────────────────────────────────────────────────────────

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
        if isinstance(row, ThreadRow):
            if row.mode_name is None:
                self._select(row)
            self._show_thread_menu(
                row.target_name, event.screen_offset, mode_name=row.mode_name,
                channel=row.query_ancestor(ChannelGroup).row.target_name,
            )
            return
        self._select(row)
        if row.kind in {"dm", "thread", "session"}:
            self._show_thread_menu(
                row.target_name, event.screen_offset,
                channel=row.query_ancestor(ChannelGroup).row.target_name,
            )
        elif row.kind in {"channel", "irc"}:
            self._show_channel_menu(row.target_name, event.screen_offset)

    def _select(self, row: CommsRow) -> None:
        row.focus()

    def _show_thread_menu(
        self, name: str, menu_offset, *, mode_name: str | None = None,
        channel: str | None = None,
    ) -> None:
        from toad.widgets.comms_menu import show_thread_menu

        def post(action: str) -> None:
            self.post_message(self.ThreadAction(name, action))

        declared_actions = context_tool_catalog("thread")
        person = (self._last_snapshot or self._snapshot()).all_people.get(name)
        if person is not None and person.status is ThreadStatus.ARCHIVED:
            declared_actions = [item for item in declared_actions
                                if item["name"] not in {"comms_start", "comms_stop", "comms_archive"}]
        elif person is not None and person.status.active and person.thread.pid > 0:
            declared_actions = [item for item in declared_actions if item["name"] != "comms_start"]
        actions: dict[str, Callable[[], None]] = {
            str(declaration["name"]): partial(post, str(declaration["name"]))
            for declaration in declared_actions
        }
        actions["copy"] = lambda: post("copy")
        if mode_name is not None:
            actions["close_view"] = lambda: self.app.post_message(
                messages.SessionArchive(mode_name)
            )

        items = [
            (str(declaration["name"]), str(declaration["action_label"]))
            for declaration in declared_actions
        ] + [("copy", "Copy name")]
        if channel is not None:
            snapshot = self._last_snapshot or self._snapshot()
            view = next(view for view in snapshot.wire.channels if view.channel.name == channel)
            pinned = name in view.pinned_members
            items.insert(0, ("pin", "Unpin from this channel" if pinned else "Pin in this channel"))
            actions["pin"] = partial(self._set_pin, channel, not pinned, thread=name)
        if mode_name is not None:
            items.append(("close_view", "Close view"))

        show_thread_menu(
            self.app.screen,
            menu_offset,
            name,
            items,
            actions,
        )

    def _show_channel_menu(self, name: str, menu_offset) -> None:
        from toad.widgets.comms_menu import show_channel_menu

        def post(action: str) -> None:
            self.post_message(self.ThreadAction(name, action))

        acknowledge = next(
            declaration
            for declaration in context_tool_catalog("thread")
            if declaration["name"] == "comms_ack"
        )
        channel = self._wire.channel_catalog.resolve(name)
        actions = {
            "pin": partial(self._set_pin, name, not channel.pinned),
            "comms_ack": lambda: post("comms_ack"),
            "copy": lambda: post("copy"),
        }
        any_mode_label = None
        if channel.exact:
            actions["any_mode"] = partial(
                self._set_any_mode, name, not channel.any_mode
            )
            any_mode_label = (
                "Show channel only" if channel.any_mode else "Show member activity"
            )
        show_channel_menu(
            self.app.screen,
            menu_offset,
            name,
            actions,
            acknowledge_label=str(acknowledge["action_label"]),
            pin_label="Unpin channel" if channel.pinned else "Pin channel",
            any_mode_label=any_mode_label,
        )

    def _set_any_mode(self, channel: str, enabled: bool) -> None:
        try:
            self._wire.set_channel_any_mode(channel, enabled)
        except (OSError, ValueError) as error:
            self.notify(str(error), title="Channel activity", severity="error")
        self._refresh()

    def _set_pin(self, channel: str, pinned: bool, *, thread: str | None = None) -> None:
        try:
            if thread is None:
                self._wire.set_channel_pinned(channel, pinned)
            else:
                self._wire.set_thread_pinned(channel, thread, pinned)
        except (OSError, ValueError) as error:
            self.notify(str(error), title="Pin action", severity="error")
        self._refresh()

    def _show_view_menu(self, mode_name: str, menu_offset) -> None:
        from toad.widgets.comms_menu import show_view_menu

        details = cast("ToadApp", self.app).session_tracker.get_session(mode_name)
        if details is None:
            return
        show_view_menu(
            self.app.screen,
            menu_offset,
            details.title or "Session view",
            lambda: self.app.post_message(messages.SessionArchive(mode_name)),
        )

    # ─── Actions ──────────────────────────────────────────────────────────────

    @on(ThreadAction)
    def _do_thread_action(self, event: ThreadAction) -> None:
        if event.action == "comms_fork":
            return  # The owning screen collects the fork specification.
        event.stop()
        name = event.name
        session_modes = [
            mode
            for mode, thread in (self._last_snapshot.session_threads if self._last_snapshot else {}).items()
            if thread == name
        ]
        try:
            if event.action == "copy":
                self.app.copy_to_clipboard(name)
            else:
                cast("ToadApp", self.app).invoke_thread_action(
                    event.action, name, self.session_thread, tuple(session_modes)
                )
        except Exception as error:
            self.notify(str(error), title="Session action", severity="error")
        self._refresh()
