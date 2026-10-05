"""Filesystem identities survive a disposable DirectoryTree's nodes."""
import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from textual.geometry import Offset

if TYPE_CHECKING:
    from toad.widgets.project_directory_tree import ProjectDirectoryTree


@dataclass(frozen=True)
class ProjectTreeIntent:
    path: Path
    expanded: frozenset[Path]
    selected: Path | None
    scroll: Offset

    @classmethod
    def capture(cls, tree: "ProjectDirectoryTree") -> "ProjectTreeIntent":
        expanded: set[Path] = set()
        nodes = [tree.root]
        while nodes:
            node = nodes.pop()
            if node.data is not None and node.is_expanded:
                expanded.add(node.data.path)
                nodes.extend(node.children)
        selected = tree.cursor_node
        return cls(Path(tree.path), frozenset(expanded),
                   selected.data.path if selected is not None and selected.data is not None else None,
                   tree.scroll_offset)

    async def restore(self, tree: "ProjectDirectoryTree") -> None:
        if Path(tree.path) != self.path:
            return
        # Mount completion precedes the first native viewport layout.
        laid_out = asyncio.Event()
        tree.call_after_refresh(laid_out.set)
        await laid_out.wait()
        await tree._add_to_load_queue(tree.root)
        pending = [tree.root]
        selection = tree.root
        while pending:
            node = pending.pop()
            if node.data is None:
                continue
            path = node.data.path
            if self.selected is not None and self.selected.is_relative_to(path):
                selection = node
            if path in self.expanded:
                node.expand()
                await tree._add_to_load_queue(node)
                pending.extend(node.children)
        # Selection and saved viewport are separate intent. move_cursor also
        # schedules an ensure-visible scroll that can overwrite the saved one.
        tree.cursor_line = selection.line
        # Mount/expansion produces native resize messages on the first frame.
        # Scroll on the following refresh, after their viewport limits settle.
        committed = asyncio.get_running_loop().create_future()

        def restore_viewport() -> None:
            # Path changes and unmount cancel the panel's original worker.
            # Its queued refresh callback must retire with that continuation.
            if committed.cancelled():
                return
            tree.scroll_to(self.scroll.x, self.scroll.y, animate=False,
                           immediate=True)
            committed.set_result(None)

        tree.call_after_refresh(restore_viewport)
        await committed
