"""Agent-comms channels and remote sessions for Toad's session panel.

IRC semantics for fully-detailed agent threads:

- **Click** a thread row -> opens its DM as a native Toad session.
- **Click** a channel row -> opens that channel as a native Toad session.
- **Right-click** -> context menu: fork, stop, acknowledge, copy name.
- Live rows: status, unread badges, task, activity (``working bash: …``).

View, not authority: reads the wire (``AGENT_COMMS_ROOT``) directly and
acts through ``agent_comms`` operations.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, cast

from textual import on
from textual.binding import Binding
from textual.containers import Vertical
from textual.dom import DOMNode
from textual.message import Message
from textual.reactive import reactive
from textual.content import Content
from textual.widgets import Static

from agent_comms import (
    ActivityState,
    ThreadStatus,
    context_tool_catalog,
    invoke_context_tool,
)
from agent_comms.operations import wire

from toad import messages
from toad.session_tracker import SessionDetails
from toad.widgets.session_sidebar import SessionRow

if TYPE_CHECKING:
    from toad.app import ToadApp


def _comms_root() -> Path:
    return Path(os.environ.get("AGENT_COMMS_ROOT", "~/.agent-comms")).expanduser()


def _display_path(path: Path) -> str:
    try:
        return f"~/{path.resolve().relative_to(Path.home())}"
    except ValueError:
        return str(path.resolve())


def _fmt_age(ts: float, now: float) -> str:
    age = max(0.0, now - ts)
    if age < 10:
        return "now"
    if age < 60:
        return f"{int(age // 10) * 10}s"
    if age < 3600:
        return f"{int(age // 60)}m"
    if age < 86400:
        return f"{int(age // 3600)}h"
    return f"{int(age // 86400)}d"


class SelectTarget(Message):
    """User picked a view target: a channel, a DM peer, or the session."""

    def __init__(self, target: str, kind: str) -> None:
        self.target = target
        self.kind = kind  # "channel" | "dm" | "session"
        super().__init__()


class CommsRow(Static):
    """One interactive row: a channel or a thread."""

    DEFAULT_CSS = """
    CommsRow {
        height: auto;
        padding: 0;
    }
    CommsRow:hover { background: $surface-lighten-2; }
    CommsRow.-selected { background: $accent-darken-2; }
    CommsRow:focus { background: $accent-darken-2; text-style: bold; }
    CommsRow:ansi:hover,
    CommsRow:ansi.-selected,
    CommsRow:ansi:focus {
        background: ansi_bright_white;
        color: ansi_black;
        text-style: bold;
    }
    CommsRow.-unread .row-name { text-style: bold; }
    """

    BINDINGS = [
        Binding("down", "cursor_down", "Next", show=False),
        Binding("up", "cursor_up", "Previous", show=False),
        Binding("enter", "open_selected", "Open", show=False),
    ]

    can_focus = True

    def __init__(self, kind: str, name: str, label: str, unread: int = 0) -> None:
        super().__init__(label)
        self.kind = kind  # "channel" | "dm" | "session"
        self.target_name = name
        self._label = label
        self.unread = unread
        self.selected = False

    def set_label(self, label: str) -> None:
        if label != self._label:
            self._label = label
            self.update(label)

    def _sidebar(self):
        parent = self.parent
        while parent is not None and not isinstance(parent, CommsSidebar):
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
        self.post_message(SelectTarget(self.target_name, self.kind))

    def on_focus(self) -> None:
        """Keep the sidebar cursor in sync with keyboard focus."""
        sidebar = self._sidebar()
        if sidebar is not None:
            rows = sidebar._ordered_rows()
            if self in rows:
                sidebar._cursor = rows.index(self)
                sidebar._apply_cursor(rows)

    def on_click(self, event) -> None:
        if event.button == 3:
            return  # right click handled by context menu in CommsSidebar
        self.post_message(SelectTarget(self.target_name, self.kind))


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


class CommsSidebar(Vertical):
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
    CommsSidebar .activity {
        color: $success;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
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

    class SessionAction(Message):
        """Context-menu action on a local Toad session."""

        def __init__(self, mode_name: str, action: str) -> None:
            self.mode_name = mode_name
            self.action = action
            super().__init__()

    def __init__(
        self, session_thread: str = "", selected_target: str = "", **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.session_thread = session_thread
        self.selected = selected_target
        self._row_map: dict[tuple[str, str], CommsRow] = {}
        self._activity_map: dict[str, Static] = {}
        self._activity_text: dict[str, str] = {}
        self._session_rows: dict[str, SessionRow] = {}
        self.can_focus = True
        self._cursor = 0

    def on_mount(self) -> None:
        app = cast("ToadApp", self.app)
        app.session_update_signal.subscribe(self, self._session_updated)
        app.mode_change_signal.subscribe(self, self._mode_changed)
        self.set_interval(1.5, self._refresh)
        self._refresh()
        self._run_test_hook()

    async def _session_updated(self, update: tuple[str, SessionDetails | None]) -> None:
        mode_name, details = update
        row = self._session_rows.get(mode_name)
        if details is None:
            if row is not None:
                del self._session_rows[mode_name]
                await row.remove()
            return
        if row is None:
            row = SessionRow(details)
            self._session_rows[mode_name] = row
            channels_heading = next(
                (
                    child
                    for child in self.children
                    if isinstance(child, Static) and child.has_class("section")
                ),
                None,
            )
            if channels_heading is None:
                await self.mount(row)
            else:
                await self.mount(row, before=channels_heading)
        else:
            row.update_details(details)
        self._mode_changed(cast("ToadApp", self.app).current_mode)

    async def sync_sessions(self) -> None:
        """Reconcile tracked rows before a resumed screen can accept input."""
        sessions = cast("ToadApp", self.app).session_tracker.ordered_sessions
        desired = {details.mode_name for details in sessions}
        for mode_name, row in list(self._session_rows.items()):
            if mode_name not in desired:
                del self._session_rows[mode_name]
                await row.remove()
        for details in sessions:
            await self._session_updated((details.mode_name, details))

    def _mode_changed(self, mode_name: str) -> None:
        for row in self._session_rows.values():
            row.current = row.mode_name == mode_name

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
            return list(wire(_comms_root()).registry.active_threads())
        except Exception:
            return []

    # ─── Data ─────────────────────────────────────────────────────────────────

    def _snapshot(self) -> dict:
        comms = wire(_comms_root())
        now = time.time()
        who = [
            person
            for person in comms.presence()
            if person["name"] != self.session_thread
        ]
        channels = comms.channels()
        if self.session_thread in comms.registry:
            unread = comms.pending_counts(self.session_thread)
            unread_by_channel = {
                channel: unread.get(channel, 0) for channel in channels
            }
            unread_by_person = {
                person["name"]: unread.get(person["name"], 0)
                for person in who
                if person["name"] != self.session_thread
            }
        else:
            unread_by_channel = dict.fromkeys(channels, 0)
            unread_by_person = {}
        activity = comms.all_activity()
        return {
            "who": who,
            "channels": channels,
            "unread_by_channel": unread_by_channel,
            "unread_by_person": unread_by_person,
            "activity": activity,
            "now": now,
        }

    def _refresh(self) -> None:
        if self.screen is not self.app.screen:
            return
        try:
            snapshot = self._snapshot()
        except Exception:
            return
        self._rebuild(snapshot)

    # ─── Rendering ────────────────────────────────────────────────────────────

    def _rebuild(self, snapshot: dict) -> None:
        selection = self.selected
        now = snapshot["now"]
        activity = snapshot["activity"]
        channels = snapshot["channels"]
        people = snapshot["who"]
        sessions = cast("ToadApp", self.app).session_tracker.ordered_sessions
        desired_keys = [("dm", person["name"]) for person in people]
        desired_keys.extend(("channel", channel) for channel in channels)

        focused = self.app.focused
        focused_key = None
        if isinstance(focused, CommsRow):
            focused_key = (focused.kind, focused.target_name)

        if list(self._row_map) != desired_keys:
            self.remove_children()
            self._row_map.clear()
            self._activity_map.clear()
            self._activity_text.clear()
            self._session_rows.clear()

            self.mount(NewSessionButton())

            for person in people:
                name = person["name"]
                kind = "dm"
                key = (kind, name)
                row = CommsRow(kind, name, name)
                detail = Static("", classes="activity")
                detail.display = False
                self._row_map[key] = row
                self._activity_map[name] = detail
                self.mount(row, detail)

            for details in sessions:
                session_row = SessionRow(details)
                self._session_rows[details.mode_name] = session_row
                self.mount(session_row)

            self.mount(Static("CHANNELS", classes="section"))
            for channel in channels:
                key = ("channel", channel)
                row = CommsRow(*key, channel)
                self._row_map[key] = row
                self.mount(row)

        for details in sessions:
            self._session_rows[details.mode_name].update_details(details)
        self._mode_changed(cast("ToadApp", self.app).current_mode)

        for channel in channels:
            unread = snapshot["unread_by_channel"].get(channel, 0)
            label = f"{channel} ({unread})" if unread else channel
            row = self._row_map[("channel", channel)]
            row.set_label(label)
            row.unread = unread
            selected = channel == selection or row is focused
            row.selected = selected
            row.set_class(selected, "-selected")
            row.set_class(bool(unread), "-unread")

        for person in people:
            name = person["name"]
            kind = "dm"
            unread = snapshot["unread_by_person"].get(name, 0)
            if person["status"] == ThreadStatus.STOPPED.value:
                status_mark = "○"
            elif unread:
                status_mark = f"●{unread}"
            else:
                status_mark = "●"
            task = f" — {person['task']}" if person["task"] else ""
            label = (
                f"{status_mark} {name}{task}" f" [{_fmt_age(person['last_seen'], now)}]"
            )
            row = self._row_map[(kind, name)]
            row.set_label(label)
            row.unread = unread
            selected = name == selection or row is focused
            row.selected = selected
            row.set_class(selected, "-selected")
            row.set_class(bool(unread), "-unread")

            act = activity.get(name)
            show_activity = (
                act is not None
                and act.state is not ActivityState.IDLE
                and now - act.timestamp < 120
            )
            activity_row = self._activity_map[name]
            model = person.get("model") or ""
            percent = person.get("context_percent")
            runtime = ""
            if model:
                runtime = model
            if percent is not None:
                runtime += (" · " if runtime else "") + f"{percent:.1f}% context"
            activity_row.display = show_activity or bool(runtime)
            if show_activity and act is not None:
                activity_detail = " ".join(act.detail.splitlines())
                detail_text = f" {activity_detail}" if activity_detail else ""
                age = _fmt_age(act.timestamp, now)
                text = f"    ⟳ {act.state.value}{detail_text} ({age})"
                if runtime:
                    text += f"\n    {runtime}"
                if self._activity_text.get(name) != text:
                    self._activity_text[name] = text
                    activity_row.update(text)
            elif runtime:
                text = f"    {runtime}"
                if self._activity_text.get(name) != text:
                    self._activity_text[name] = text
                    activity_row.update(text)
            else:
                self._activity_text.pop(name, None)

        if focused_key is not None and focused_key in self._row_map:
            self._row_map[focused_key].focus()

    # ─── Keyboard ─────────────────────────────────────────────────────────────

    def _ordered_rows(self) -> list[CommsRow | SessionRow]:
        return cast(
            list[CommsRow | SessionRow], list(self.query("CommsRow, SessionRow"))
        )

    def action_cursor_up(self) -> None:
        rows = self._ordered_rows()
        if rows:
            self._cursor = max(0, min(len(rows) - 1, self._cursor - 1))
            self._apply_cursor(rows)
            rows[self._cursor].focus()

    def action_cursor_down(self) -> None:
        rows = self._ordered_rows()
        if rows:
            self._cursor = min(len(rows) - 1, self._cursor + 1)
            self._apply_cursor(rows)
            rows[self._cursor].focus()

    def _apply_cursor(self, rows: list[CommsRow | SessionRow]) -> None:
        for index, row in enumerate(rows):
            if isinstance(row, CommsRow):
                row.selected = index == self._cursor
                row.set_class(index == self._cursor, "-selected")
        rows[self._cursor].scroll_visible(animate=False)

    def action_open_selected(self) -> None:
        rows = self._ordered_rows()
        focused = self.app.focused if self.app else None
        if isinstance(focused, (CommsRow, SessionRow)) and focused in rows:
            target = focused
            self._cursor = rows.index(target)
        elif 0 <= self._cursor < len(rows):
            target = rows[self._cursor]
        else:
            return
        self._apply_cursor(rows)
        if isinstance(target, SessionRow):
            target.post_message(messages.SessionSwitch(target.mode_name))
        else:
            self.selected = target.target_name
            target.post_message(SelectTarget(target.target_name, target.kind))

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
            if isinstance(node, (CommsRow, SessionRow)):
                row = node
                break
            node = node.parent
        if row is None:
            return
        if isinstance(row, SessionRow):
            self._show_session_menu(row.mode_name, event.screen_offset)
            return
        self._select(row)
        if row.kind in {"dm", "session"}:
            self._show_thread_menu(row.target_name, event.screen_offset)
        else:
            self._show_channel_menu(row.target_name, event.screen_offset)

    def _select(self, row: CommsRow) -> None:
        self.selected = row.target_name
        for other in self.query(CommsRow):
            other.remove_class("-selected")
        row.add_class("-selected")

    def _show_thread_menu(self, name: str, menu_offset) -> None:
        from toad.widgets.comms_menu import show_thread_menu

        def post(action: str) -> None:
            self.post_message(self.ThreadAction(name, action))

        declared_actions = context_tool_catalog("thread")
        actions: dict[str, Callable[[], None]] = {
            str(declaration["name"]): partial(post, str(declaration["name"]))
            for declaration in declared_actions
        }
        actions["copy"] = lambda: post("copy")

        show_thread_menu(
            self.app.screen,
            menu_offset,
            name,
            [
                (str(declaration["name"]), str(declaration["action_label"]))
                for declaration in declared_actions
            ]
            + [("copy", "Copy name")],
            actions,
        )

    def _show_session_menu(self, mode_name: str, menu_offset) -> None:
        from toad.widgets.comms_menu import RenameSessionDialog, show_session_menu

        details = cast("ToadApp", self.app).session_tracker.get_session(mode_name)
        if details is None:
            return

        def rename() -> None:
            def apply_name(name: str | None) -> None:
                if name:
                    self.app.post_message(messages.SessionRename(mode_name, name))

            self.app.push_screen(RenameSessionDialog(details.title), apply_name)

        def post(action: str) -> None:
            self.post_message(self.SessionAction(mode_name, action))

        is_agent_session = (
            cast("ToadApp", self.app)._main_session_screen(mode_name) is not None
        )
        show_session_menu(
            self.app.screen,
            menu_offset,
            details.title,
            {
                "rename": rename,
                "archive": lambda: post("archive"),
                "delete": lambda: post("delete"),
            },
            is_agent_session=is_agent_session,
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
        show_channel_menu(
            self.app.screen,
            menu_offset,
            name,
            {
                "comms_ack": lambda: post("comms_ack"),
                "copy": lambda: post("copy"),
            },
            acknowledge_label=str(acknowledge["action_label"]),
        )

    # ─── Actions ──────────────────────────────────────────────────────────────

    @on(ThreadAction)
    def _do_thread_action(self, event: ThreadAction) -> None:
        name = event.name
        try:
            comms = wire(_comms_root())
            if event.action == "copy":
                self.app.copy_to_clipboard(name)
            elif event.action != "comms_fork":
                invoke_context_tool(
                    comms,
                    event.action,
                    subject=name,
                    actor=self.session_thread,
                )
        except Exception as error:
            self.notify(str(error), title="Session action", severity="error")
        self._refresh()

    @on(SessionAction)
    def _do_session_action(self, event: SessionAction) -> None:
        if event.action == "archive":
            self.app.post_message(messages.SessionArchive(event.mode_name))
        elif event.action == "delete":
            self.app.post_message(messages.SessionDelete(event.mode_name))
