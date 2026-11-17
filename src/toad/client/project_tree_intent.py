"""Toolkit-neutral project-tree intent: the filesystem state a reader left in a project
tree (expanded folders, cursor path, scroll offset) so it survives a disposable panel's
destruction and restores onto its replacement.

The frontend owns its native tree widget (Textual's `ProjectDirectoryTree`, Qt's
`QtProjectTreeView`). Each one implements `ProjectTreeOwner` so the capture/restore
algorithm here is the single owner of what makes an intent and how it is applied.
Lifted from `widgets/project_tree_intent.py` so Qt can read and apply intents without
pulling the Textual geometry types.

Protocol method names are prefixed `read_*` where the natural noun (`cursor_path`,
`scroll_offset`) already names a Textual widget attribute, so an implementation can
add protocol methods without shadowing native names.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


class TreeIntent:
    """What a reader left in a project tree; the family answers every reader without
    absence tests."""

    async def restore(self, owner: ProjectTreeOwner) -> None:
        """Nothing was left to restore."""

    def pending_or(self, capture: Callable[[], TreeIntent]) -> TreeIntent:
        """An intent still to restore answers for the tree; without one, read the tree now."""
        return capture()


NO_TREE_INTENT = TreeIntent()


@runtime_checkable
class ProjectTreeOwner(Protocol):
    """The native-tree adapter the capture/restore algorithm reads and writes against.
    Every frontend implements this once; nothing else here knows a tree widget's API."""

    @property
    def root_path(self) -> Path: ...

    def expanded_paths(self) -> Iterable[Path]:
        """Every currently-expanded node's path, in any order."""

    def read_cursor_path(self) -> Path:
        """Where the cursor sits; the root when the reader moved no cursor."""

    def read_scroll_offset(self) -> tuple[int, int]:
        """The tree's native (x, y) scroll offset."""

    async def wait_ready(self) -> None:
        """Wait until the tree is ready to accept expansion/cursor/scroll changes."""

    async def apply_intent(self, intent: ProjectTreeIntent) -> None:
        """Expand the recorded paths, move the cursor, scroll. Native-specific."""


@dataclass(frozen=True)
class ProjectTreeIntent(TreeIntent):
    path: Path
    expanded: frozenset[Path]
    selected: Path
    scroll: tuple[int, int]

    def pending_or(self, capture: Callable[[], TreeIntent]) -> TreeIntent:
        return self

    @classmethod
    def capture(cls, owner: ProjectTreeOwner) -> ProjectTreeIntent:
        return cls(
            path=Path(owner.root_path),
            expanded=frozenset(owner.expanded_paths()),
            selected=owner.read_cursor_path(),
            scroll=owner.read_scroll_offset(),
        )

    async def restore(self, owner: ProjectTreeOwner) -> None:
        if Path(owner.root_path) != self.path:
            return
        await owner.wait_ready()
        if Path(owner.root_path) != self.path:
            return
        await owner.apply_intent(self)
