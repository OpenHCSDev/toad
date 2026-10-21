"""A session's absent, local or wire-bound thread, with its owned behavior."""
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from toad.format_path import format_path
from toad.transcript_state import UnboundTranscript, UnreadTranscript
from agent_comms.errors import UnregisteredThreadError
from agent_comms.thread_identity import ThreadIncarnation, UnrecordedThreadIncarnation


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

    def with_session(self, session_id: str):
        """A newly attached ACP session supplies an unbound view's name."""
        return LocalThreadIdentity(session_id)

    def wire_root(self) -> str | None:
        return None

    def transcript_scope(self) -> tuple[str, str] | None:
        return None

    def transcript_state(self):
        return UnboundTranscript()

    @abstractmethod
    def display_thread(self) -> str: ...

    def display_root(self) -> str:
        return "No managed wire"

    def inspection_state(self):
        from toad.core.context_inspection import DetachedInspection
        return DetachedInspection()

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

    def resolve_thread(self, registry, project: Path) -> str:
        """An unbound view asks Core to discover its project's session."""
        return registry.session_thread(project, self.thread_name()).name_or(self.thread_name())

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

    def resolve_thread(self, registry, project: Path) -> str:
        """A bound view requires its original name; it never discovers a replacement."""
        return registry.require(self.owner.name).name

    def with_thread(self, thread: str):
        return ThreadIdentity(self.owner.renamed(thread), self.root)

    def with_root(self, root: str | None):
        return self if root == self.root else super().with_root(root)

    def with_session(self, session_id: str):
        """A managed thread keeps its declared name and incarnation."""
        return self

    async def inspect_owner(self, read_owner, show_detached) -> None:
        await read_owner(self)

    def bind_history(self, histories) -> None:
        histories.bind_scope(f"thread:{self.thread_name()}")

    def wire_root(self) -> str:
        return self.root

    def transcript_scope(self) -> tuple[str, str]:
        return self.root, self.thread_name()

    def transcript_state(self):
        return UnreadTranscript()

    def display_root(self) -> str:
        return format_path(self.root_path())

    def inspection_state(self):
        from toad.core.context_inspection import ReadingOwnerInspection
        return ReadingOwnerInspection()

    def root_path(self) -> Path:
        return Path(self.root).expanduser().resolve()
