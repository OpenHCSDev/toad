"""Filesystem identities survive a disposable DirectoryTree's nodes."""
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
        tree.move_cursor(selection, animate=False)
        # Mount/expansion produces native resize messages on the first frame.
        # Scroll on the following refresh, after their viewport limits settle.
        tree.call_after_refresh(tree.scroll_to, self.scroll.x, self.scroll.y,
                                animate=False)
