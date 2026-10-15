from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from time import time
from operator import attrgetter
from typing import Iterable, Literal, Sequence

from toad.core.events import CoreEventStream, SessionChangedEvent, SessionClosedEvent
from agent_comms.ui_model.unread import ExactUnread, UnreadPresentation
from agent_comms.ui_model.sidebar import ThreadRowModel
from toad.widgets.activity_spinner import animated_label
from textual.content import Content
from toad.conversation_kind import ConversationKind



@dataclass(frozen=True)
class OpenTab(ABC):
    """A tab reads its label and activity from the source it represents."""

    mode_name: str
    busy = False

    @property
    @abstractmethod
    def title(self) -> str: ...

    @property
    @abstractmethod
    def unread(self) -> UnreadPresentation: ...

    def label(self, phase: int) -> Content:
        return Content(self.title)


@dataclass(frozen=True)
class NamedTab(OpenTab):
    name: str
    unread: UnreadPresentation = ExactUnread()

    @property
    def title(self) -> str:
        return self.name


@dataclass(frozen=True)
class ThreadTab(OpenTab):
    row: ThreadRowModel

    @property
    def title(self) -> str:
        return self.row.label

    @property
    def unread(self) -> UnreadPresentation:
        return self.row.unread

    @property
    def busy(self) -> bool:
        return self.row.busy

    def label(self, phase: int) -> Content:
        return animated_label(self.row, phase=phase)


@dataclass(frozen=True)
class CommsViewKey:
    """A wire destination belongs to one owner session and sending identity."""

    root: str
    owner_mode: str
    me: str
    kind: type[ConversationKind]
    target: str

    @property
    def title(self) -> str:
        return self.kind.label(self.target)


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
    selected_targets: tuple[SidebarSelection, ...] = ()
    panel_scroll_y: float = 0


@dataclass(frozen=True)
class SessionName:
    """A session tab's name: the user's choice, or the thread's title."""

    authored: str | None
    thread_title: str = ""

    @property
    def display(self) -> str:
        """What the tab shows: the user's name when they chose one."""
        return self.authored or self.thread_title

    @property
    def is_placeholder(self) -> bool:
        """No name yet: not authored, and still showing the workspace placeholder."""
        return self.authored is None and self.thread_title == "New Session"

    @classmethod
    def authored_name(cls, name: str) -> "SessionName":
        return cls(name)

    @classmethod
    def following(cls, thread_title: str) -> "SessionName":
        return cls(None, thread_title)

    def present_thread_title(self, thread_title: str) -> "SessionName | None":
        """The name after the thread presents a title, or None if it cannot win."""
        if self.authored is not None:
            return None
        return type(self)(None, thread_title)

    def adopt_identity(self, previous: str, current: str) -> "SessionName | None":
        """The thread behind this session is now named `current`.

        A tab that shows no name of its own yet, or still shows the old
        thread's name, follows; the user's name and a tab already following
        another thread stay.
        """
        if self.authored is not None:
            return None
        if self.thread_title != previous and not self.is_placeholder:
            return None
        return type(self)(None, current)


@dataclass
class SessionDetails:
    """Tracks a concurrent session."""

    index: int
    """Index of session, used in sorting."""
    mode_name: str
    """The screen mode name."""
    name: SessionName = field(default_factory=lambda: SessionName.following("New Session"))
    """The name of the conversation: the user's choice or the thread's title."""
    subtitle: str = ""
    """The subtitle of the conversation."""
    path: str = ""
    """The project directory path."""

    updates: int = 0
    """Track updates to the session details."""
    created_at: float = field(default_factory=time)
    """Creation time for local sessions without a wire identity."""

    @property
    def initial_title(self) -> str | None:
        """The workspace placeholder is not an authored session name."""
        return None if self.name.is_placeholder else self.name.display

    def bind_initial_identity(self, session_id: str | None) -> None:
        """An existing native identity names an otherwise unnamed admission."""
        if session_id is not None and self.name.is_placeholder:
            self.update_thread_title(session_id)

    def name_session(self, name: str) -> None:
        """The user named this session; no presented title replaces it."""
        self.name = SessionName.authored_name(name)

    def update_thread_title(self, thread_title: str) -> bool:
        """Adopt the thread's title where the user has not named the session."""
        replacement = self.name.present_thread_title(thread_title)
        if replacement is None or replacement.thread_title == self.name.thread_title:
            return False
        self.name = replacement
        return True



class SessionTracker:
    """Tracks concurrent agent settings"""

    def __init__(self) -> None:
        self.sessions: dict[str, SessionDetails] = {}
        self._session_index = 0
        self.events = CoreEventStream(self)

    @property
    def session_count(self) -> int:
        return len(self.sessions)

    def new_session(self, *, title: str = "New Session") -> SessionDetails:
        self._session_index += 1
        mode_name = f"session-{self._session_index}"
        session_meta = SessionDetails(
            index=self._session_index, mode_name=mode_name,
            name=SessionName.following(title),
        )
        self.sessions[mode_name] = session_meta
        self.events.publish(SessionChangedEvent(mode_name))
        return session_meta

    def close_session(self, mode_name: str) -> None:
        if mode_name in self.sessions:
            del self.sessions[mode_name]
            self.events.publish(SessionClosedEvent(mode_name))

    def bind_identity(self, mode_name: str, previous: str, current: str) -> None:
        """The thread's name arrives: the user's name keeps the tab's label."""
        details = self.sessions[mode_name]
        if (adopted := details.name.adopt_identity(previous, current)) is not None:
            details.name = adopted
            self.events.publish(SessionChangedEvent(mode_name))

    def get_session(self, mode_name: str) -> SessionDetails | None:
        return self.sessions.get(mode_name, None)

    def name_session(self, mode_name: str, name: str) -> SessionDetails:
        """The user named this session; its tab keeps the name."""
        session_details = self.sessions[mode_name]
        before = session_details.name.display
        session_details.name_session(name)
        if session_details.name.display != before:
            self.events.publish(SessionChangedEvent(mode_name))
        return session_details

    def update_session(
        self,
        mode_name: str,
        subtitle: str | None = None,
        path: str | None = None,
    ) -> SessionDetails:
        session_details = self.sessions[mode_name]
        before = (
            session_details.name.display, session_details.subtitle, session_details.path,
        )
        if subtitle is not None:
            session_details.subtitle = subtitle
        if path is not None:
            session_details.path = path
        after = (
            session_details.name.display, session_details.subtitle, session_details.path,
        )
        if after != before:
            self.events.publish(SessionChangedEvent(mode_name))
        return session_details

    @property
    def ordered_sessions(self) -> Sequence[SessionDetails]:
        return sorted(self.sessions.values(), key=attrgetter("index"))

    def __iter__(self) -> Iterable[SessionDetails]:
        return iter(self.ordered_sessions)

