"""Qt's file pickers for a message composer: the file dialog and the project path search.

The dialog is Qt's own QFileDialog. On Android, Qt answers it with the system's document
picker (the Storage Access Framework), which returns a `content://` URL that QFile reads;
on a desktop it is the platform's dialog. The path search ranks the project's paths through
the shared ProjectPaths, as Textual's @ completion does. Both hand the bytes they read to
`MessagePromptComposer.file_picked`, which decides what is attached.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QFile, QFileInfo, QIODevice, Qt, QUrl
from PySide6.QtWidgets import QDialog, QFileDialog, QLineEdit, QListWidget, QVBoxLayout, QWidget

from toad.client.message_files import FileSearch, MessagePromptComposer
from toad.client.project_paths import ProjectPathSearch
from toad.prompt_actions import AttachFileAction


def read_picked(url: QUrl, composer: MessagePromptComposer) -> None:
    """Read what a picker chose, up to what the composer can still attach, and attach it."""
    location = url.toString(QUrl.UrlFormattingOption.PreferLocalFile)
    picked = QFile(location)
    if not picked.open(QIODevice.OpenModeFlag.ReadOnly):
        composer.show_failure(f"Could not read {location}: {picked.errorString()}")
        return
    try:
        content = bytes(picked.read(composer.read_limit).data())
    finally:
        picked.close()
    composer.file_picked(QFileInfo(location).fileName(), content)


def open_file_dialog(parent: QWidget, composer: MessagePromptComposer) -> QFileDialog:
    """Qt's file dialog over ``parent``, attaching the file it returns."""
    dialog = QFileDialog(parent, AttachFileAction.title)
    dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
    # An accepted dialog holds its one choice: Qt's own dialog emits no urlSelected, and
    # Android's document picker answers with a content:// URL, so both are read from here.
    dialog.accepted.connect(lambda: [read_picked(url, composer) for url in dialog.selectedUrls()])
    dialog.finished.connect(dialog.deleteLater)
    dialog.open()
    return dialog


class QtPathSearch(ProjectPathSearch, QDialog):
    """The project's paths, ranked as you type; choosing one attaches that file."""

    shown_limit = 100

    def __init__(self, parent: QWidget, root: Path, chosen: Callable[[Path], None],
                 run: Callable) -> None:
        super().__init__(parent)
        self.start_path_search(root)
        self.setWindowTitle(AttachFileAction.title)
        self.chosen, self.run = chosen, run
        self.listing: list[str] = []
        self.query = QLineEdit(self)
        self.query.setPlaceholderText(f"Search {root}")
        self.results = QListWidget(self)
        layout = QVBoxLayout(self)
        layout.addWidget(self.query)
        layout.addWidget(self.results, 1)
        self.query.textChanged.connect(self.search)
        self.query.returnPressed.connect(self.choose_current)
        self.results.itemActivated.connect(lambda item: self.choose(item.text()))
        self.finished.connect(self.deleteLater)
        run(FileSearch, self.list_project)

    async def list_project(self) -> None:
        self.listing = self.spell_paths(await self.scan_paths(add_directories=False))
        await self.rank_paths(self.listing)
        self.show_paths(self.listing)

    def search(self, text: str) -> None:
        self.run(FileSearch, lambda: self.show_ranked(text))

    async def show_ranked(self, text: str) -> None:
        self.show_paths(await self.ranked(text) if text else self.listing)

    def show_paths(self, spellings: list[str]) -> None:
        self.results.clear()
        self.results.addItems(spellings[:self.shown_limit])
        self.results.setCurrentRow(0)

    def choose_current(self) -> None:
        if (item := self.results.currentItem()) is not None:
            self.choose(item.text())

    def choose(self, spelling: str) -> None:
        self.accept()
        self.chosen(self.root / spelling)


def open_path_search(parent: QWidget, composer: MessagePromptComposer, root: Path, run: Callable) -> QtPathSearch:
    search = QtPathSearch(parent, root, lambda path: run(FileSearch, lambda: composer.attach_path(path)), run)
    search.setWindowModality(Qt.WindowModality.WindowModal)
    search.open()
    return search
