from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from time import time
from typing import TYPE_CHECKING, Iterable, Sequence

from agent_comms.ui_model.sidebar import SidebarModel, SidebarObservation, ThreadRowModel
from agent_comms.ui_model.unread import ExactUnread, UnreadPresentation
from textual.content import Content

from toad.core.events import CoreEventStream, SessionChangedEvent, SessionClosedEvent
from toad.tab_identity import SessionTabIdentity, TabIdentity
from toad.tab_order import TabOrder

if TYPE_CHECKING:
    from toad.conversation_kind import ConversationKind


@dataclass(frozen=True)
class OpenTab(ABC):
    """A tab reads its label and activity from the source it represents."""

    identity: TabIdentity
    busy = False

    @property
    def mode_name(self) -> str:
        return self.identity.mode_name

    @property
    @abstractmethod
    def title(self) -> str: ...

    @property
    def unread(self) -> UnreadPresentation:
        return ExactUnread()

    def repainted_by(self, observation: SidebarObservation) -> bool:
        return False

    def label(self) -> Content:
        return Content(self.title)

    def affected_by(self, names: frozenset[str]) -> bool:
        """Local names do not change when backend thread state changes."""
        return False


@dataclass(frozen=True)
class NamedTab(OpenTab):
    name: str

    @property
    def title(self) -> str:
        return self.name


@dataclass(frozen=True)
class ConversationTab(NamedTab):
    conversation: ConversationKind
    sidebar: SidebarModel

    @property
    def unread(self) -> UnreadPresentation:
        return self.conversation.unread(self.sidebar.observation)

    def repainted_by(self, observation: SidebarObservation) -> bool:
        return True


@dataclass(frozen=True)
class ThreadTab(OpenTab):
    row: ThreadRowModel

    def affected_by(self, names: frozenset[str]) -> bool:
        return self.row.name in names

    @property
    def title(self) -> str:
        return self.row.title

    def label(self) -> Content:
        return Content(self.row.label)

    @property
    def unread(self) -> UnreadPresentation:
        return self.row.unread

    @property
    def busy(self) -> bool:
        return self.row.status.working


@dataclass(frozen=True)
class CommsViewKey:
    """A wire destination belongs to one owner session."""

    root: str
    owner_mode: str
    conversation: ConversationKind


@dataclass(frozen=True)
class ChannelViewAddress:
    root: str
    conversation: ConversationKind


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
    """A session label owns whether presented thread names can replace it."""

    display: str

    @property
    def is_placeholder(self) -> bool:
        return False

    def present_thread_title(self, thread_title: str) -> SessionName:
        return self

    def adopt_identity(self, previous: str, current: str) -> SessionName:
        return self


class AuthoredSessionName(SessionName):
    """The user's label stays when the thread presents a title or changes name."""


class ThreadSessionName(SessionName):
    """An unlabelled session follows its thread's presented title and identity."""

    @property
    def is_placeholder(self) -> bool:
        return self.display == "New Session"

    def present_thread_title(self, thread_title: str) -> SessionName:
        return type(self)(thread_title)

    def adopt_identity(self, previous: str, current: str) -> SessionName:
        if self.display == previous or self.is_placeholder:
            return type(self)(current)
        return self


@dataclass
class SessionDetails:
    """Tracks a concurrent session."""

    identity: SessionTabIdentity
    """The durable thing this tab opens."""
    name: SessionName = field(
        default_factory=lambda: ThreadSessionName("New Session")
    )
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
    def mode_name(self) -> str:
        return self.identity.mode_name

    @property
    def initial_title(self) -> str | None:
        """The workspace placeholder is not an authored session name."""
        return None if self.name.is_placeholder else self.name.display

    def bind_initial_identity(self, thread_name: str) -> None:
        """The bound thread names an otherwise unnamed session."""
        if self.name.is_placeholder:
            self.update_thread_title(thread_name)

    def name_session(self, name: str) -> None:
        """The user named this session; no presented title replaces it."""
        self.name = AuthoredSessionName(name)

    def update_thread_title(self, thread_title: str) -> bool:
        """Adopt the thread's title where the user has not named the session."""
        replacement = self.name.present_thread_title(thread_title)
        if replacement == self.name:
            return False
        self.name = replacement
        return True


class SessionTracker:
    """Tracks concurrent agent settings"""

    def __init__(self, order: TabOrder) -> None:
        self.sessions: dict[TabIdentity, SessionDetails] = {}
        self.order = order
        self.events = CoreEventStream(self)

    @property
    def session_count(self) -> int:
        return len(self.sessions)

    def new_session(self, identity: SessionTabIdentity, *, title: str = "New Session") -> SessionDetails:
        details = SessionDetails(identity=identity, name=ThreadSessionName(title))
        self.sessions[identity] = details
        self.events.publish(SessionChangedEvent(identity.mode_name))
        return details

    def close_session(self, identity: TabIdentity) -> None:
        if identity in self.sessions:
            del self.sessions[identity]
            self.events.publish(SessionClosedEvent(identity.mode_name))

    def bind_identity(self, identity: TabIdentity, previous: str, current: str) -> None:
        """The thread's name arrives: the user's name keeps the tab's label."""
        details = self.sessions[identity]
        adopted = details.name.adopt_identity(previous, current)
        if adopted != details.name:
            details.name = adopted
            self.events.publish(SessionChangedEvent(identity.mode_name))

    def get_session(self, identity: TabIdentity) -> SessionDetails | None:
        return self.sessions.get(identity)

    def name_session(self, identity: TabIdentity, name: str) -> SessionDetails:
        """The user named this session; its tab keeps the name."""
        session_details = self.sessions[identity]
        before = session_details.name.display
        session_details.name_session(name)
        if session_details.name.display != before:
            self.events.publish(SessionChangedEvent(identity.mode_name))
        return session_details

    def update_session(
        self,
        identity: TabIdentity,
        subtitle: str | None = None,
        path: str | None = None,
    ) -> SessionDetails:
        session_details = self.sessions[identity]
        before = (
            session_details.name.display,
            session_details.subtitle,
            session_details.path,
        )
        if subtitle is not None:
            session_details.subtitle = subtitle
        if path is not None:
            session_details.path = path
        after = (
            session_details.name.display,
            session_details.subtitle,
            session_details.path,
        )
        if after != before:
            self.events.publish(SessionChangedEvent(identity.mode_name))
        return session_details

    @property
    def ordered_sessions(self) -> Sequence[SessionDetails]:
        return self.order.project(self.sessions)

    def __iter__(self) -> Iterable[SessionDetails]:
        return iter(self.ordered_sessions)
