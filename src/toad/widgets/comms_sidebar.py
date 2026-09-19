"""Comms sidebar: the agent-comms wire as a rich, interactive Toad panel.

IRC semantics for fully-detailed agent threads:

- **Click** a thread row -> composes a DM (``@name `` in the prompt).
- **Click** a channel row -> composes into that channel (``#name ``).
- **Right-click** -> context menu: fork, stop, acknowledge, copy name.
- Live rows: status, unread badges, task, activity (``working bash: …``).

View, not authority: reads the wire (``AGENT_COMMS_ROOT``) directly and
acts through ``agent_comms`` operations.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from agent_comms import ActivityState, ThreadStatus
from agent_comms.operations import wire


def _comms_root() -> Path:
    return Path(os.environ.get("AGENT_COMMS_ROOT", "~/.agent-comms")).expanduser()


def _fmt_age(ts: float, now: float) -> str:
    age = max(0.0, now - ts)
    if age < 10:
        return "now"
    if age < 60:
        return f"{int(age)}s"
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
        padding: 0 1;
    }
    CommsRow:hover { background: $surface-lighten-2; }
    CommsRow.-selected { background: $accent-darken-2; }
    CommsRow:focus { background: $accent-darken-2; text-style: bold; }
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


class CommsSidebar(VerticalScroll):
    """The wire: channels, threads, unread badges, live activity.

    Keyboard: up/down move the selection, enter opens the selected
    target in the main pane. Mouse: click selects+opens, right-click
    opens the context menu.
    """

    DEFAULT_CSS = """
    CommsSidebar {
        height: auto;
        max-height: 100%;
        padding: 0 0 1 0;
    }
    CommsSidebar .section { color: $text-muted; padding: 1 1 0 1; }
    CommsSidebar .row-name { color: $text; }
    CommsSidebar .row-detail { color: $text-muted; }
    CommsSidebar .activity { color: $success; }
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

    def __init__(self, session_thread: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.session_thread = session_thread
        self._row_map: dict[tuple[str, str], CommsRow] = {}
        self.can_focus = True
        self._cursor = 0

    def on_mount(self) -> None:
        self.set_interval(1.5, self._refresh)
        self._refresh()
        self._run_test_hook()

    def _run_test_hook(self) -> None:
        """Opt-in test seam: TOAD_COMMS_TEST_TARGET drives the same code
        path a row click takes (SelectTarget -> main pane switch). No-op
        unless the env var is set."""
        target = os.environ.get("TOAD_COMMS_TEST_TARGET", "")
        if not target:
            return
        if target.startswith("#"):
            self.post_message(SelectTarget(target, "channel"))
        elif self.session_thread and target == self.session_thread:
            self.post_message(SelectTarget(target, "session"))
        else:
            self.post_message(SelectTarget(target, "dm"))

    # ─── Data ─────────────────────────────────────────────────────────────────

    def _snapshot(self) -> dict:
        comms = wire(_comms_root())
        now = time.time()
        who = list(comms.who())
        channels = comms.channels()
        # Per-channel unread: messages to that channel newer than any read.
        history = list(comms.full_history())
        unread_by_channel: dict[str, int] = {}
        for channel in channels:
            unread_by_channel[channel] = 0
        markers = comms.bus._read_markers()
        oldest_read = min(markers.values()) if markers else 0
        for message in history:
            target = message.target
            if target in unread_by_channel and message.seq > oldest_read:
                unread_by_channel[target] += 1
        activity = comms.all_activity()
        return {
            "who": who,
            "channels": channels,
            "unread_by_channel": unread_by_channel,
            "activity": activity,
            "now": now,
        }

    def _refresh(self) -> None:
        try:
            snapshot = self._snapshot()
        except Exception:
            return
        self._rebuild(snapshot)

    # ─── Rendering ────────────────────────────────────────────────────────────

    def _rebuild(self, snapshot: dict) -> None:
        selection = self.selected
        self.remove_children()
        now = snapshot["now"]
        activity = snapshot["activity"]

        self.mount(Static("CHANNELS", classes="section"))
        for channel in snapshot["channels"]:
            unread = snapshot["unread_by_channel"].get(channel, 0)
            label = f"{channel} ({unread})" if unread else channel
            row = CommsRow("channel", channel, label, unread)
            if channel == selection:
                row.selected = True
                row.add_class("-selected")
            if unread:
                row.add_class("-unread")
            self.mount(row)

        self.mount(Static("WHO'S HERE", classes="section"))
        for person in snapshot["who"]:
            name = person["name"]
            is_session = name == self.session_thread
            if person["status"] == ThreadStatus.STOPPED.value:
                status_mark = "○"
            elif person["pending"]:
                status_mark = f"●{person['pending']}"
            else:
                status_mark = "●"
            task = f" — {person['task']}" if person["task"] else ""
            session_mark = " (session)" if is_session else ""
            row = CommsRow(
                "session" if is_session else "dm",
                name,
                f"{status_mark} {name}{session_mark}{task}"
                f" [{_fmt_age(person['last_seen'], now)}]",
                person["pending"],
            )
            if name == selection:
                row.selected = True
                row.add_class("-selected")
            if person["pending"]:
                row.add_class("-unread")
            self.mount(row)
            act = activity.get(name)
            if (
                act is not None
                and act.state is not ActivityState.IDLE
                and now - act.timestamp < 120
            ):
                detail = f" {act.detail}" if act.detail else ""
                self.mount(
                    Static(
                        f"    ⟳ {act.state.value}{detail} ({_fmt_age(act.timestamp, now)})",
                        classes="activity",
                    )
                )
        self.scroll_end(animate=False)

    # ─── Keyboard ─────────────────────────────────────────────────────────────

    def _ordered_rows(self) -> list[CommsRow]:
        return list(self.query(CommsRow))

    def action_cursor_up(self) -> None:
        rows = self._ordered_rows()
        if rows:
            self._cursor = max(0, self._cursor - 1)
            self._apply_cursor(rows)
            rows[self._cursor].focus()

    def action_cursor_down(self) -> None:
        rows = self._ordered_rows()
        if rows:
            self._cursor = min(len(rows) - 1, self._cursor + 1)
            self._apply_cursor(rows)
            rows[self._cursor].focus()

    def _apply_cursor(self, rows: list[CommsRow]) -> None:
        for index, row in enumerate(rows):
            row.selected = index == self._cursor
            row.set_class(index == self._cursor, "-selected")
        rows[self._cursor].scroll_visible(animate=False)

    def action_open_selected(self) -> None:
        rows = self._ordered_rows()
        focused = self.app.focused if self.app else None
        if isinstance(focused, CommsRow) and focused in rows:
            target = focused
            self._cursor = rows.index(target)
        elif 0 <= self._cursor < len(rows):
            target = rows[self._cursor]
        else:
            return
        self.selected = target.target_name
        self._apply_cursor(rows)
        target.post_message(SelectTarget(target.target_name, target.kind))

    # ─── Context menu ─────────────────────────────────────────────────────────

    def on_click(self, event) -> None:
        """Right click anywhere -> menu on the row under the mouse."""
        if event.button != 3:
            return
        widget = self.screen.get_widget_at(event.screen_x, event.screen_y)
        row = None
        while widget is not None:
            if isinstance(widget, CommsRow):
                row = widget
                break
            widget = widget.parent
        if row is None:
            return
        self._select(row)
        if row.kind == "thread":
            self._show_thread_menu(row.target_name)
        else:
            self._show_channel_menu(row.target_name)

    def _select(self, row: CommsRow) -> None:
        self.selected = row.target_name
        for other in self.query(CommsRow):
            other.remove_class("-selected")
        row.add_class("-selected")

    def _show_thread_menu(self, name: str) -> None:
        from toad.widgets.comms_menu import show_thread_menu

        show_thread_menu(
            self.app.screen,
            name,
            {
                "fork": lambda: self.post_message(self.ThreadAction(row.name, "fork")),
                "stop": lambda: self.post_message(self.ThreadAction(row.name, "stop")),
                "ack": lambda: self.post_message(self.ThreadAction(row.name, "ack")),
                "copy": lambda: self.post_message(self.ThreadAction(row.name, "copy")),
            },
        )

    def _show_channel_menu(self, name: str) -> None:
        from toad.widgets.comms_menu import show_channel_menu

        show_channel_menu(
            self.app.screen,
            name,
            {
                "ack": lambda: self.post_message(self.ThreadAction(row.name, "ack")),
                "copy": lambda: self.post_message(self.ThreadAction(row.name, "copy")),
            },
        )

    # ─── Actions ──────────────────────────────────────────────────────────────

    @on(ThreadAction)
    def _do_thread_action(self, event: ThreadAction) -> None:
        name = event.name
        comms = wire(_comms_root())
        try:
            if event.action == "stop":
                comms.stop(name)
            elif event.action == "ack":
                comms.acknowledge(name)
            elif event.action == "copy":
                self.app.copy_to_clipboard(name)
        except Exception:
            pass
        self._refresh()
