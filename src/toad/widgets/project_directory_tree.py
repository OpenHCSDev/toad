from pathlib import Path
from typing import Iterable

import asyncio

from textual import work
from textual.binding import Binding
from textual.message import Message
from textual.widgets import DirectoryTree
from textual.widgets.directory_tree import DirEntry

from toad.path_filter import PathFilter


class ProjectDirectoryTree(DirectoryTree):
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

    BINDINGS = [
        Binding(
            "ctrl+c",
            "dismiss",
            "Interrupt",
            tooltip="Interrupt running command",
            show=False,
        ),
        Binding("ctrl+r", "refresh", "Refresh", tooltip="Refresh file view", show=True),
        Binding(
            "shift+enter",
            "insert_selected",
            "Insert path",
            tooltip="Insert selected path in prompt",
            show=False,
        ),
    ]

    def __init__(
        self,
        path: str | Path,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        self.path_filter: PathFilter | None = None
        self._directory_dirty = False
        self._refresh_scheduled = False
        path = Path(path).resolve() if isinstance(path, str) else path.resolve()
        super().__init__(path, name=name, id=id, classes=classes, disabled=disabled)

    async def watch_path(self) -> None:
        """Watch for changes to the `path` of the directory tree.

        If the path is changed the directory tree will be repopulated using
        the new value as the root.
        """
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
        self.scroll_to(0, 0, animate=False)

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

    def on_show(self) -> None:
        self.refresh_if_visible()

    def refresh_if_visible(self) -> None:
        if (self._directory_dirty and not self._refresh_scheduled and self.is_attached
                and self.is_on_screen and self.screen is self.app.screen):
            self._refresh_scheduled = True
            self.call_after_refresh(self._begin_refresh)

    def _begin_refresh(self) -> None:
        if not self.is_attached or not self.is_on_screen or self.screen is not self.app.screen:
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
    async def action_refresh(self) -> None:
        await self.reload()
        self.notify("Project directory has been refreshed", title="Directory Tree")

    def action_insert_selected(self) -> None:
        if self.cursor_node is not None and self.cursor_node.data is not None:
            path = self.cursor_node.data.path
            if path.is_file():
                self.post_message(self.InsertSelected(path))
