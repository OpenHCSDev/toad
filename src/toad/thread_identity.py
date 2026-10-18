"""A session's absent, local or wire-bound thread, with its owned behavior."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar


class SessionIdentity(ABC):
    managed: ClassVar[bool] = False

    @classmethod
    def for_thread(cls, thread: str, root: str | None):
        """Decode the optional wire binding once when accepting a source."""
        if not thread:
            return NoThreadIdentity()
        if root is None:
            return LocalThreadIdentity(thread)
        return ThreadIdentity(thread, root)

    @abstractmethod
    def thread_name(self) -> str: ...

    def with_thread(self, thread: str):
        return self.for_thread(thread, self.wire_root())

    def with_root(self, root: str | None):
        return self.for_thread(self.thread_name(), root)

    def wire_root(self) -> str | None:
        return None

    def transcript_scope(self) -> tuple[str, str] | None:
        return None

    @abstractmethod
    def display_thread(self) -> str: ...

    def display_root(self) -> str:
        return "No managed wire"

    def inspection_state(self):
        from toad.core.context_inspection import DetachedInspection
        return DetachedInspection()

    def root_path(self) -> Path | None:
        return None


@dataclass(frozen=True)
class NoThreadIdentity(SessionIdentity):
    def thread_name(self) -> str:
        return ""

    def display_thread(self) -> str:
        return "No thread"


@dataclass(frozen=True)
class NamedThreadIdentity(SessionIdentity, ABC):
    thread: str

    def thread_name(self) -> str:
        return self.thread

    def display_thread(self) -> str:
        return f"@{self.thread}"


@dataclass(frozen=True)
class LocalThreadIdentity(NamedThreadIdentity):
    """A named session without a managed wire."""


@dataclass(frozen=True)
class ThreadIdentity(NamedThreadIdentity):
    root: str
    managed: ClassVar[bool] = True

    def wire_root(self) -> str:
        return self.root

    def transcript_scope(self) -> tuple[str, str]:
        return self.root, self.thread

    def display_root(self) -> str:
        path = self.root_path()
        try:
            return f"~/{path.relative_to(Path.home())}"
        except ValueError:
            return str(path)

    def inspection_state(self):
        from toad.core.context_inspection import ReadingOwnerInspection
        return ReadingOwnerInspection()

    def root_path(self) -> Path:
        return Path(self.root).expanduser().resolve()
