"""The conversation composer on Qt: Textual's message prompt drawn natively. What it offers
after an @ or a /, what accepting an offer writes, and where a typed message goes all come
from the shared owners (MentionCompletion, SlashCommandResults over the CommandCatalog,
BusSubmissions); this module draws them and reads the keys."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, replace
from math import ceil
from typing import ClassVar

import shiboken6

from agent_comms.messaging.mentions import MentionCandidate
from agent_comms.messaging.message_files import FileUpload
from PySide6.QtCore import QBuffer, QEvent, QIODevice, QMimeData, Qt, QTimer, Slot
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QKeyEvent, QPalette, QTextCharFormat, QTextCursor
from pyqt_reactive.widgets.shared.list_item_delegate import LAYOUT_ROLE, MultilinePreviewItemDelegate
from pyqt_reactive.widgets.shared.styled_text_layout import Segment, StyledTextLayout
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from pyqt_reactive.widgets.fitted_text import WrappedText
from textual.cursor_shape import SteadyBlock
from textual.document._document import Document, DocumentBase, Location, RangedEditResult, Selection

from toad.clipboard_image import save_clipboard_png

from toad.client.application import ClientApplication
from toad.client.bus_submission import BusSubmissions, TypedText
from toad.client.commands import ConversationCommands
from toad.client.composer_pool import ComposerDraft, ComposerPoolHost
from toad.client.line_blocks import FailureRole, LineRole, MutedRole
from toad.client.mention_completion import MentionCompletion, MentionEditor
from toad.client.message_files import AttachedFileChip, ImageCompressionControl, MessagePromptComposer
from toad.client.prompt_composer import (
    ComposerOffer,
    MentionCandidateOffer,
    PromptComposer,
    PromptSettingEffects,
    SlashCommandOffer,
)
from toad.client import platform as toad_platform
from toad.client.condensed_path import home_relative
from toad.key_modes import KeyMode, Standard
from toad.neovim_editing import NeovimEditing, NeovimEditorSurface
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from ui_theme.scheme import MutedColour, PrimaryColour, SecondaryColour
from toad.prompt_actions import (
    AttachFileAction,
    MessageAction,
    NewlineAction,
    PasteClipboardAction,
    PromptAction,
    SubmitAction,
    SubmitInputAction,
    SubmitNowAction,
)
from toad.widget_actions import DeclaredWidgetActions, DismissAction
from toad.widget_contracts import (
    DismissibleContract,
    OpensSelectedContract,
    SelectsContract,
    SubmitsContract,
)
from toad.qt.file_pickers import compress_image_bytes, open_file_dialog, open_path_search
from toad.qt.hints import QtCallbackHintTarget, QtHintTargetSource
from toad.qt.lines import QtLineRenderer
from toad.qt.queue_ui import QtDeliveryControls, QtQueueHint, QtQueueInspection, QtQueueSummary, RowReveal
from toad.qt.prompt_stack import QtInfoBar
from toad.slash_command import SlashCommand
from toad.slash_command_results import CommandMatch, SlashCommandResults
from toad.qt.metrics import UiGap, delete_layout_widgets
from toad.qt.tap_flash import QtPushButton


def _bind_composer_shortcuts(composer: Composer):
    """One `QShortcut` per composer action on the editor, answering the action's keys in
    the current key mode and keymap (`ActionKeys`) and running the composer's own method
    while the editor (or a child) has focus. Textual reaches these methods through its own
    PromptTextArea action system — the keys live in one place.

    `SubmitAction` checks `composer.editor.submission_allowed` so Enter in Vim Normal/Visual/
    Command mode reaches the real embedded Neovim buffer instead of submitting."""
    return [
        composer.host.app.action_keys.bind(
            composer.editor,
            action_cls(),
            method.__get__(composer),
            context=action_cls.composer_shortcut_context(composer),
        )
        for action_cls, method in composer.action_methods
    ]


class ComposerHost(ConversationCommands):
    """What a composer asks of the conversation view it sits in: the commands it offers
    after a /, and where a typed message goes."""

    app: ClientApplication
    submissions: BusSubmissions

    def submit(self, text: TypedText, action: SubmitInputAction) -> None:
        raise NotImplementedError


class Offer(ComposerOffer):
    """One row of the list over the composer and what tapping it writes."""

    @property
    def layout(self) -> StyledTextLayout:
        return StyledTextLayout(name=Segment(self.offer_label))

    @abstractmethod
    def accept(self, composer: Composer) -> None: ...


@dataclass(frozen=True)
class CommandOffer(SlashCommandOffer, Offer):
    """A slash command: accepting it starts the message with the command, as Textual's
    SlashComplete inserts it."""

    match: CommandMatch

    @property
    def layout(self) -> StyledTextLayout:
        return StyledTextLayout(
            name=Segment(self.offer_label),
            detail_line=self.offer_detail,
            multiline=True,
        )

    def accept(self, composer: Composer) -> None:
        composer.editor.setPlainText(f"{self.match.command.command} ")
        composer.editor.editing_mode.move_to_end(composer.editor)


@dataclass(frozen=True)
class MentionOffer(MentionCandidateOffer, Offer):
    """A thread to mention at the cursor."""

    completion: MentionCompletion
    candidate: MentionCandidate

    def accept(self, composer: Composer) -> None:
        self.completion.accept(composer, self.candidate.name)


class OfferList(QListWidget, SelectsContract, OpensSelectedContract):
    """The offers for what the cursor is typing, over the editor; hidden when there are none."""

    rows = 7

    def __init__(self, composer: Composer) -> None:
        super().__init__()
        self.composer = composer
        self.offers: tuple[Offer, ...] = ()
        composer.renderer.themed(self, self.paint_colours)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.itemClicked.connect(self.take_item)
        self.hide()

    def paint_colours(self) -> None:
        """Offer lines in the current scheme's text colours."""
        scheme = self.composer.host.app.theme.color_scheme
        previous = self.itemDelegate()
        self.setItemDelegate(MultilinePreviewItemDelegate(
            scheme.to_qcolor(scheme.text_primary), scheme.to_qcolor(scheme.text_secondary),
            scheme.to_qcolor(scheme.selection_text), self))
        if previous is not None:
            previous.deleteLater()

    def select(self) -> None:
        """Move the cursor to the first offer; a Selects consumer uses this to choose."""
        if self.count():
            self.setCurrentRow(0)

    def open_selected(self) -> None:
        """Commit the row the cursor is on, the same way accept_current does."""
        self.accept_current()

    def show_offers(self, title: str, offers: tuple[Offer, ...]) -> None:
        if offers == self.offers:
            return
        self.offers = offers
        self.clear()
        for offer in offers:
            item = QListWidgetItem()
            item.setData(LAYOUT_ROLE, offer.layout)
            self.addItem(item)
        self.setToolTip(title)
        self.setCurrentRow(0)
        self.setFixedHeight(self.sizeHintForRow(0) * min(self.rows, len(offers)) + 4 if offers else 0)
        self.setVisible(bool(offers))

    def step(self, rows: int) -> None:
        self.setCurrentRow((self.currentRow() + rows) % self.count())

    def accept_current(self) -> None:
        self.offers[self.currentRow()].accept(self.composer)

    def take_item(self, item: QListWidgetItem) -> None:
        self.offers[self.row(item)].accept(self.composer)
        self.composer.editor.setFocus()


