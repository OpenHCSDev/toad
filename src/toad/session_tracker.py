from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from time import time
from operator import attrgetter
from typing import Iterable, Literal, Sequence

from textual.signal import Signal
from textual.widget import Widget
from agent_comms.presentation import CoordinationSnapshot



class UnreadPresentation(ABC):
    """Only completed counts can be displayed as numbers."""

    @classmethod
    def for_thread(cls, snapshot: CoordinationSnapshot, name: str) -> "UnreadPresentation":
        if name in snapshot.thread_unread_pending:
            return IndexingUnread()
        return ExactUnread(snapshot.thread_unread.get(name, 0))

    @property
    @abstractmethod
    def label(self) -> str:
        """The badge shown by row and tab presentation owners."""

    @property
    def highlighted(self) -> bool:
        return bool(self.label)

    @property
    def detail(self) -> str:
        return ""


@dataclass(frozen=True)
class ExactUnread(UnreadPresentation):
    count: int = 0

    @property
    def label(self) -> str:
        return f"({self.count})" if self.count else ""


@dataclass(frozen=True)
class IndexingUnread(UnreadPresentation):
    @property
    def label(self) -> str:
        return "Indexing…"

    @property
    def detail(self) -> str:
        return "Unread replies are still being indexed; the exact count is not yet known."


@dataclass(frozen=True)
class OpenTab:
    mode_name: str
    title: str
    unread: UnreadPresentation = ExactUnread()


@dataclass(frozen=True)
class CommsViewKey:
    """A wire destination belongs to one owner session and sending identity."""

    root: str
    owner_mode: str
    me: str
    kind: str
    target: str

    @property
    def title(self) -> str:
        return f"@{self.target}" if self.kind == "dm" else self.target


@dataclass(frozen=True)
class ChannelViewAddress:
    root: str
    target: str
    kind: type


@dataclass(frozen=True)
class SidebarSelection:
    channel: str
    target: str


@dataclass
class SidebarState:
    expanded: dict[str, bool] = field(default_factory=dict)
    panels_collapsed: dict[str, bool] = field(default_factory=dict)
    selected: SidebarSelection | None = None
    channel_scroll_y: float = 0
    panel_scroll_y: float = 0

    def restore_scroll(self, channel: Widget, panels: Widget) -> bool:
        before = channel.scroll_y, panels.scroll_y
        channel.scroll_to(y=self.channel_scroll_y, animate=False, immediate=True)
        panels.scroll_to(y=self.panel_scroll_y, animate=False, immediate=True)
        return before != (channel.scroll_y, panels.scroll_y)


@dataclass
class SessionDetails:
    """Tracks a concurrent session."""

    index: int
    """Index of session, used in sorting."""
    mode_name: str
    """The screen mode name."""
    title: str = ""
    """The title of the conversation."""
    subtitle: str = ""
    """The subtitle of the conversation."""
    path: str = ""
    """The project directory path."""

    updates: int = 0
    """Track updates to the session details."""
    created_at: float = field(default_factory=time)
    """Creation time for local sessions without a wire identity."""



class SessionTracker:
    """Tracks concurrent agent settings"""

    def __init__(self, signal: Signal[tuple[str, SessionDetails | None]]) -> None:
        self.sessions: dict[str, SessionDetails] = {}
        self._session_index = 0
        self.signal = signal

    @property
    def session_count(self) -> int:
        return len(self.sessions)

    def new_session(self, *, title: str = "New Session") -> SessionDetails:
        self._session_index += 1
        mode_name = f"session-{self._session_index}"
        session_meta = SessionDetails(
            index=self._session_index, mode_name=mode_name, title=title
        )
        self.sessions[mode_name] = session_meta
        return session_meta

    def close_session(self, mode_name: str) -> None:
        if mode_name in self.sessions:
            del self.sessions[mode_name]
            self.signal.publish((mode_name, None))

    def get_session(self, mode_name: str) -> SessionDetails | None:
        return self.sessions.get(mode_name, None)

    def update_session(
        self,
        mode_name: str,
        title: str | None = None,
        subtitle: str | None = None,
        path: str | None = None,
    ) -> SessionDetails:
        session_details = self.sessions[mode_name]
        before = (
            session_details.title, session_details.subtitle, session_details.path,
        )
        if title is not None:
            session_details.title = title
        if subtitle is not None:
            session_details.subtitle = subtitle
        if path is not None:
            session_details.path = path
        after = (
            session_details.title, session_details.subtitle, session_details.path,
        )
        if after != before:
            self.signal.publish((mode_name, session_details))
        return session_details

    @property
    def ordered_sessions(self) -> Sequence[SessionDetails]:
        return sorted(self.sessions.values(), key=attrgetter("index"))

    def __iter__(self) -> Iterable[SessionDetails]:
        return iter(self.ordered_sessions)

    def session_cursor_move(
        self, mode_name: str, direction: Literal[-1, +1]
    ) -> str | None:
        mode_names = [session.mode_name for session in self.ordered_sessions]
        try:
            mode_index = mode_names.index(mode_name)
        except ValueError:
            return None
        mode_index = (mode_index + direction) % len(mode_names)
        new_mode_name = mode_names[mode_index]
        return new_mode_name
