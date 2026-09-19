"""Compact, live session list for the persistent left sidebar."""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.content import Content
from textual.reactive import reactive
from textual.widgets import Static

from toad import messages
from toad.session_tracker import SessionDetails


class SessionRow(Static):
    """One durable Toad session with its current lifecycle activity."""

    can_focus = True
    mode_name: str
    current = reactive(False, toggle_class="-current")

    DEFAULT_CSS = """
    SessionRow {
        height: 2;
        padding: 0 1;
        color: $text-muted;
    }
    SessionRow:hover, SessionRow:focus, SessionRow.-current {
        background: $surface-lighten-2;
    }
    SessionRow.-current { color: $text; text-style: bold; }
    SessionRow.-busy { color: $warning; }
    SessionRow.-asking { color: $accent; }
    """

    def __init__(self, details: SessionDetails) -> None:
        super().__init__(id=details.mode_name)
        self.mode_name = details.mode_name
        self.update_details(details)

    def update_details(self, details: SessionDetails) -> None:
        self.remove_class(
            "-state-notready", "-state-busy", "-state-asking", "-state-idle"
        )
        self.add_class(f"-state-{details.state}")
        self.set_class(details.state == "busy", "-busy")
        self.set_class(details.state == "asking", "-asking")
        marker = {
            "notready": "○",
            "busy": "●",
            "asking": "?",
            "idle": "✓",
        }[details.state]
        activity = details.summary or details.subtitle or details.path or "Ready"
        self.update(
            Content.assemble(
                (f"{marker} ", "$text-secondary"),
                (details.title or "New Session", "$text"),
                "\n  ",
                activity.replace("\n", " ")[:44],
            )
        )

    def on_click(self) -> None:
        self.post_message(messages.SessionSwitch(self.mode_name))


class SessionSidebar(VerticalScroll):
    """Tracker-backed session list, independent of agent-comms presence."""

    DEFAULT_CSS = """
    SessionSidebar {
        height: auto;
        max-height: 12;
    }
    """

    def compose(self):
        for details in self.app.session_tracker.ordered_sessions:
            yield SessionRow(details)

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
            row = SessionRow(details)
            await self.mount(row)
        else:
            row.update_details(details)
        self._mode_changed(self.app.current_mode)

    def _mode_changed(self, mode_name: str) -> None:
        for row in self.query(SessionRow):
            row.current = row.mode_name == mode_name
