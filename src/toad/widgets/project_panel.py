from __future__ import annotations

import asyncio
from pathlib import Path

from textual import events, work
from textual.reactive import reactive
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Static

from toad.widgets.project_directory_tree import ProjectDirectoryTree
from toad.widgets.project_tree_intent import ProjectTreeIntent
from toad.widgets.worker_static import WorkerStatic


class ProjectSearchButton(Static, can_focus=True):
    DEFAULT_CSS = """
    ProjectSearchButton {
        height: 1;
        color: $text-muted;
        pointer: pointer;
    }
    ProjectSearchButton:hover,
    ProjectSearchButton:focus {
        color: $text;
        background: $surface-lighten-2;
        text-style: bold;
    }
    """
    BINDINGS = [Binding("enter", "search", "Search files", show=False)]

    class Requested(Message):
        pass

    def __init__(self) -> None:
        super().__init__("⌕ Search files")

    def action_search(self) -> None:
        self.post_message(self.Requested())

    def on_click(self, event: events.Click) -> None:
        if event.button == 1:
            event.stop()
            self.action_search()


class ProjectPanel(Vertical):
    path: reactive[Path] = reactive(Path, init=False)
    DEFAULT_CSS = """
    ProjectPanel {
        height: 1fr;
    }
    ProjectPanel ProjectDirectoryTree {
        height: 1fr;
    }
    """

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.directory_tree: ProjectDirectoryTree | None = None
        self.path = path
        self._tree_requested = False

    def compose(self) -> ComposeResult:
        yield ProjectSearchButton()

    def on_show(self) -> None:
        self.call_after_refresh(self._ensure_tree)

    def _ensure_tree(self) -> None:
        from toad.widgets.side_bar import SideBar, SideBarCollapsible

        if not self.is_attached:
            return
        sidebar = next((node for node in self.ancestors if isinstance(node, SideBar)), None)
        panel = next((node for node in self.ancestors if isinstance(node, SideBarCollapsible)), None)
        if sidebar is None or panel is None or sidebar.collapsed or panel.collapsed:
            return
        if self.screen.is_current and not self._tree_requested:
            self._tree_requested = True
            self._mount_tree()

    @work(group="project-tree")
    async def _mount_tree(self) -> None:
        self.directory_tree = ProjectDirectoryTree(self.path, id="project_directory_tree")
        await self.mount(self.directory_tree)

    def watch_path(self, path: Path) -> None:
        if self.directory_tree is not None:
            self.directory_tree.path = path

    def invalidate(self) -> None:
        if self.directory_tree is not None:
            self.directory_tree.invalidate()

    def refresh_if_visible(self) -> None:
        if self.directory_tree is not None:
            self.directory_tree.refresh_if_visible()

    def capture_intent(self) -> ProjectTreeIntent | None:
        """Read the completed native projection at this panel's owner."""
        if self.directory_tree is not None:
            return ProjectTreeIntent.capture(self.directory_tree)
        return None


class RestorableProjectPanel(ProjectPanel):
    """A disposable tree restores filesystem intent using the original loader."""

    def __init__(self, path: Path, *, intent: ProjectTreeIntent | None = None) -> None:
        super().__init__(path)
        self._intent = intent

    def capture_intent(self) -> ProjectTreeIntent | None:
        """An unfinished restore retains its original reader, not a default node."""
        if self._intent is not None:
            return self._intent
        return super().capture_intent()

    def watch_path(self, path: Path) -> None:
        self._intent = None
        if self.directory_tree is not None:
            self.workers.cancel_group(self, "project-tree")
        super().watch_path(path)

    @work(group="project-tree")
    async def _mount_tree(self) -> None:
        await super()._mount_tree().wait()
        if self._intent is not None:
            await self._intent.restore(self.directory_tree)
            self._intent = None


class FilePreview(Vertical):
    """Bounded, read-only preview for one project file."""

    DEFAULT_CSS = """
    FilePreview {
        height: 1fr;
        padding: 0 1;
    }
    FilePreview > Static {
        width: 1fr;
        height: auto;
    }
    FilePreview > .file-preview-path {
        width: 1fr;
        color: $text-muted;
        border-bottom: solid $panel;
        margin-bottom: 1;
    }
    FilePreview > Markdown {
        width: 1fr;
        height: auto;
    }
    """
    def __init__(self, path: Path, *, id: str) -> None:
        super().__init__(id=id)
        self.path = path
        self._ready = asyncio.Event()
        self.loading = Static("Loading file…")
        self.body = VerticalScroll()

    def compose(self) -> ComposeResult:
        yield Static(str(self.path), classes="file-preview-path", markup=False)
        yield self.loading
        yield self.body

    def on_mount(self) -> None:
        self._load_preview()

    async def wait_ready(self) -> None:
        await self._ready.wait()

    def on_unmount(self) -> None:
        self._ready.set()

    async def reveal(self, position):
        await self.wait_ready()
        if not self.is_attached:
            return
        await self._load_preview(position).wait()

    @work(group="file-preview-load", exclusive=True)
    async def _load_preview(self, position=None) -> None:
        try:
            from toad.file_kind import FileKind
            if position is not None:
                await self.body.remove_children()
            self.loading.update("Loading file…")
            self.loading.display = True
            try:
                kind = FileKind.for_path(self.path)
                source = await self.app.preparation.run_thread(kind.load, self.path)
                if self.is_attached and not self._pruning:
                    if position is None:
                        await kind.show(self, source)
                    else:
                        await kind.show_at(self, source, position)
            except (OSError, ValueError, EOFError) as error:
                if self.is_attached and not self._pruning:
                    self.loading.update(f"Unable to open {self.path}: {error}")
                return
            if self.is_attached and not self._pruning:
                self.loading.display = False
        finally:
            self._ready.set()
