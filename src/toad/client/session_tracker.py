from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from time import time
from typing import Iterable, Sequence

from agent_comms.ui_model.sidebar import SidebarModel, ThreadRowModel
from agent_comms.ui_model.unread import ExactUnread, UnreadPresentation

from toad.client.conversation import ConversationKind
from toad.core.events import CoreEventStream, SessionChangedEvent, SessionClosedEvent
from toad.client.tab_identity import SessionTabIdentity, TabIdentity
from toad.client.tab_order import TabOrder


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

    def label(self) -> str:
        return self.title

    def unread_suffix(self, badge) -> str:
        """What follows the label in the tab: the unread badge the user's
        `sidebar.unread_counts` setting draws (``badge``), or nothing. Both tab bars append it."""
        shown = badge(self.unread)
        return f" {shown}" if shown else ""

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


@dataclass(frozen=True)
class ThreadTab(OpenTab):
    row: ThreadRowModel

    def affected_by(self, names: frozenset[str]) -> bool:
        return self.row.name in names

    @property
    def title(self) -> str:
        return self.row.title

    def label(self) -> str:
        return self.row.label

    @property
    def unread(self) -> UnreadPresentation:
        return self.row.unread

    @property
    def busy(self) -> bool:
        return self.row.status.is_working()


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
    panel_identity: object = None

    def is_panel_collapsed(self, title: str, default: bool = False) -> bool:
        """Current collapsed state for a panel keyed by title; `default` is the
        panel spec's initial collapsed value, used when the user has not touched
        this panel yet."""
        return self.panels_collapsed.get(title, default)

    def set_panel_collapsed(self, title: str, value: bool) -> None:
        """Record a user's collapse choice. Both frontends write through this
        single accessor so the panel's state is the one authority — a direct
        `panels_collapsed[title] = v` write would be a parallel path."""
        self.panels_collapsed[title] = value

    def toggle_panel_collapsed(self, title: str, default: bool = False) -> bool:
        """Flip and return the new collapsed state."""
        new_value = not self.is_panel_collapsed(title, default)
        self.set_panel_collapsed(title, new_value)
        return new_value

    def welcome_section_open(self, title: str) -> bool:
        """Whether the welcome's section under ``title`` is open: open until the reader closes
        it, and as the reader left it whenever the listing is drawn again."""
        return self.expanded.get(f"welcome:{title}", True)

    def set_welcome_section_open(self, title: str, value: bool) -> None:
        self.expanded[f"welcome:{title}"] = value

    def preserve_selected_target(self) -> None:
        """Keep the newly selected row in selected_targets when a prior selection existed."""
        if self.selected is not None:
            self.selected_targets = (self.selected,)


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
        self.name = SessionName(name)

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
        self.events.publish(SessionChangedEvent(identity))
        return details

    def close_session(self, identity: TabIdentity) -> None:
        if identity in self.sessions:
            del self.sessions[identity]
            self.events.publish(SessionClosedEvent(identity))

    def bind_identity(self, identity: TabIdentity, previous: str, current: str) -> None:
        """The thread's name arrives: the user's name keeps the tab's label."""
        details = self.sessions[identity]
        adopted = details.name.adopt_identity(previous, current)
        if adopted != details.name:
            details.name = adopted
            self.events.publish(SessionChangedEvent(identity))

    def get_session(self, identity: TabIdentity) -> SessionDetails | None:
        return self.sessions.get(identity)

    def name_session(self, identity: TabIdentity, name: str) -> SessionDetails:
        """The user named this session; its tab keeps the name."""
        session_details = self.sessions[identity]
        before = session_details.name.display
        session_details.name_session(name)
        if session_details.name.display != before:
            self.events.publish(SessionChangedEvent(identity))
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
            self.events.publish(SessionChangedEvent(identity))
        return session_details

    @property
    def ordered_sessions(self) -> Sequence[SessionDetails]:
        return self.order.project(self.sessions)

    def __iter__(self) -> Iterable[SessionDetails]:
        return iter(self.ordered_sessions)