_QT_MODIFIER_KEYS = frozenset({
    Qt.Key.Key_Shift,
    Qt.Key.Key_Control,
    Qt.Key.Key_Alt,
    Qt.Key.Key_Meta,
    Qt.Key.Key_AltGr,
    Qt.Key.Key_CapsLock,
    Qt.Key.Key_NumLock,
    Qt.Key.Key_ScrollLock,
})

_QT_SPECIAL_KEYS: dict[int, str] = {
    Qt.Key.Key_Escape: "escape",
    Qt.Key.Key_Return: "enter",
    Qt.Key.Key_Enter: "enter",
    Qt.Key.Key_Backspace: "backspace",
    Qt.Key.Key_Delete: "delete",
    Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Backtab: "shift+tab",
    Qt.Key.Key_Left: "left",
    Qt.Key.Key_Right: "right",
    Qt.Key.Key_Up: "up",
    Qt.Key.Key_Down: "down",
    Qt.Key.Key_Home: "home",
    Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "pageup",
    Qt.Key.Key_PageDown: "pagedown",
    Qt.Key.Key_Insert: "insert",
    Qt.Key.Key_Space: "space",
    **{getattr(Qt.Key, f"Key_F{n}"): f"f{n}" for n in range(1, 13)},
}


def _qt_key_to_input(event: QKeyEvent) -> tuple[str, str] | None:
    """Translate one Qt `QKeyEvent` into `(key_name, character)` for `NeovimEditing.input_code`."""
    key = event.key()
    if key in _QT_MODIFIER_KEYS:
        return None
    mods = event.modifiers()
    ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
    alt = bool(mods & Qt.KeyboardModifier.AltModifier)
    meta = bool(mods & Qt.KeyboardModifier.MetaModifier)
    shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
    text = event.text()

    if key in _QT_SPECIAL_KEYS:
        base = _QT_SPECIAL_KEYS[key]
        parts: list[str] = []
        if ctrl:
            parts.append("ctrl")
        if alt:
            parts.append("alt")
        if meta:
            parts.append("meta")
        if shift and not base.startswith("shift+") and base != "space":
            parts.append("shift")
        parts.append(base)
        if not (ctrl or alt or meta) and base == "space":
            return ("space", " ")
        return ("+".join(parts), "")

    if not (ctrl or alt or meta) and text and text.isprintable():
        return (text, text)

    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        char = chr(ord("a") + (key - Qt.Key.Key_A))
        parts = []
        if ctrl:
            parts.append("ctrl")
        if alt:
            parts.append("alt")
        if meta:
            parts.append("meta")
        if shift:
            parts.append("shift")
        parts.append(char)
        return ("+".join(parts), char.upper() if shift and not (ctrl or alt or meta) else char)

    if 0x20 <= key <= 0x7E:
        char = chr(key)
        parts = []
        if ctrl:
            parts.append("ctrl")
        if alt:
            parts.append("alt")
        if meta:
            parts.append("meta")
        parts.append(char)
        return ("+".join(parts), char)

    return None


