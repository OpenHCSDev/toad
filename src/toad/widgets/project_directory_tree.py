from pathlib import Path
from typing import Iterable

import asyncio

from formbridge.key_declarations import TextEntryMode
from textual import work

from toad.widget_actions import Action, NativeMethodKeys
from textual.message import Message
from textual.widgets import DirectoryTree
from textual.widgets.directory_tree import DirEntry

from toad.path_filter import PathFilter
from toad.tone_paint import UntintedTonePaint
from textual.events import Show
from textual import on


class ProjectTreeAction(Action, affix="Action"):
    """Keys the project directory tree answers."""


class RefreshAction(ProjectTreeAction):
    """Refresh file view."""

    keys = {TextEntryMode: ("ctrl+r",)}
    show = True

    def apply(self, tree: ProjectDirectoryTree) -> None:
        tree.refresh_directory()


class InsertPathAction(ProjectTreeAction):
    """Insert selected path in prompt."""

    keys = {TextEntryMode: ("shift+enter",)}

    def apply(self, tree: ProjectDirectoryTree) -> None:
        tree.insert_selected()


class ProjectDirectoryTree(NativeMethodKeys, UntintedTonePaint, DirectoryTree,
                           actions=(ProjectTreeAction,)):
    BINDING_GROUP_TITLE = "Tree view"
    HELP = """\
## Project files

This shows the files in your project directory.

- **cursor keys** navigation
- **Enter** expand folder
- **Enter** preview file
- **Shift+Enter** insert file path in prompt
"""

    class InsertSelected(Message):
        def __init__(self, path: Path) -> None:
            self.path = path
            super().__init__()

    def __init__(
        self,
        path: str | Path,
        *,
        disabled: bool = False,
    ) -> None:
        self._path_ready = asyncio.Event()
        self.path_filter: PathFilter | None = None
        self._directory_dirty = False
        self._refresh_scheduled = False
        path = Path(path).resolve() if isinstance(path, str) else path.resolve()
        super().__init__(path, disabled=disabled)

    async def watch_path(self) -> None:
        """Watch for changes to the `path` of the directory tree.

        If the path is changed the directory tree will be repopulated using
        the new value as the root.
        """
        self._path_ready.clear()
        path = Path(self.path).absolute()
        path_filter = await asyncio.to_thread(PathFilter.from_git_root, path)
        if path != Path(self.path).absolute():
            return
        self.path_filter = path_filter
        has_cursor = self.cursor_node is not None
        self.reset_node(self.root, str(self.path), DirEntry(self.PATH(self.path)))
        await self.reload()
        if has_cursor:
            self.cursor_line = 0
        self.scroll_to(0, 0, animate=False, immediate=True)
        if path == Path(self.path).absolute():
            self._path_ready.set()

    async def wait_path_ready(self) -> None:
        """The original path watcher owns completion of reset/filter/reload."""
        await self._path_ready.wait()

    def invalidate(self) -> None:
        self._directory_dirty = True
        self.refresh_if_visible()

    def reload(self):
        # DirectoryTree replaces its queue and cancels the old loader. Finish
        # superseded queued jobs first, otherwise NodeExpanded handlers waiting
        # for old_queue.join() never return and tab close/layout waits can hang.
        old_queue = self._load_queue
        while not old_queue.empty():
            old_queue.get_nowait()
            old_queue.task_done()
        return super().reload()

    @on(Show)
    def on_show(self) -> None:
        self.refresh_if_visible()

    def refresh_if_visible(self) -> None:
        if (self._directory_dirty and not self._refresh_scheduled and self.is_attached
                and self.is_on_screen and self.screen.is_current):
            self._refresh_scheduled = True
            self.call_after_refresh(self._begin_refresh)

    def _begin_refresh(self) -> None:
        if not self.is_attached or not self.is_on_screen or not self.screen.is_current:
            self._refresh_scheduled = False
            return
        self._directory_dirty = False
        self._refresh_directory()

    @work(exclusive=True, group="directory-refresh")
    async def _refresh_directory(self) -> None:
        try:
            await self.reload()
        finally:
            self._refresh_scheduled = False
            # Changes during a reload request one follow-up, not repeated
            # cancellation of the in-flight loader on every filesystem event.
            self.refresh_if_visible()

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        """Filter the paths before adding them to the tree.

        Args:
            paths: The paths to be filtered.

        Returns:
            The filtered paths.

        By default this method returns all of the paths provided. To create
        a filtered `DirectoryTree` inherit from it and implement your own
        version of this method.
        """

        if (path_filter := self.path_filter) is not None:
            for path in paths:
                if not path_filter.match(path):
                    yield path
        else:
            yield from paths

    @work
    async def refresh_directory(self) -> None:
        await self.reload()
        self.notify("Project directory has been refreshed", title="Directory Tree")

    def insert_selected(self) -> None:
        path = self.cursor_path
        if path.is_file():
            self.post_message(self.InsertSelected(path))

    # --- ProjectTreeOwner protocol (toad.client.project_tree_intent) ---
    # One adapter here, one on the Qt side; ProjectTreeIntent.capture/restore are the
    # single owner of what the intent holds and how it is applied.

    @property
    def root_path(self) -> Path:
        return Path(self.path)

    def expanded_paths(self):
        nodes = [self.root]
        while nodes:
            node = nodes.pop()
            if node.data is not None and node.is_expanded:
                yield node.data.path
                nodes.extend(node.children)

    def read_cursor_path(self) -> Path:
        return self.cursor_path

    def read_scroll_offset(self) -> tuple[int, int]:
        offset = self.scroll_offset
        return (int(offset.x), int(offset.y))

    async def wait_ready(self) -> None:
        # The original async path watcher resets/reloads its tree after mount.
        # Reader restoration must follow that owned operation, not race its reset.
        await self.wait_path_ready()
        # Mount completion precedes the first native viewport layout.
        laid_out = asyncio.Event()
        self.call_after_refresh(laid_out.set)
        await laid_out.wait()

    async def apply_intent(self, intent) -> None:
        await self._add_to_load_queue(self.root)
        pending = [self.root]
        selection = self.root
        while pending:
            node = pending.pop()
            if node.data is None:
                continue
            path = node.data.path
            if intent.selected.is_relative_to(path):
                selection = node
            if path in intent.expanded:
                node.expand()
                await self._add_to_load_queue(node)
                pending.extend(node.children)
        # Selection and saved viewport are separate intent. move_cursor also
        # schedules an ensure-visible scroll that can overwrite the saved one.
        self.cursor_line = selection.line
        # Mount/expansion produces native resize messages on the first frame.
        # Scroll on the following refresh, after their viewport limits settle.
        committed = asyncio.get_running_loop().create_future()

        def restore_viewport() -> None:
            # Path changes and unmount cancel the panel's original worker.
            # Its queued refresh callback must retire with that continuation.
            if committed.cancelled():
                return
            # Restoring an owned reader is independent of a scrollbar that
            # has not yet been shown; native geometry still clamps the target.
            self.scroll_to(intent.scroll[0], intent.scroll[1], animate=False,
                           immediate=True, force=True)
            committed.set_result(None)

        self.call_after_refresh(restore_viewport)
        await committed
