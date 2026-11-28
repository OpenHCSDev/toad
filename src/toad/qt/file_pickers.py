"""Qt's file pickers for a message composer: the file dialog and the project path search.

The dialog is Qt's own QFileDialog. On a desktop it is Qt's themed dialog (pyqt-reactive's
theme selects it). On Android it is native: Qt asks the activity for a document, and the
APK's activity offers Android's chooser in its place - the apps that give a file (Files,
Photos, Drive) and the camera (tools/android/keepalive AttachChooser). Either answer comes
back as a `content://` URL that QFile reads. The path search ranks the project's paths through
the shared ProjectPaths, as Textual's @ completion does. Both hand the bytes they read to
`MessagePromptComposer.file_picked`, which decides what is attached.
"""

from __future__ import annotations

import mimetypes
from collections.abc import Callable
from pathlib import Path

from agent_comms.messaging.message_files import MAX_MESSAGE_FILE_BYTES
from PySide6.QtCore import QBuffer, QByteArray, QFile, QFileInfo, QIODevice, Qt, QUrl
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QDialog, QFileDialog, QLineEdit, QListWidget, QVBoxLayout, QWidget

from toad.client.message_file_links import file_size
from toad.client.message_files import FileSearch, MessagePromptComposer
from toad.client.project_paths import ProjectPathSearch
from toad.prompt_actions import AttachFileAction
from toad.qt.presented_window import PresentedWindow

MAX_COMPRESSIBLE_IMAGE_BYTES = 4 * MAX_MESSAGE_FILE_BYTES
"""Maximum raw image size read when auto-compressing an oversized photo to fit a message."""


def compress_image_bytes(
    name: str,
    mime_type: str,
    content: bytes,
    *,
    max_dimension: int = 2048,
    jpeg_quality: int = 82,
) -> tuple[str, str, bytes] | None:
    """Re-encode an image to a smaller JPEG (downscaling longest side to ``max_dimension``).
    Returns ``(new_name, "image/jpeg", encoded)`` only when smaller than ``content``."""
    image = QImage.fromData(QByteArray(content))
    if image.isNull():
        return None
    scaled = image.width() > max_dimension or image.height() > max_dimension
    if scaled:
        image = image.scaled(
            max_dimension,
            max_dimension,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    candidates: list[tuple[str, str, bytes]] = []
    rgb = image.convertToFormat(QImage.Format.Format_RGB888) if image.hasAlphaChannel() else image
    stem = Path(name).stem or "image"
    targets = [(".jpg", "JPEG", "image/jpeg", jpeg_quality, rgb)]
    if scaled:
        targets.append((".png", "PNG", "image/png", -1, image))
    for ext, fmt, mime, quality, source in targets:
        buf = QBuffer()
        if not buf.open(QIODevice.OpenModeFlag.WriteOnly):
            continue
        try:
            if source.save(buf, fmt, quality):
                encoded = bytes(buf.data().data())
                if encoded:
                    candidates.append((f"{stem}{ext}", mime, encoded))
        finally:
            buf.close()
    smaller = [item for item in candidates if len(item[2]) < len(content)]
    return min(smaller, key=lambda item: len(item[2])) if smaller else None


def read_picked(url: QUrl, composer: MessagePromptComposer) -> None:
    """Read what a picker chose, up to what the composer can still attach, and attach it.
    An oversized image that would otherwise exceed the message byte cap is compressed first."""
    # A local file's path, else the URL itself: QFile opens an Android content:// URL as is.
    location = url.toLocalFile() or url.toString()
    name = QFileInfo(location).fileName()
    guessed_mime = mimetypes.guess_type(name)[0] or ""
    picked = QFile(location)
    if not picked.open(QIODevice.OpenModeFlag.ReadOnly):
        composer.show_failure(f"Could not read {location}: {picked.errorString()}")
        return
    try:
        limit = composer.read_limit
        content = bytes(picked.read(limit).data())
        if len(content) >= limit and (guessed_mime.startswith("image/") or not guessed_mime):
            # Read the full image (bounded) and compress so large phone photos fit in one tap.
            rest = bytes(picked.read(max(0, MAX_COMPRESSIBLE_IMAGE_BYTES - len(content))).data())
            full = content + rest
            if len(full) <= MAX_COMPRESSIBLE_IMAGE_BYTES:
                compressed = compress_image_bytes(name, guessed_mime or "image/jpeg", full)
                if compressed is not None and len(compressed[2]) < limit:
                    new_name, new_mime, new_bytes = compressed
                    composer.file_picked(new_name, new_bytes, new_mime)
                    composer.show_compression_summary(
                        f"Compressed {name}: {file_size(len(full))} -> {file_size(len(new_bytes))}"
                    )
                    return
    finally:
        picked.close()
    composer.file_picked(name, content)


def open_file_dialog(parent: QWidget, composer: MessagePromptComposer) -> QFileDialog:
    """Qt's file dialog over ``parent``, attaching all files it returns."""
    dialog = QFileDialog(parent, AttachFileAction.title)
    dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
    # An accepted dialog holds its chosen URLs: Qt's own dialog emits no urlSelected, and
    # Android's document picker returns one or more content:// URLs via ClipData/getData.
    dialog.accepted.connect(lambda: [read_picked(url, composer) for url in dialog.selectedUrls()])
    dialog.finished.connect(dialog.deleteLater)
    dialog.open()
    return dialog


class QtPathSearch(PresentedWindow, ProjectPathSearch, QDialog):
    """The project's paths, ranked as you type; choosing one or more attaches those files."""

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
        self.results.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
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
        selected = [item.text() for item in self.results.selectedItems()]
        if selected:
            self.choose_many(selected)
        elif (item := self.results.currentItem()) is not None:
            self.choose(item.text())

    def choose_many(self, spellings: list[str]) -> None:
        self.accept()
        for spelling in spellings:
            self.chosen(self.root / spelling)

    def choose(self, spelling: str) -> None:
        self.choose_many([spelling])


def open_path_search(parent: QWidget, composer: MessagePromptComposer, root: Path, run: Callable) -> QtPathSearch:
    search = QtPathSearch(parent, root, lambda path: run(FileSearch, lambda: composer.attach_path(path)), run)
    search.setWindowModality(Qt.WindowModality.WindowModal)
    search.open()
    return search
