"""A session's absent, local or wire-bound thread, with its owned behavior."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from agent_comms.errors import UnregisteredThreadError
from agent_comms.thread_identity import ThreadIncarnation, UnrecordedThreadIncarnation

from toad.format_path import format_path
from toad.transcript_scope import KnownTranscript, NoTranscript, TranscriptScope
from toad.transcript_state import UnboundTranscript, UnreadTranscript
from toad.comms_root import Observing
from toad.session_tracker import SessionDetails
from agent_comms.nominal.field_codec import AcpSessionId



class SessionIdentity(ABC):
    @classmethod
    def for_thread(cls, thread: str, root: str | None):
        """Decode the optional wire binding once when accepting a source."""
        if not thread:
            return NoThreadIdentity()
        if root is None:
            return LocalThreadIdentity(thread)
        return ThreadIdentity(UnrecordedThreadIncarnation(thread), root)

    @abstractmethod
    def thread_name(self) -> str: ...

    def with_thread(self, thread: str):
        return self.for_thread(thread, self.wire_root())

    def with_root(self, root: str | None):
        return self.for_thread(self.thread_name(), root)

    def with_session(self, session_id: AcpSessionId):
        """A newly attached ACP session supplies an unbound view's name."""
        return LocalThreadIdentity(session_id)

    def wire_root(self) -> str | None:
        return None

    def belongs_to_wire(self, root: Path) -> bool:
        """A session without a managed wire may project whichever wire is selected."""
        return True

    def transcript_scope(self) -> TranscriptScope:
        return NoTranscript()

    def transcript_state(self):
        return UnboundTranscript()

    @abstractmethod
    def display_thread(self) -> str: ...

    def display_root(self) -> str:
        return "No managed wire"

    def inspection_state(self):
        from toad.core.context_inspection import DetachedInspection

        return DetachedInspection()

    @property
    def root_path(self) -> Path | None:
        return None

    def detached_status(self) -> str:
        return f"{self.display_thread()} · {self.display_root()}"

    async def inspect_owner(self, read_owner, show_detached) -> None:
        show_detached(self.detached_status())

    def thread_incarnation(self) -> ThreadIncarnation:
        raise ValueError("Session has no managed thread incarnation")

    def bind_history(self, histories) -> None:
        """An unbound session keeps its native input-history scope."""

    def bind_initial_identity(self, details: SessionDetails) -> None:
        """A session without a thread has no initial thread title."""

    def resolve_thread(self, observed: Observing, project: Path) -> str:
        """An unbound view asks Core to discover its project's session."""
        return observed.session_thread(project, self.thread_name()).name_or(self.thread_name())

    def command_target[T](self, target: Callable[[str], T]) -> T:
        """A named session addresses backend commands as its thread."""
        return target(self.thread_name())


@dataclass(frozen=True)
class NoThreadIdentity(SessionIdentity):
    def thread_name(self) -> str:
        return ""

    def display_thread(self) -> str:
        return "No thread"

    def command_target[T](self, target: Callable[[str], T]) -> T:
        """An unbound session has no backend thread; local commands remain."""
        raise UnregisteredThreadError("An unbound session has no backend thread")


@dataclass(frozen=True)
class NamedThreadIdentity(SessionIdentity, ABC):
    def bind_initial_identity(self, details: SessionDetails) -> None:
        details.bind_initial_identity(self.thread_name())

    def display_thread(self) -> str:
        return f"@{self.thread_name()}"


@dataclass(frozen=True)
class LocalThreadIdentity(NamedThreadIdentity):
    """A named session without a managed wire."""

    thread: str

    def thread_name(self) -> str:
        return self.thread


@dataclass(frozen=True)
class ThreadIdentity(NamedThreadIdentity):
    owner: ThreadIncarnation
    root: str

    def thread_name(self) -> str:
        return self.owner.name

    def thread_incarnation(self) -> ThreadIncarnation:
        return self.owner

    def resolve_thread(self, observed: Observing, project: Path) -> str:
        """A bound view requires its original name; it never discovers a replacement."""
        return observed.registry_for(self.owner.name).require(self.owner.name).name

    def with_thread(self, thread: str):
        return ThreadIdentity(self.owner.renamed(thread), self.root)

    def with_root(self, root: str | None):
        return self if root == self.root else super().with_root(root)

    def with_session(self, session_id: AcpSessionId):
        """A managed thread keeps its declared name and incarnation."""
        return self

    async def inspect_owner(self, read_owner, show_detached) -> None:
        await read_owner(self)

    def bind_history(self, histories) -> None:
        histories.bind_scope(f"thread:{self.thread_name()}")

    def wire_root(self) -> str:
        return self.root

    def belongs_to_wire(self, root: Path) -> bool:
        return self.root_path == root

    def transcript_scope(self) -> KnownTranscript:
        return KnownTranscript(self.root, self.owner)

    def transcript_state(self):
        return UnreadTranscript()

    def display_root(self) -> str:
        return format_path(self.root_path)

    def inspection_state(self):
        from toad.core.context_inspection import ReadingOwnerInspection

        return ReadingOwnerInspection()

    @cached_property
    def root_path(self) -> Path:
        """The bound wire's root as the observer names it, resolved once per identity: the
        sidebar asks for it on every row of every paint."""
        return Path(self.root).expanduser().resolve()