class ComposerEditor(QPlainTextEdit, NeovimEditorSurface, QtHintTargetSource):
    """The message being typed, backed by real embedded Neovim (`NeovimEditing`) when a modal
    key mode is active, or native `QPlainTextEdit` in `Standard` mode. Enter and Ctrl+Enter
    send when text entry is active, Shift+Enter starts a line; while offers are shown, Up and
    Down move through them and Enter or Tab takes one, Escape hides them. Escape with no offers
    visible routes through Neovim (exiting Insert/Visual/Command to Normal, and firing
    `StandardEditingAction` from idle Normal to focus the conversation window)."""

    def primary_hint_targets(self, host):
        if not self.isVisible() or not self.isEnabled():
            return ()
        x, y = self.hint_anchor(self, host)
        return (QtCallbackHintTarget(self, x, y, lambda: self.setFocus(Qt.FocusReason.ShortcutFocusReason)),)

    def __init__(self, composer: Composer) -> None:
        super().__init__()
        self.composer = composer
        self._engine_document: DocumentBase = Document("")
        self._cursor_location: Location = (0, 0)
        self._syncing_from_engine = False
        self._editing_mode: KeyMode = Standard()
        self._attached_mode: KeyMode | None = None
        self._engine_regions: tuple[Selection, ...] = ()
        self._neovim_paint_timer = QTimer(self)
        self._neovim_paint_timer.setSingleShot(True)
        self._neovim_paint_timer.setInterval(0)
        self._neovim_paint_timer.timeout.connect(self._run_neovim_paint)
        self._pending_paint_owner: NeovimEditing | None = None
        self.setTabChangesFocus(False)
        # Android soft-keyboard wiring: without these the tap registers but the IME
        # never raises, so the user sees a composer they can't type into. Desktop Qt
        # raises the OS keyboard implicitly on focus; Android Qt doesn't — the editor
        # has to opt in explicitly. Three pieces: (1) ClickFocus on Android (StrongFocus
        # on desktop) so a tap takes keyboard focus without QStackedWidget tab switches
        # auto-selecting the input box, (2) WA_InputMethodEnabled so the IME considers
        # the widget, (3) mousePressEvent/MouseFocusReason explicitly requests IME show.
        self.setFocusPolicy(
            Qt.FocusPolicy.StrongFocus
            if toad_platform.host.auto_focus_composer
            else Qt.FocusPolicy.ClickFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.destroyed.connect(self._close_attached_mode)
        self.follow_key_mode()

    @property
    def app(self):
        return self.composer.host.app

    @property
    def prompt(self):
        return self.composer

    @property
    def submission_allowed(self) -> bool:
        return self._editing_mode.accepts_text and not self.composer.offers.isVisible()

    def visual_line_count(self) -> int:
        """Lines Qt actually laid out, including soft wraps inside one text block."""
        return max(1, ceil(self.document().size().height()))

    def _close_attached_mode(self, *_args) -> None:
        previous = self._attached_mode
        self._attached_mode = None
        if previous is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if not loop.is_closed():
            loop.create_task(previous.close())

    def _ensure_mode_attached(self) -> None:
        if not shiboken6.isValid(self) or self._attached_mode is self._editing_mode:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self._engine_document = Document(self.toPlainText())
        self._cursor_location = self._qt_cursor_location()
        self._attached_mode = self._editing_mode
        self._editing_mode.attach_surface(self)

    def follow_key_mode(self) -> None:
        """Modal input follows `ui.key_mode`, the setting Textual's prompt reads: a modal key
        mode (`VimNormal`, `VimInsert`, `VimVisual`) embeds a real Neovim buffer session on
        `QtToadApp.neovim`; `Standard` uses native `QPlainTextEdit` editing."""
        key_mode = self.composer.settings.ui.key_mode
        if type(self._editing_mode) is key_mode and self._attached_mode is self._editing_mode:
            self.sync_cursor_shape()
            return
        self._close_attached_mode()
        self._editing_mode = key_mode()
        self._engine_regions = ()
        self.setExtraSelections([])
        self._ensure_mode_attached()
        self.sync_cursor_shape()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._ensure_mode_attached()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._attached_mode is self._editing_mode:
            self._editing_mode.resize(self)

    def sync_cursor_shape(self) -> None:
        """Block cursor when the active editing mode reports `SteadyBlock`, beam otherwise."""
        metrics = self.fontMetrics()
        block = self._editing_mode.cursor_shape == SteadyBlock()
        self.setOverwriteMode(block)
        self.setCursorWidth(
            max(6, metrics.averageCharWidth())
            if block
            else max(1, round(metrics.lineSpacing() * 0.12))
        )

    def changeEvent(self, event: QEvent) -> None:  # type: ignore[override]
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self.sync_cursor_shape()

    @property
    def editing_mode(self) -> KeyMode:
        """What the info bar's badge and composer actions read: the real `KeyMode` owner."""
        return self._editing_mode

    # ---- NeovimEditorSurface implementation on QPlainTextEdit ----

    @property
    def neovim_document(self) -> DocumentBase:
        return self._engine_document

    def set_neovim_document(self, document: DocumentBase) -> None:
        self._engine_document = document

    def _qt_cursor_location(self) -> Location:
        cursor = self.textCursor()
        return (cursor.blockNumber(), cursor.positionInBlock())

    def _qt_selection(self) -> Selection:
        cursor = self.textCursor()
        if not cursor.hasSelection():
            return Selection.cursor(self._qt_cursor_location())
        doc = self.document()
        anchor_blk = doc.findBlock(cursor.anchor())
        pos_blk = doc.findBlock(cursor.position())
        return Selection(
            (anchor_blk.blockNumber(), cursor.anchor() - anchor_blk.position()),
            (pos_blk.blockNumber(), cursor.position() - pos_blk.position()),
        )

    @property
    def neovim_selection(self) -> Selection:
        return self._qt_selection()

    @property
    def neovim_cursor_location(self) -> Location:
        return self._cursor_location

    @property
    def neovim_indent_width(self) -> int:
        return 4

    @property
    def neovim_wrap_width(self) -> int:
        char_w = max(1, self.fontMetrics().averageCharWidth())
        return max(1, self.viewport().width() // char_w)

    @property
    def neovim_content_height(self) -> int:
        return self.visual_line_count()

    @property
    def neovim_attached(self) -> bool:
        return shiboken6.isValid(self)

    def neovim_bindings(self, profile):
        return [
            (binding.key, binding)
            for action_cls in PromptAction.members_with(PromptAction)
            for binding in DeclaredWidgetActions.key_bindings(action_cls)
            if issubclass(profile, binding.mode)
        ]

    def neovim_clear_history(self) -> None:
        self.document().clearUndoRedoStacks()

    def neovim_schedule_paint(self, owner: NeovimEditing) -> bool:
        if not shiboken6.isValid(self):
            return False
        self._pending_paint_owner = owner
        if not self._neovim_paint_timer.isActive():
            self._neovim_paint_timer.start()
        return True

    def _run_neovim_paint(self) -> None:
        owner = self._pending_paint_owner
        self._pending_paint_owner = None
        if owner is not None and shiboken6.isValid(self):
            owner.paint(self)

    def neovim_call_later(self, callback: Callable[[], object]) -> bool:
        if not shiboken6.isValid(self):
            return False
        QTimer.singleShot(0, callback)
        return True

    def _move_qt_cursor(self, location: Location) -> None:
        row, col = location
        doc = self.document()
        block = doc.findBlockByNumber(min(max(0, row), max(0, doc.blockCount() - 1)))
        pos = block.position() + min(max(0, col), len(block.text()))
        cursor = self.textCursor()
        if cursor.position() != pos or cursor.hasSelection():
            cursor.setPosition(pos)
            self.setTextCursor(cursor)

    def neovim_paint_selection(self, selection: Selection) -> None:
        self._cursor_location = selection.end
        if not self._syncing_from_engine:
            self._move_qt_cursor(selection.end)

    def neovim_record_cursor_width(self) -> None:
        pass

    def neovim_project_edit(self, result: RangedEditResult) -> None:
        pass

    def neovim_finish_changes(self) -> None:
        text = self._engine_document.text
        self._syncing_from_engine = True
        try:
            if self.toPlainText() != text:
                super().setPlainText(text)
            self._move_qt_cursor(self._cursor_location)
        finally:
            self._syncing_from_engine = False
        self._paint_engine_regions()

    def neovim_invalidate_regions(self, regions: tuple[Selection, ...]) -> None:
        self._engine_regions = self._editing_mode.engine_regions()
        self._paint_engine_regions()

    def _paint_engine_regions(self) -> None:
        if not self._engine_regions:
            if self.extraSelections():
                self.setExtraSelections([])
            return
        scheme = self.composer.host.app.theme.color_scheme
        fmt = QTextCharFormat()
        fmt.setBackground(scheme.to_qcolor(scheme.selection_bg))
        fmt.setForeground(scheme.to_qcolor(scheme.selection_text))
        doc = self.document()
        max_block = max(0, doc.blockCount() - 1)
        extras: list[QTextEdit.ExtraSelection] = []
        for region in self._engine_regions:
            start_row, start_col = region.start
            end_row, end_col = region.end
            b0 = doc.findBlockByNumber(min(max(0, start_row), max_block))
            b1 = doc.findBlockByNumber(min(max(0, end_row), max_block))
            p0 = b0.position() + min(max(0, start_col), len(b0.text()))
            p1 = b1.position() + min(max(0, end_col), len(b1.text()))
            if p0 == p1:
                continue
            sel = QTextEdit.ExtraSelection()
            cursor = QTextCursor(doc)
            cursor.setPosition(min(p0, p1))
            cursor.setPosition(max(p0, p1), QTextCursor.MoveMode.KeepAnchor)
            sel.cursor = cursor
            sel.format = fmt
            extras.append(sel)
        self.setExtraSelections(extras)

    def neovim_show_mode(self, mode: NeovimEditing) -> None:
        self.sync_cursor_shape()
        self.composer.refresh_editing_mode()

    def neovim_refresh_bindings(self) -> None:
        self.composer.refresh_editing_mode()

    def neovim_notify(self, message: str, *, title: str, severity: str, timeout: float | None = None) -> None:
        self.composer.host.app.notify(message, title=title, severity=severity)

    def leave_modal_editor(self) -> None:
        """Move focus out of the composer to the conversation's history window, keeping the draft."""
        self.composer.offers.show_offers("", ())
        messages = getattr(self.composer.host, "messages", None)
        if messages is not None:
            messages.setFocus()
        else:
            self.clearFocus()

    # ---- Native `Standard` text-mutation hooks called polymorphically by `KeyMode` ----

    def set_native_text(self, text: str) -> None:
        super().setPlainText(text)

    def insert_native_text(self, text: str) -> None:
        super().insertPlainText(text)

    def clear_native_text(self) -> None:
        super().clear()

    def move_cursor(self, location: Location) -> None:
        self._move_qt_cursor(location)

    def replace_native_span(self, row: int, start: int, end: int, text: str) -> None:
        block = self.document().findBlockByNumber(row)
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + start)
        cursor.setPosition(block.position() + end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text)
        self.setTextCursor(cursor)

    def setPlainText(self, text: str) -> None:  # type: ignore[override]
        if self._syncing_from_engine:
            super().setPlainText(text)
            return
        self._engine_document = Document(text)
        self._editing_mode.set_text(self, text)

    def clear(self) -> None:  # type: ignore[override]
        if self._syncing_from_engine:
            super().clear()
            return
        self._engine_document = Document("")
        self._editing_mode.clear_text(self)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.composer.focus_changed(False)

    @staticmethod
    def _show_ime_if_hidden() -> None:
        ime = QGuiApplication.inputMethod()
        if not ime.isVisible():
            ime.show()

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if self._attached_mode is self._editing_mode:
            self._editing_mode.request_selection(self, self._qt_selection())
        # Defer the IME show() to the next event-loop tick. Firing inline inside
        # mousePressEvent reaches into Android's native IME path which recurses
        # into QAndroidPlatformOpenGLWindow::eglSurface() while the Qt event
        # dispatch still owns the surface — the platform plugin's deadlock
        # protector then SIGABRTs the app. Same class as #1885, #1901, #1911,
        # #1939 EGL fixes. Skip calling show() when the IME is already visible so
        # tapping inside an already-focused composer does not re-trigger Qt's
        # Android m_editText layout cycle.
        QTimer.singleShot(0, self._show_ime_if_hidden)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self._ensure_mode_attached()
        self.composer.focus_changed(True)
        # Only raise Android's soft keyboard on an explicit tap/click (MouseFocusReason),
        # never on implicit focus transfers when switching tabs or reactivating the window.
        if event.reason() == Qt.FocusReason.MouseFocusReason:
            QTimer.singleShot(0, self._show_ime_if_hidden)

    def event(self, event) -> bool:
        """A key a priority action answers is the action's, not the text control's: Enter
        sends and Shift+Enter starts a line through their declared actions, as Textual's
        prompt bindings beat its text area. Declining the shortcut override lets the
        shortcut fire."""
        if event.type() == QEvent.Type.ShortcutOverride and self.composer.host.app.action_keys.claims(event):
            event.ignore()
            return True
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        offers = self.composer.offers
        key = event.key()
        # Offer navigation stays local — it's widget-scoped, not a declared action family.
        if offers.isVisible() and key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            offers.step(-1 if key == Qt.Key.Key_Up else 1)
            return
        if offers.isVisible() and key == Qt.Key.Key_Tab:
            offers.accept_current()
            return
        self._ensure_mode_attached()
        if (input_key := _qt_key_to_input(event)) is not None and self._editing_mode.send_key(self, *input_key):
            return
        super().keyPressEvent(event)

    def insertFromMimeData(self, source: QMimeData) -> None:  # type: ignore[override]
        """Route clipboard/dragged images through the composer's attachment path."""
        if not self.composer.paste_mime_data(source):
            super().insertFromMimeData(source)


class Composer(PromptSettingEffects, PromptComposer, MentionEditor, SubmitsContract, DismissibleContract, QWidget,
               metaclass=PyQtWidgetMeta):
    """A conversation's composer, Textual's prompt drawn natively: the offer list,
    the queue summary and delivery controls, the framed ``❯`` editor, then its info bar
    and what is still submitting, the last send's failure and your last message's delivery.

    `PromptComposer` (Textual's `Prompt`) owns the submission owner, queue answers, glyph and
    draft rejoin; message composers add `MessagePromptComposer`. This class makes the Qt calls.
    Enter sends (`SubmitAction`), as in the TUI. A touch keyboard's Enter is committed as a
    newline in a multi-line field, so the frame also carries a `SubmitAction.title` button whose
    tap runs `submit`: one send path, two triggers. The shared action families bind to it
    through `SubmitsContract` + `DismissibleContract`."""

    # The declared TextEntryMode key spellings each prompt action exposes drive the Qt
    # composer's QShortcuts. Keeping the composer method as the callback (not the action's
    # own .apply, which expects a Textual `PromptTextArea`) lets both backends consume the
    # same key declarations without Qt dragging Textual's PromptSubmission chassis. A kind
    # of composer adds the actions only it answers.
    action_methods: ClassVar[tuple[tuple[type[PromptAction | MessageAction], Callable[..., None]], ...]]

    def __init__(self, host: ComposerHost, renderer: QtLineRenderer, placeholder: str) -> None:
        super().__init__()
        self.host, self.renderer = host, renderer
        # The composer's area is its own surface (`area_tone`), as Textual's prompt area is.
        self.setObjectName("composer")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.given_placeholder = placeholder
        self.mention_candidates: tuple[MentionCandidate, ...] = ()
        self.commands: list[SlashCommand] = []
        self.ranking = SlashCommandResults(case_sensitive=False)
        self.dismissed_text = ""
        self.offers = OfferList(self)
        self.editor = ComposerEditor(self)
        self.editor.setPlaceholderText(self.input_placeholder())
        self.editor.textChanged.connect(self.refresh_offers)
        self.editor.cursorPositionChanged.connect(self.refresh_offers)
        self.editor.textChanged.connect(self.fit_height)
        self.editor.document().documentLayout().documentSizeChanged.connect(
            lambda _size: self._schedule_fit_height()
        )
        self.editor.textChanged.connect(self.refresh_glyph)
        self.editor.setFrameShape(QFrame.Shape.NoFrame)
        self.editor.setStyleSheet("QPlainTextEdit { background: transparent; border: none }")
        self.glyph = QLabel()
        self.frame = QFrame()
        self.frame.setObjectName("prompt-frame")
        self.frame_layout = frame_layout = QVBoxLayout(self.frame)
        frame_layout.setSpacing(UiGap.tight)
        self.editor_row = editor_row = QHBoxLayout()
        editor_row.setContentsMargins(0, 0, 0, 0)
        editor_row.setSpacing(UiGap.tight)
        editor_row.addWidget(self.glyph, 0, Qt.AlignmentFlag.AlignTop)
        editor_row.addWidget(self.editor, 1)
        self.button_box = QWidget(self.frame)
        self.button_row = QHBoxLayout(self.button_box)
        self.button_row.setContentsMargins(0, 0, 0, 0)
        self.button_row.setSpacing(UiGap.tight)
        self.button_row.addStretch(1)
        frame_layout.addLayout(editor_row)
        frame_layout.addWidget(self.button_box)
        self.info_bar = QtInfoBar(host, renderer, self)
        renderer.themed(self, self.paint_colours)
        # Textual's QueueSummary + DeliveryControls, reading the shared submissions owner.
        self.submitting = QtQueueSummary(self)
        self.submitting.setObjectName("composer-queue")
        self.delivery_controls = QtDeliveryControls(self)
        self.delivery_controls.setObjectName("composer-delivery")
        for line in (self.submitting, self.delivery_controls):
            line.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Textual's `QueueHint`: the info bar's held count while the delivery preview is off,
        # before the status line as Textual composes it.
        self.held = QtQueueHint(self)
        self.info_bar.layout().insertWidget(self.info_bar.layout().indexOf(self.info_bar.status), self.held)
        self.failure = self.line(FailureRole)
        self.send_button = QtPushButton("➤", self.button_box)
        self.send_button.setToolTip(SubmitAction.title)
        self.send_button.setAccessibleName(SubmitAction.title)
        self.send_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # tapping keeps the keyboard up
        self.send_button.clicked.connect(self.submit)
        # Reusable single-shot timers avoid per-call PySide QMetaObject::normalizedSignature
        # allocations from QTimer.singleShot(0, self, slot).
        self._fit_height_timer = QTimer(self)
        self._fit_height_timer.setSingleShot(True)
        self._fit_height_timer.setInterval(0)
        self._fit_height_timer.timeout.connect(self._run_scheduled_fit_height)
        self._sync_queue_timer = QTimer(self)
        self._sync_queue_timer.setSingleShot(True)
        self._sync_queue_timer.setInterval(0)
        self._sync_queue_timer.timeout.connect(self._sync_queue)
        self._last_queue_state: tuple[str, bool, str] | None = None
        # The top-level window is the shared layout viewport. Android can keep that native
        # window at the physical screen size while occluding its bottom with the IME, even
        # under ADJUST_RESIZE, so the input method's own rectangle is the authority for the
        # visible part. Follow both facts: desktop resize (via QtToadApp.resizeEvent /
        # fit_safe_area -> viewport_geometry_changed) and Android keyboard geometry.
        self._viewport_window = host.app
        self._last_frame_width: int = 0
        self._input_method = QGuiApplication.inputMethod()
        self._input_method.keyboardRectangleChanged.connect(
            self._schedule_fit_height, Qt.ConnectionType.QueuedConnection
        )
        self._input_method.visibleChanged.connect(
            self._schedule_fit_height, Qt.ConnectionType.QueuedConnection
        )
        # Compact symbol buttons dock bottom-right beside `self.editor` in `editor_row`,
        # so the editor grows strictly by wrapped line count with zero blank line and zero
        # expand/collapse bounce when adding or removing characters.
        self.frame_row = frame_row = QHBoxLayout()
        frame_row.setSpacing(0)
        frame_row.addWidget(self.frame, 1)
        self.add_box_button(self.send_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # Textual's compose order: completions, delivery controls, the prompt container,
        # its info bar (`widgets/prompt.py` `Prompt.compose`).
        layout.addWidget(self.offers)
        layout.addWidget(self.submitting)
        layout.addWidget(self.delivery_controls)
        layout.addLayout(frame_row)
        layout.addWidget(self.info_bar)
        layout.addWidget(self.failure)
        # The declared prompt-action keys as QShortcuts: Enter, Ctrl+Enter, Shift+Enter, Escape.
        self._shortcuts = _bind_composer_shortcuts(self)
        self.place_input_box()
        self._frame_ready = True
        self.refresh_glyph()
        self.fit_height()
        self.sync_queue()

    @property
    def settings(self):
        """The settings of the view this composer sits in: its override, else the app's."""
        return self.host.configuration_state.fields

    def place_input_box(self) -> None:
        """The input box setting's room, in cells, as Textual's `PromptContainer` and
        `PromptLabel` read it: the frame's margin and padding, the label's padding, and a
        border only where the box draws one."""
        box = self.settings.ui.input.box
        metrics = self.fontMetrics()
        cell, line = metrics.averageCharWidth(), metrics.lineSpacing()

        def cells(spacing):
            return spacing.left * cell, spacing.top * line, spacing.right * cell, spacing.bottom * line

        self.frame_row.setContentsMargins(*cells(box.frame_margin))
        # The editor spans the full frame width above a compact bottom-right action strip
        # (`button_box`), so wrapped lines have zero dead space above `+`/`➤` and adding or
        # removing characters never bounces composer height.
        left, top, right, bottom = cells(box.frame_padding)
        room = max(4, round(line * 0.45))
        self.frame.layout().setContentsMargins(left, top + room, right, bottom + max(2, room // 2))
        left, top, right, bottom = cells(box.label_padding)
        # The glyph's text sits on the editor's first line, below the document's own margin.
        self.glyph.setContentsMargins(left, top + self.document_margin(), right, bottom)
        self.focus_changed(self.editor.hasFocus())
        self.fit_buttons()
        self.fit_height()

    def one_line_box_height(self) -> int:
        """The input box's height holding one line: one editor line above the docked action
        strip, plus the box's padding and border."""
        padding = self.frame.layout().contentsMargins()
        border = self.settings.ui.input.box.qt_border_pixels
        btn_h = max((button.height() for button in self.box_buttons if not button.isHidden()), default=0)
        strip_h = (btn_h + UiGap.tight) if btn_h else 0
        return self.editor_height(1) + strip_h + padding.top() + padding.bottom() + border

    def add_box_button(self, button: QPushButton) -> None:
        """Dock a compact symbol button in the bottom-right strip under `self.editor` (Send
        last, Attach before it)."""
        button.setParent(self.button_box)
        # Send is added first and stays last; every later button goes before it.
        if self.box_buttons:
            self.box_buttons = (*self.box_buttons[:-1], button, *self.box_buttons[-1:])
            self.button_row.insertWidget(self.button_row.count() - 1, button, 0, Qt.AlignmentFlag.AlignBottom)
        else:
            self.box_buttons = (button,)
            self.button_row.addWidget(button, 0, Qt.AlignmentFlag.AlignBottom)
        self.fit_buttons()
        self.fit_height()

    box_buttons: tuple[QPushButton, ...] = ()

    def fit_buttons(self) -> None:
        """Compact square symbol buttons matching one line of the editor."""
        line = self.fontMetrics().lineSpacing()
        height = max(18, line + max(4, round(line * 0.3)))
        width = height + max(2, round(line * 0.2))
        radius = max(3, round(height * 0.2))
        pad_x = max(2, round(line * 0.2))
        for button in self.box_buttons:
            font = QFont(self.font())
            font.setPointSizeF(font.pointSizeF() * 1.15 if font.pointSizeF() > 0 else 13.0)
            button.setFont(font)
            button.setStyleSheet(f"QPushButton {{ padding: 0px {pad_x}px; border-radius: {radius}px; }}")
            button.setFixedSize(width, height)

    def update_prompt(self) -> None:
        """A leading symbol or the placeholder setting changed: draw both again."""
        self.refresh_glyph()
        self.editor.setPlaceholderText(self.input_placeholder())

    def input_placeholder(self) -> str:
        """What the empty editor shows: the placeholder this composer's kind gave it."""
        return self.given_placeholder

    @property
    def submissions(self) -> BusSubmissions:
        return self.host.submissions

    def paint_colours(self) -> None:
        """The area's tone, inherited text/placeholder ink, the offer list, the glyph and
        the frame's border, under the renderer's current scheme."""
        # The area, the band its delivery and queue lines sit on, and the field typed into: the
        # shared composer's tones (Textual paints the same ones through TonePaint).
        queue = self.renderer.theme(self.queue_tone)
        self.renderer.apply_sheet(
            self,
            f"#composer {{ background: {self.renderer.theme(self.area_tone)} }}"
            f" #composer-queue, #composer-delivery {{ background: {queue} }}",
        )
        fg = self.renderer.theme(self.text_colour)
        placeholder = self.renderer.theme(self.placeholder_colour)
        # Qt's QStyleSheetStyle ignores QPalette.PlaceholderText once a stylesheet is set on
        # QPlainTextEdit, falling back to black; declare placeholder-text-color in QSS too.
        self.renderer.apply_sheet(
            self.editor,
            f"QPlainTextEdit {{ background: transparent; border: none;"
            f" color: {fg}; placeholder-text-color: {placeholder}; }}",
        )
        palette = self.editor.palette()
        palette.setColor(QPalette.ColorRole.Text, QColor(fg))
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(placeholder))
        self.editor.setPalette(palette)
        self.renderer.apply_sheet(
            self.offers,
            self.host.app.theme.color_scheme.styles.generate_list_widget_style(),
        )
        self.renderer.apply_sheet(self.glyph, f"color: {self.renderer.theme(SecondaryColour)}")
        self.focus_changed(self.editor.hasFocus())

    def focus_changed(self, focused: bool) -> None:
        """The frame's border follows focus (Textual's `PromptContainer.border`), and the
        badge and cursor shape follow the active editing mode."""
        colour = self.renderer.theme(PrimaryColour if focused else MutedColour)
        field = self.renderer.theme(self.input_tone)
        self.renderer.apply_sheet(self.frame, self.settings.ui.input.box.qt_frame_sheet(field, colour))
        self.editor.sync_cursor_shape()
        self.info_bar.badge.present_editing_mode(self.editor.editing_mode, focused)

    def refresh_editing_mode(self) -> None:
        self.editor.sync_cursor_shape()
        self.info_bar.badge.present_editing_mode(self.editor.editing_mode, self.editor.hasFocus())
        RowReveal.toggle(self.delivery_controls, self.shows_delivery_controls, self)

    @property
    def offers_send_now(self) -> bool:
        """Textual's `SubmitNowAction.available`: the editor takes text (vim Normal does not)
        with no offer list open (`PromptTextArea.submission_allowed`), and the shared answer."""
        return (self.editor.editing_mode.accepts_text and not self.offers.isVisible()
                and super().offers_send_now)

    def refresh_glyph(self) -> None:
        self.glyph.setText(self.prompt_symbol(self.text, False))

    def show_status(self, status) -> None:
        self.info_bar.status.present_status(status)

    def line(self, role: type[LineRole]) -> WrappedText:
        label = WrappedText()
        self.renderer.themed(label, lambda: label.setStyleSheet(self.renderer.color_style(role)))
        label.setContentsMargins(UiGap.frame, 0, UiGap.frame, 0)
        label.hide()
        return label

    def fit_height(self) -> None:
        """Grow strictly by visual line count under the shared viewport limit, then scroll inside
        the editor. Because `+` / `➤` sit beside the editor in `editor_row`, text never collides
        with them and adding/removing characters never bounces composer height."""
        # QPlainTextDocumentLayout's height is the visual line count.  ``blockCount`` is
        # only the number of explicit newlines, so one long phone-width paragraph stayed a
        # one-line editor while Qt wrapped five lines of text underneath it.
        typed = self.editor.visual_line_count()
        line_spacing = self.editor.fontMetrics().lineSpacing()
        doc_margin = self.document_margin()
        viewport_h = self.visible_viewport_height()
        lines = self.visible_editor_lines(typed, viewport_h, line_spacing, 2 * doc_margin)
        self.editor.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if typed > lines else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.editor.setFixedHeight(self.editor_height(lines))
        if typed <= lines:
            # QPlainTextEdit scrolls down to line 1 while wrapping at 1-line height before
            # `fit_height` grows it; resetting to 0 brings line 0 back into view.
            self.editor.verticalScrollBar().setValue(0)

    def visible_viewport_height(self) -> int:
        """The window height not hidden by safe-area margins or the platform input method.

        On Android 15, ``ToadActivity`` folds ``WindowInsets.Type.ime()`` into
        ``safeAreaMarginsChanged`` (applied as ``contentsMargins`` on the top-level window),
        so ``contentsRect().height()`` already excludes the keyboard and status bar without
        resizing the EGL surface. Taking the smaller of ``contentsRect().height()`` and
        ``rect().height() - keyboardRectangle`` avoids double-subtracting while still
        respecting ``QInputMethod.keyboardRectangle()`` on older Android and tests.
        """
        viewport = self._viewport_window.rect()
        covered = (
            viewport.intersected(self._input_method.keyboardRectangle().toRect()).height()
            if self._input_method.isVisible()
            else 0
        )
        return max(1, min(self._viewport_window.contentsRect().height(), viewport.height() - covered))

    _fit_height_pending: bool = False

    @Slot()
    def _schedule_fit_height(self) -> None:
        """Defer editor resize off QAndroidInputContext::runOnQtThread() and top-level resize.

        On Qt-for-Android, QInputMethod emits keyboardRectangleChanged and visibleChanged
        synchronously while QAndroidInputContext::runOnQtThread() holds the platform deadlock
        protector; resizing the editor inline flushes the backing store into
        QAndroidPlatformOpenGLWindow::eglSurface() and SIGABRTs. Queued delivery plus a
        coalesced zero-delay tick on `self` lets the IME hook unwind first and skips
        destroyed composers.
        """
        if not self._fit_height_pending:
            self._fit_height_pending = True
            self._fit_height_timer.start()

    def _run_scheduled_fit_height(self) -> None:
        self._fit_height_pending = False
        self.fit_height()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        width = self.frame.width()
        if width != self._last_frame_width:
            self._last_frame_width = width
            self._schedule_fit_height()

    _frame_ready: bool = False

    def changeEvent(self, event: QEvent) -> None:  # type: ignore[override]
        """Refit box margins, floating buttons and height when the app text scale changes."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange and self._frame_ready:
            self.place_input_box()

    TOUCH_ROOM: ClassVar[int] = 16
    """Room the box adds around its text for a finger, split evenly above and below."""

    def document_margin(self) -> int:
        return round(self.editor.document().documentMargin())

    def editor_height(self, lines: int) -> int:
        """The editor's height showing `lines` lines: the lines and the document's margins."""
        return self.editor.fontMetrics().lineSpacing() * lines + 2 * self.document_margin()

    @property
    def text(self) -> str:
        return self.editor.toPlainText()

    # Offers

    def mention_candidates_changed(self) -> None:
        self.refresh_offers()

    def set_commands(self, commands: list[SlashCommand]) -> None:
        self.commands = commands
        self.refresh_offers()

    def typing_command(self) -> bool:
        """The message is still its first word and that word starts a command, as Textual's
        slash completion opens on a leading /."""
        text = self.text
        return text.startswith("/") and not any(character.isspace() for character in text)

    def refresh_offers(self) -> None:
        cursor = self.editor.textCursor()
        if cursor.hasSelection() or self.text == self.dismissed_text:
            self.offers.show_offers("", ())
        elif self.typing_command():
            if not self.commands:
                self.host.update_slash_commands()
            self.offers.show_offers("Slash commands", tuple(
                CommandOffer(match) for match in self.ranking.ranked(self.text, self.commands)))
        else:
            block = cursor.block()
            mention = MentionCompletion.at_cursor(block.text(), block.blockNumber(), cursor.positionInBlock())
            self.offers.show_offers(MentionCompletion.title, tuple(
                MentionOffer(mention, candidate) for candidate in mention.options(self.mention_candidates)))

    def dismiss(self) -> None:
        self.dismissed_text = self.text
        self.offers.show_offers("", ())

    def replace_span(self, row: int, start: int, end: int, text: str) -> None:
        self.editor.editing_mode.replace_span(self.editor, row, start, end, text)

    # Sending

    def send(self, action: SubmitInputAction = SubmitAction()) -> None:
        """Hand what is typed to the view with the action that sends it; the action owns
        the event it becomes, as Textual's `SubmitInputAction.submission_event` does."""
        text = self.text
        self.editor.clear()
        self.dismissed_text = ""
        self.failure.hide()
        self.host.submit(TypedText(text, self.take_files()), action)
        # The view listed the message in that call: draw its preview row with the cleared
        # editor, in one frame, rather than on the next turn.
        if self.queue_sync_pending:
            self._sync_queue()

    # Toolkit-neutral action-family contract: Textual's Prompt inherits Submits +
    # DismissibleControl from widget_actions.py; the mixin lift itself is fork
    # a28441d7743dc4abb's work. These methods expose the same contract on Qt so the
    # neutral family, once lifted, binds without changing this widget again.

    def submit(self) -> None:
        """What `SubmitAction` (Enter) calls: an empty prompt sends nothing."""
        if self.text.strip():
            self.send(SubmitAction())

    def submit_now(self) -> None:
        """What `SubmitNowAction` (Ctrl+Enter, Ctrl+Y) calls: the typed text, or with an
        empty prompt the held queue, is sent ahead (`UserInputSubmitted(immediate=True)`;
        the backend's `QueueNowInputSubmission` flushes an empty immediate submit)."""
        if self.offers_send_now:
            self.send(SubmitNowAction())

    def _insert_newline(self) -> None:
        """What `NewlineAction` (Shift+Enter, Ctrl+J) calls — a real `\\n`, not a submit."""
        self.editor.editing_mode.insert_text(self.editor, "\n")

    def paste_clipboard(self) -> None:
        """What `PasteClipboardAction` (Ctrl+V) calls in Standard, Vim Insert, and Vim Normal:
        attaches a clipboard image as PNG or inserts clipboard text at the cursor."""
        if self.editor.isReadOnly():
            return
        clipboard = QApplication.clipboard()
        if not self.paste_mime_data(clipboard.mimeData()):
            image = clipboard.image()
            if not image.isNull():
                self._paste_qimage(image)
                return
            text = clipboard.text()
            if text:
                self.editor.editing_mode.insert_text(self.editor, text)

    def paste_mime_data(self, mime: QMimeData | None) -> bool:
        """Handle image or text MIME data; return True when handled."""
        if mime is None or self.editor.isReadOnly():
            return False
        if mime.hasImage():
            data = mime.imageData()
            image = data if isinstance(data, QImage) else QImage(data)
            if not image.isNull():
                self._paste_qimage(image)
                return True
        if mime.hasText():
            text = mime.text()
            if text:
                self.editor.editing_mode.insert_text(self.editor, text)
                return True
        return False

    def _paste_qimage(self, image: QImage) -> None:
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            self.show_failure("Could not encode clipboard image as PNG.")
            return
        png_bytes = bytes(buffer.data())
        if png_bytes:
            self.attach_pasted_png(png_bytes)

    def attach_pasted_png(self, data: bytes) -> None:
        """What a pasted PNG does on a non-file composer: save locally and insert `@path`,
        matching Textual's `Prompt.png_pasted`."""
        try:
            path = save_clipboard_png(data)
        except (OSError, ValueError) as error:
            self.show_failure(f"Paste failed: {error}")
            return
        reference = f'@"{path}"' if any(char.isspace() for char in str(path)) else f"@{path}"
        self.editor.editing_mode.insert_text(self.editor, f" {reference} ")

    def dismiss_control(self) -> None:
        """What `DismissAction` calls — hide completion offers, or hand Escape to the active
        `KeyMode` (`Standard` leaves the composer; `NeovimEditing` sends `<Esc>` to Neovim so
        Insert/Visual returns to Normal and idle Normal triggers `StandardEditingAction`)."""
        if self.offers.isVisible():
            self.dismiss()
            return
        self.editor.editing_mode.dismiss_input(self.editor)

    def append_to_draft(self, suffix: str) -> None:
        self.editor.editing_mode.move_to_end(self.editor)
        self.editor.editing_mode.insert_text(self.editor, suffix)

    def show_failure(self, text: str) -> None:
        self.failure.setText(text)
        self.failure.show()

    queue_sync_pending: bool = False

    def sync_queue(self) -> None:
        """The queue summary, the delivery controls and the held count from the shared
        submissions, as Textual's ``Prompt.sync_queue`` shows them; once per event-loop turn,
        however many changes the turn reports (a send publishes several, and every
        notification read reports the queue again)."""
        if not self.queue_sync_pending:
            self.queue_sync_pending = True
            self._sync_queue_timer.start()

    def _sync_queue(self) -> None:
        self.queue_sync_pending = False
        state = (self.queue_summary, self.shows_delivery_controls, self.queue_hint)
        if state == self._last_queue_state:
            return
        self._last_queue_state = state
        summary, controls, hint = state
        self.submitting.refresh(summary)
        RowReveal.toggle(self.delivery_controls, controls, self)
        self.held.refresh(hint)
        self.info_bar.sync_visibility()

    def open_queue_menu(self) -> None:
        """Textual's ``Conversation.open_queue_menu`` pushes the ``QueueInspection``
        screen; Qt opens the same shape as a modal dialog over the composer. The
        inspection reads ``queue_evidence`` from the shared submissions owner — if
        that isn't wired yet (Qt still on base ``BusSubmissions``), the dialog says
        so instead of crashing."""
        submissions = self.host.submissions
        dialog = QtQueueInspection(submissions, self.renderer, parent=self)
        dialog.open()

    def hold(self, reason: str) -> None:
        """A read-only view holds compose and says why; an empty reason opens it."""
        self.editor.setReadOnly(bool(reason))
        self.editor.setToolTip(reason)

    def labelled(self, label: str) -> None:
        """The view's label changed; a channel's composer keeps the placeholder its kind gave it."""

    # ---- RebindableComposer: freeze draft on detach and rebind to another tab ----

    def pool_alive(self) -> bool:
        return shiboken6.isValid(self)

    def capture_composer_draft(self) -> ComposerDraft:
        self.offers.show_offers("", ())
        return ComposerDraft(
            text=self.editor.toPlainText(),
            cursor_offset=self.editor.textCursor().position(),
            placeholder=self.given_placeholder,
            read_only_reason=self.editor.toolTip() if self.editor.isReadOnly() else "",
            failure_text=self.failure.text() if not self.failure.isHidden() else "",
            mention_candidates=self.mention_candidates,
            commands=tuple(self.commands),
            dismissed_text=self.dismissed_text,
        )

    def rebind_toolkit_conversation(self, host: ComposerPoolHost, draft: ComposerDraft) -> None:
        self.host = host
        self.info_bar.configuration_scope = host
        self.info_bar.status.configuration_scope = host
        self._last_queue_state = None
        self.given_placeholder = draft.placeholder or host.composer_placeholder
        self.mention_candidates = draft.mention_candidates
        self.commands = list(draft.commands)
        self.dismissed_text = draft.dismissed_text
        self.offers.show_offers("", ())
        self.editor.blockSignals(True)
        try:
            self.editor.setPlainText(draft.text)
            cursor = self.editor.textCursor()
            cursor.setPosition(min(draft.cursor_offset, len(draft.text)))
            self.editor.setTextCursor(cursor)
        finally:
            self.editor.blockSignals(False)
        self.hold(draft.read_only_reason)
        if draft.failure_text:
            self.show_failure(draft.failure_text)
        else:
            self.failure.setText("")
            self.failure.hide()
        self.place_input_box()

    def after_rebind_conversation(self) -> None:
        self.fit_height()


Composer.action_methods = (
    (SubmitAction, Composer.submit),
    (SubmitNowAction, Composer.submit_now),
    (DismissAction, Composer.dismiss_control),
    (NewlineAction, Composer._insert_newline),
    (PasteClipboardAction, Composer.paste_clipboard),
)


class QtAttachedFileChip(AttachedFileChip, QtPushButton):
    """An attached file as a button over the editor; tapping it takes the file off."""

    def __init__(self, composer: QtMessageComposer, position: int) -> None:
        super().__init__(composer.attached_chips_host)
        self.show_file(composer, position)
        self.setText(f"{self.caption}  ✕")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("Remove this file")
        self.clicked.connect(self.take_off)


class QtCompressImagesButton(ImageCompressionControl, QtPushButton):
    """One-tap button over the composer to shrink attached images before sending."""

    def __init__(self, composer: QtMessageComposer) -> None:
        super().__init__(composer.attached_row)
        self.bind_compression(composer)
        self.setText(self.compress_caption)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("Downscale and JPEG-compress attached images")
        self.clicked.connect(self.compress_images)


class QtMessageComposer(MessagePromptComposer, Composer):
    """A bus message's composer on Qt: the shared message composer, an Attach button beside
    Send, the attached files as scrollable chips with an image-compression control over the
    editor, and Qt's two pickers."""

    action_methods = (*Composer.action_methods, (AttachFileAction, MessagePromptComposer.attach_file))

    def __init__(self, host: ComposerHost, renderer: QtLineRenderer, placeholder: str) -> None:
        super().__init__(host, renderer, placeholder)
        self.attach_button = QtPushButton("+", self.button_box)
        self.attach_button.setToolTip(AttachFileAction.title)
        self.attach_button.setAccessibleName(AttachFileAction.title)
        self.attach_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # tapping keeps the keyboard up
        self.attach_button.clicked.connect(self.attach_file)
        self.add_box_button(self.attach_button)
        self.attached_row = QWidget(self)
        row_layout = QHBoxLayout(self.attached_row)
        row_layout.setContentsMargins(UiGap.frame, 0, UiGap.frame, 0)
        row_layout.setSpacing(UiGap.tight)
        self.attached_scroll = QScrollArea(self.attached_row)
        self.attached_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.attached_scroll.setWidgetResizable(True)
        self.attached_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.attached_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.attached_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.attached_chips_host = QWidget(self.attached_scroll)
        self.attached_chips = QHBoxLayout(self.attached_chips_host)
        self.attached_chips.setContentsMargins(0, 0, 0, 0)
        self.attached_chips.setSpacing(UiGap.tight)
        self.attached_chips.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.attached_scroll.setWidget(self.attached_chips_host)
        self.compress_button: QtCompressImagesButton | None = None
        row_layout.addWidget(self.attached_scroll, 1)
        layout = self.layout()
        layout.insertWidget(layout.indexOf(self.frame_row), self.attached_row)
        self.attached_row.hide()

    def submit(self) -> None:
        """Allow sending attached files with or without accompanying text."""
        if self.text.strip() or self.attached_files:
            self.send(SubmitAction())

    def attach_pasted_png(self, data: bytes) -> None:
        """Attach a pasted PNG directly through the shared `MessagePromptComposer` owner."""
        self.attach_png_bytes(data)

    def compress_image(self, upload: FileUpload) -> FileUpload | None:
        compressed = compress_image_bytes(upload.name, upload.mime_type, upload.content)
        if compressed is None:
            return None
        new_name, new_mime, new_bytes = compressed
        return FileUpload.of(new_name, new_mime, new_bytes)

    def show_compression_summary(self, text: str) -> None:
        self.host.app.show_info(text)

    def pick_in_window(self) -> None:
        open_file_dialog(self, self)

    def pick_by_path_search(self) -> None:
        open_path_search(self, self, self.host.app.project_dir.path, self.host.app.run_operation)

    def show_files_offered(self) -> None:
        self.attach_button.setVisible(self.takes_files)

    def show_attached(self) -> None:
        delete_layout_widgets(self.attached_chips)
        row_layout = self.attached_row.layout()
        if self.compress_button is not None:
            row_layout.removeWidget(self.compress_button)
            self.compress_button.hide()
            self.compress_button.deleteLater()
            self.compress_button = None
        chip_height = 0
        for position in range(len(self.attached_files)):
            chip = QtAttachedFileChip(self, position)
            chip_height = max(chip_height, chip.sizeHint().height())
            self.attached_chips.addWidget(chip)
        if self.has_compressible_images:
            self.compress_button = QtCompressImagesButton(self)
            chip_height = max(chip_height, self.compress_button.sizeHint().height())
            row_layout.addWidget(self.compress_button, 0)
        if chip_height > 0:
            self.attached_scroll.setFixedHeight(chip_height + 2)
        self.attached_row.setVisible(bool(self.attached_files))


class ChannelComposer(QtMessageComposer):
    """A channel's composer, which offers its members after an @."""


class MessageComposer(QtMessageComposer):
    """A direct message's composer: it names its peer, as Textual's MessagePrompt does."""

    def __init__(self, host: ComposerHost, renderer: QtLineRenderer) -> None:
        self.label = ""
        super().__init__(host, renderer, "")

    def labelled(self, label: str) -> None:
        self.label = label
        self.editor.setPlaceholderText(self.input_placeholder())

    def input_placeholder(self) -> str:
        """Textual's `MessagePrompt`: the peer it messages."""
        return f"Message {self.label or 'thread'}"

    def capture_composer_draft(self) -> ComposerDraft:
        return replace(super().capture_composer_draft(), label=self.label)

    def rebind_conversation(self, host: ComposerPoolHost, draft: ComposerDraft) -> None:
        super().rebind_conversation(host, draft)
        self.labelled(draft.label)


class ProjectComposer(Composer):
    """Textual's `Prompt`: input waits on the agent; the info bar shows `PromptPath`."""

    def __init__(self, host: ComposerHost, renderer: QtLineRenderer, placeholder: str = "") -> None:
        super().__init__(host, renderer, placeholder)
        self.info_bar.show_path(home_relative(str(host.project.path)))

    def input_placeholder(self) -> str:
        """Textual's `Prompt`: the kind's own placeholder, else `ui.input.placeholder`."""
        return self.given_placeholder or self.settings.ui.input.placeholder

    def rebind_conversation(self, host: ComposerPoolHost, draft: ComposerDraft) -> None:
        super().rebind_conversation(host, draft)
        self.info_bar.show_path(home_relative(str(host.project.path)))


class MailboxComposer(MessageComposer, ProjectComposer):
    """A CLI thread's composer, Textual's `MailboxPrompt(MessagePrompt)`, with its project path."""
