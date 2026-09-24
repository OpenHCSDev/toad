"""Compact, live session list for the persistent left sidebar."""

from __future__ import annotations

from agent_comms import ThreadView
from textual.containers import VerticalScroll
from textual.binding import Binding
from textual.content import Content
from textual.reactive import reactive
from textual.widgets import Static

from toad.session_tracker import SessionDetails
from toad.widgets.selection import HoverSelection


class ThreadStatusRow(HoverSelection):
    """Compact wire status presentation shared by open and unopened threads."""

    DEFAULT_CSS = """
    ThreadStatusRow.-wire-thread {
        height: 2;
        padding: 0;
        text-wrap: nowrap;
        text-overflow: ellipsis;
        color: $text-muted;
        pointer: pointer;
    }
    ThreadStatusRow.-wire-thread.-busy { color: $warning; }
    ThreadStatusRow.-wire-thread.-unread { text-style: bold; }
    ThreadStatusRow:hover {
        background: transparent;
        color: #ad8bf5 !important;
        text-style: underline;
    }
    ThreadStatusRow:ansi:hover {
        background: transparent;
        color: ansi_magenta !important;
        text-style: underline;
    }
    ThreadStatusRow:focus {
        background: transparent;
        color: #ad8bf5 !important;
        text-style: underline;
    }
    ThreadStatusRow:ansi:focus {
        background: transparent;
        color: ansi_magenta !important;
        text-style: underline;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._thread_signature: tuple | None = None
        self.thread_name: str | None = None

    def update_thread(
        self, person: ThreadView, *, unread: int = 0, pinned: bool = False,
        action_status: str | None = None,
    ) -> None:
        self.thread_name = person.thread.name
        presentation = person.presentation
        summary, busy = presentation.summary, presentation.busy
        if action_status is not None:
            summary, busy = action_status, True
        # Put the count before the title so long thread names cannot clip it.
        badge = f"({unread}) " if unread else ""
        content = Content.assemble(
            (badge, "bold $accent"),
            f"{'* ' if pinned else ''}{presentation.label}\n  {summary}",
        )
        tooltip = "\n".join(
            str(value)
            for value in (
                person.thread.name,
                summary,
                "Pinned in this channel" if pinned else None,
                person.runtime.model if person.runtime else person.thread.model,
            )
            if value
        )
        signature = (content.plain, tooltip, busy)
        if signature == self._thread_signature:
            return
        self._thread_signature = signature
        self.add_class("-wire-thread")
        self.set_class(busy, "-busy")
        self.set_class(bool(unread), "-unread")
        self.remove_class("-asking")
        self.tooltip = Content(tooltip)
        self.update(content, layout=False)


class SessionRow(ThreadStatusRow):
    """An open Toad view, using the same wire status as unopened threads."""

    can_focus = True
    BINDINGS = [
        Binding("up", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("enter", "open", show=False),
    ]
    mode_name: str
    current = reactive(False, toggle_class="-current")

    DEFAULT_CSS = """
    SessionRow {
        height: 2;
        padding: 0;
        color: $text-muted;
        pointer: pointer;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    SessionRow.-current { color: $text; text-style: bold; }
    SessionRow.-busy { color: $warning; }
    SessionRow.-asking { color: $accent; }
    """

    def __init__(
        self, details: SessionDetails, *, widget_id: str | None = None
    ) -> None:
        super().__init__(id=widget_id)
        self.mode_name = details.mode_name
        self._details_signature: tuple[str, str, str] | None = None
        self.update_details(details)

    def update_details(self, details: SessionDetails) -> None:
        if self.has_class("-wire-thread"):
            self.remove_class("-wire-thread")
            self._thread_signature = None
            self._details_signature = None
        presentation = details.presentation
        activity = presentation.summary
        signature = (details.state, details.title, activity)
        if signature == self._details_signature:
            return
        self._details_signature = signature
        self.remove_class(
            "-state-notready", "-state-busy", "-state-asking", "-state-idle"
        )
        self.add_class(f"-state-{details.state}")
        self.set_class(presentation.busy, "-busy")
        self.set_class(presentation.asking, "-asking")
        self.update(f"{presentation.label}\n  {activity}", layout=False)

    def _sidebar(self):
        parent = self.parent
        while parent is not None and not hasattr(parent, "action_cursor_down"):
            parent = parent.parent
        return parent

    def action_cursor_up(self) -> None:
        if (sidebar := self._sidebar()) is not None:
            sidebar.action_cursor_up()

    def action_cursor_down(self) -> None:
        if (sidebar := self._sidebar()) is not None:
            sidebar.action_cursor_down()

    def action_open(self) -> None:
        if (sidebar := self._sidebar()) is not None:
            sidebar.remember_row(self)
        self.app.switch_mode(self.mode_name)

    def on_focus(self) -> None:
        if (sidebar := self._sidebar()) is not None:
            rows = sidebar._ordered_rows()
            if self in rows:
                sidebar.focus_row(self)

    def on_click(self, event) -> None:
        if event.button != 3:
            self.action_open()


class SessionSidebar(VerticalScroll):
    """Tracker-backed local sessions shown with remote agent sessions."""

    DEFAULT_CSS = """
    SessionSidebar {
        height: auto;
        max-height: 12;
    }
    """

    def compose(self):
        for details in self.app.session_tracker.ordered_sessions:
            yield SessionRow(details, widget_id=details.mode_name)

    def on_mount(self) -> None:
        self.app.session_update_signal.subscribe(self, self._session_updated)
        self.app.mode_change_signal.subscribe(self, self._mode_changed)
        self._mode_changed(self.app.current_mode)

    async def _session_updated(self, update: tuple[str, SessionDetails | None]) -> None:
        mode_name, details = update
        row = self.query_one_optional(f"#{mode_name}", SessionRow)
        if details is None:
            if row is not None:
                await row.remove()
            return
        if row is None:
            row = SessionRow(details, widget_id=details.mode_name)
            await self.mount(row)
        else:
            row.update_details(details)
        self._mode_changed(self.app.current_mode)

    def _mode_changed(self, mode_name: str) -> None:
        for row in self.query(SessionRow):
            row.current = row.mode_name == mode_name
