"""Qt port of the thread sidebar's Project panel: a native file tree rooted at the
session's project path, over the same `ProjectTreeOwner` protocol Textual's
`ProjectDirectoryTree` implements. The capture / restore algorithm is in
`toad.client.project_tree_intent`; this widget is a thin adapter between it and
Qt's `QFileSystemModel` + `QTreeView`.

Child of its parent window throughout — a parent-less QWidget on Qt-for-Android
becomes a top-level QWindow and recurses into the EGL deadlock protector during
the first paint flush (SIGABRT, matching PR #1885/#1919 root cause).
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt, QTimer
from PySide6.QtWidgets import QFileSystemModel, QTreeView, QVBoxLayout, QWidget

from toad.thread_sidebar_declarations import ProjectSidebarPanel, ThreadSidebarPanelBody
from toad.client.project_tree_intent import (
    NO_TREE_INTENT,
    ProjectTreeIntent,
    TreeIntent,
)
from toad.client.project_view import ProjectView


class QtProjectPanel(ThreadSidebarPanelBody, ProjectView, QWidget):
    panel_type = ProjectSidebarPanel

    """The Qt sidebar's project tree. `ProjectView` is the toolkit-neutral base
    Textual's `ProjectPanel` also inherits from, so a screen can hold a project
    view on either frontend with the same interface. The widget itself implements
    the `ProjectTreeOwner` protocol so `ProjectTreeIntent.capture/restore` work
    against this tree the same way they work against the Textual tree."""

    def __init__(self, root: Path, *, intent: TreeIntent = NO_TREE_INTENT,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Widget)
        self._root = Path(root).resolve()
        self._intent: TreeIntent = intent
        self._model = QFileSystemModel(self)
        self._model.setRootPath(str(self._root))
        self._tree = QTreeView(self)
        self._tree.setModel(self._model)
        self._tree.setRootIndex(self._model.index(str(self._root)))
        self._tree.setHeaderHidden(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setExpandsOnDoubleClick(True)
        self._tree.setAnimated(False)
        # Hide the model's other columns (size, type, modified) so the tree
        # reads as a file list on a phone-width sidebar.
        for column in range(1, self._model.columnCount()):
            self._tree.hideColumn(column)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._tree, 1)
        self._ready = asyncio.Event()
        # QFileSystemModel loads the root directory asynchronously; mark ready
        # on its directoryLoaded(rootPath) signal so restores wait for the
        # first set of nodes before trying to expand them.
        self._model.directoryLoaded.connect(self._directory_loaded)
        if intent is not NO_TREE_INTENT:
            QTimer.singleShot(0, self._kick_restore)

    # --- ProjectView overrides (toolkit-neutral base; widgets.project_panel
    # mirrors these on the Textual side) ---

    def invalidate(self) -> None:
        # Force the model to re-read the root the next time it is shown.
        self._model.setRootPath("")
        self._model.setRootPath(str(self._root))
        self._tree.setRootIndex(self._model.index(str(self._root)))

    def show_project(self, path: Path) -> None:
        resolved = Path(path).resolve()
        if resolved == self._root:
            return
        self._root = resolved
        self._intent = NO_TREE_INTENT
        self._ready.clear()
        self._model.setRootPath(str(self._root))
        self._tree.setRootIndex(self._model.index(str(self._root)))

    # --- ProjectTreeOwner protocol (toad.client.project_tree_intent) ---

    @property
    def root_path(self) -> Path:
        return self._root

    def expanded_paths(self) -> Iterable[Path]:
        root_index = self._tree.rootIndex()
        yield from self._walk_expanded(root_index)

    def _walk_expanded(self, index: QModelIndex) -> Iterable[Path]:
        for row in range(self._model.rowCount(index)):
            child = self._model.index(row, 0, index)
            if self._tree.isExpanded(child):
                yield Path(self._model.filePath(child))
                yield from self._walk_expanded(child)

    def read_cursor_path(self) -> Path:
        cursor = self._tree.currentIndex()
        if cursor.isValid():
            return Path(self._model.filePath(cursor))
        return self._root

    def read_scroll_offset(self) -> tuple[int, int]:
        return (
            self._tree.horizontalScrollBar().value(),
            self._tree.verticalScrollBar().value(),
        )

    async def wait_ready(self) -> None:
        if self._model.index(str(self._root)).isValid():
            return
        await self._ready.wait()

    async def apply_intent(self, intent: ProjectTreeIntent) -> None:
        # Expand every path the intent recorded; QFileSystemModel loads
        # children on demand, so the expansion walks top-down under each
        # expanded ancestor.
        for path in sorted(intent.expanded, key=lambda p: len(p.parts)):
            index = self._model.index(str(path))
            if index.isValid():
                self._tree.expand(index)
        if intent.selected != self._root:
            cursor = self._model.index(str(intent.selected))
            if cursor.isValid():
                self._tree.setCurrentIndex(cursor)
        x, y = intent.scroll
        self._tree.horizontalScrollBar().setValue(x)
        self._tree.verticalScrollBar().setValue(y)

    # --- Qt internals ---

    def _directory_loaded(self, path: str) -> None:
        if Path(path) == self._root:
            self._ready.set()

    def _kick_restore(self) -> None:
        intent = self._intent
        self._intent = NO_TREE_INTENT
        if intent is NO_TREE_INTENT:
            return
        loop = asyncio.get_event_loop_policy().get_event_loop()
        if loop.is_running():
            loop.create_task(intent.restore(self))

    def capture_intent(self) -> TreeIntent:
        """Read the current tree state as a `ProjectTreeIntent` using the shared
        `ProjectTreeIntent.capture` algorithm; the result survives a panel
        rebuild and can be restored onto a fresh instance."""
        return ProjectTreeIntent.capture(self)
