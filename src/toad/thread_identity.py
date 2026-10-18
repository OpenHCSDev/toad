"""The thread and wire named by one logical session view."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar


class SessionIdentity(ABC):
    managed: ClassVar[bool]

    @abstractmethod
    def display_thread(self) -> str: ...

    @abstractmethod
    def display_root(self) -> str: ...

    @abstractmethod
    def inspection_state(self): ...

    @abstractmethod
    def root_path(self) -> Path | None: ...


@dataclass(frozen=True)
class NoThreadIdentity(SessionIdentity):
    managed: ClassVar[bool] = False

    def display_thread(self) -> str:
        return "No thread"

    def display_root(self) -> str:
        return "No managed wire"

    def inspection_state(self):
        from toad.core.context_inspection import DetachedInspection
        return DetachedInspection()

    def root_path(self) -> None:
        return None


@dataclass(frozen=True)
class ThreadIdentity(SessionIdentity):
    thread: str
    root: str
    managed: ClassVar[bool] = True

    def display_thread(self) -> str:
        return f"@{self.thread}"

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
