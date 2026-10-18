"""The thread and wire named by one logical session view."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ThreadIdentity:
    thread: str
    root: str | None

    @property
    def managed(self) -> bool:
        return bool(self.thread) and self.root is not None
