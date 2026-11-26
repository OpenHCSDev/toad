"""The conversation composer on Qt: Textual's message prompt drawn natively. What it offers
after an @ or a /, what accepting an offer writes, and where a typed message goes all come
from the shared owners (MentionCompletion, SlashCommandResults over the CommandCatalog,
BusSubmissions); this module draws them and reads the keys."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from math import ceil
from typing import ClassVar

from agent_comms.messaging.mentions import MentionCandidate
from agent_comms.messaging.message_reference import MessageReference
from agent_comms.messaging.notification_reads import LiveNotificationRead
from agent_comms.messaging.read_basis import DisplayIdentity, NoDisplaySelection
from agent_comms.ui_model.observation import ReadNotifications
from PySide6.QtCore import QEvent, Qt, QTimer, Slot
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeyEvent, QPalette, QTextCursor
from pyqt_reactive.widgets.shared.list_item_delegate import LAYOUT_ROLE, MultilinePreviewItemDelegate
from pyqt_reactive.widgets.shared.styled_text_layout import Segment, StyledTextLayout
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from pyqt_reactive.widgets.fitted_text import ElidedLine, WrappedText

from toad.client.application import ClientApplication
from toad.client.bus_submission import BusSubmissions, TypedText
from toad.client.commands import ConversationCommands
from toad.client.line_blocks import FailureRole, LineRole, MutedRole
from toad.client.mention_completion import MentionCompletion, MentionEditor
from toad.client.message_files import AttachedFileChip, MessagePromptComposer
from toad.client.prompt_composer import (
    ComposerOffer,
    MentionCandidateOffer,
    PromptComposer,
    PromptSettingEffects,
    SlashCommandOffer,
)
from toad.client.condensed_path import home_relative
from toad.key_modes import Standard, VimInsert
from pyqt_reactive.protocols.widget_adapters import PyQtWidgetMeta
from ui_theme.scheme import MutedColour, PrimaryColour, SecondaryColour
from toad.client.notification_status import (
    CheckedNotifications,
    NotificationStatus,
    UnavailableNotifications,
    UncheckedNotifications,
)
from toad.client.subscribers import NotificationSubscriber
from toad.prompt_actions import (
    AttachFileAction,
    MessageAction,
    NewlineAction,
    PromptAction,
    SubmitAction,
    SubmitInputAction,
    SubmitNowAction,
)
from toad.widget_actions import DismissAction
from toad.widget_contracts import (
    DismissibleContract,
    OpensSelectedContract,
    SelectsContract,
    SubmitsContract,
)
from toad.qt.composer_vim import ComposerVimMode, apply_normal_key
from toad.qt.file_pickers import open_file_dialog, open_path_search
from toad.qt.lines import QtLineRenderer
from toad.qt.queue_ui import QtDeliveryControls, QtQueueHint, QtQueueInspection, QtQueueSummary, RowReveal
from toad.qt.prompt_stack import QtInfoBar
from toad.slash_command import SlashCommand
from toad.slash_command_results import CommandMatch, SlashCommandResults
from toad.qt.metrics import UiGap, delete_layout_widgets


def _bind_composer_shortcuts(composer: Composer):
    """One `QShortcut` per composer action on the editor, answering the action's keys in
    the current key mode and keymap (`ActionKeys`) and running the composer's own method
    while the editor (or a child) has focus. Textual reaches these methods through its own
    PromptTextArea action system — the keys live in one place."""
    return [composer.host.app.action_keys.bind(composer.editor, action_cls(), method.__get__(composer))
            for action_cls, method in composer.action_methods]


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
        composer.editor.moveCursor(QTextCursor.MoveOperation.End)


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


class ComposerEditor(QPlainTextEdit):
    """The message being typed. Enter and Ctrl+Enter send, Shift+Enter starts a line; while
    offers are shown, Up and Down move through them and Enter or Tab takes one, Escape
    hides them. Escape with no offers visible dismisses the control (clears the draft and
    blurs the editor), mirroring Textual's DismissAction on a Prompt."""

    def __init__(self, composer: Composer) -> None:
        super().__init__()
        self.composer = composer
        self.setTabChangesFocus(False)
        # Android soft-keyboard wiring: without these the tap registers but the IME
        # never raises, so the user sees a composer they can't type into. Desktop Qt
        # raises the OS keyboard implicitly on focus; Android Qt doesn't — the editor
        # has to opt in explicitly. Three pieces: (1) StrongFocus so a tap can take
        # keyboard focus, (2) WA_InputMethodEnabled so the IME considers the widget,
        # (3) mousePressEvent explicitly requests the IME show on tap (focusInEvent
        # alone fires too early on Android, before the window is composited).
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.follow_key_mode()

    def visual_line_count(self) -> int:
        """Lines Qt actually laid out, including soft wraps inside one text block."""
        return max(1, ceil(self.document().size().height()))

    def follow_key_mode(self) -> None:
        """Modal input follows `ui.key_mode`, the setting Textual's prompt reads: a modal key
        mode (vim_normal, vim_insert) puts the editor in its mode, at start and whenever the
        setting changes."""
        key_mode = self.composer.settings.ui.key_mode
        self.vim_enabled = key_mode.modal
        self.vim = ComposerVimMode(key_mode if key_mode.modal else VimInsert)

    @property
    def editing_mode(self):
        """What the info bar's badge names: the modal state, else the standard mode."""
        return self.vim if self.vim_enabled else Standard()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.composer.focus_changed(False)

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        # Defer the IME show() to the next event-loop tick. Firing inline inside
        # mousePressEvent reaches into Android's native IME path which recurses
        # into QAndroidPlatformOpenGLWindow::eglSurface() while the Qt event
        # dispatch still owns the surface — the platform plugin's deadlock
        # protector then SIGABRTs the app. Same class as #1885, #1901, #1911,
        # #1939 EGL fixes. QTimer.singleShot(0) runs after the current event
        # unwinds, breaking the recursion.
        QTimer.singleShot(0, QGuiApplication.inputMethod().show)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.composer.focus_changed(True)
        # Same defer as mousePressEvent — focusInEvent also runs inside Qt's
        # event-dispatch path on Android.
        QTimer.singleShot(0, QGuiApplication.inputMethod().show)

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
        # Vim NORMAL mode intercepts navigation/edit commands before the standard
        # composer bindings; Enter + Ctrl+Enter are owned by SubmitAction/SubmitNowAction
        # on the composer and fire through QShortcut regardless.
        offers = self.composer.offers
        key = event.key()
        if (self.vim_enabled and not self.vim.accepts_text
                and not offers.isVisible() and key != Qt.Key.Key_Escape):
            apply_normal_key(self, self.vim, event)
            self.composer.refresh_editing_mode()
            return
        # Offer navigation stays local — it's widget-scoped, not a declared action family.
        if offers.isVisible() and key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            offers.step(-1 if key == Qt.Key.Key_Up else 1)
            return
        if offers.isVisible() and key == Qt.Key.Key_Tab:
            offers.accept_current()
            return
        # Enter / Ctrl+Enter / Ctrl+Y / Shift+Enter / Escape are all bound as
        # QShortcuts on Composer via `ActionKeys.bind_family`; they read the declared
        # keys off `SubmitAction`/`SubmitNowAction`/`NewlineAction`/`DismissAction`
        # so the Qt editor and Textual's PromptTextArea share a single source of
        # truth. SubmitNowAction already declares `ctrl+enter` + `ctrl+y`; the
        # composer routes it through `submit_now` which flushes the queue when input
        # is held.
        super().keyPressEvent(event)


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
        self.editor_row = editor_row = QHBoxLayout(self.frame)
        editor_row.setSpacing(UiGap.tight)
        editor_row.addWidget(self.glyph, 0, Qt.AlignmentFlag.AlignTop)
        editor_row.addWidget(self.editor, 1)
        self.info_bar = QtInfoBar(host, renderer, self)
        self.receipt = Receipt(host.app, renderer, self.info_bar)
        self.info_bar.layout().insertWidget(0, self.receipt, 1, Qt.AlignmentFlag.AlignVCenter)
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
        self.send_button = QPushButton("➤", self.frame)
        self.send_button.setToolTip(SubmitAction.title)
        self.send_button.setAccessibleName(SubmitAction.title)
        self.send_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # tapping keeps the keyboard up
        self.send_button.clicked.connect(self.submit)
        # Compact symbol buttons sit on the right side of `editor_row` inside `self.frame`,
        # aligned to the editor's bottom edge so Android's soft keyboard never clips them.
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
        # The top-level window is the shared layout viewport. Android can keep that native
        # window at the physical screen size while occluding its bottom with the IME, even
        # under ADJUST_RESIZE, so the input method's own rectangle is the authority for the
        # visible part. Follow both facts: desktop resize and Android keyboard geometry.
        self._viewport_window = host.app
        self._viewport_window.installEventFilter(self)
        self._input_method = QGuiApplication.inputMethod()
        self._input_method.keyboardRectangleChanged.connect(
            self._schedule_fit_height, Qt.ConnectionType.QueuedConnection
        )
        self._input_method.visibleChanged.connect(
            self._schedule_fit_height, Qt.ConnectionType.QueuedConnection
        )
        self.place_input_box()
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
        # The box's touch room sits evenly above and below the text, so one line is centred in
        # the box as Textual's prompt is; the editor itself is exactly its lines' height.
        left, top, right, bottom = cells(box.frame_padding)
        room = self.TOUCH_ROOM // 2
        self.frame.layout().setContentsMargins(left, top + room, right, bottom + room)
        left, top, right, bottom = cells(box.label_padding)
        # The glyph's text sits on the editor's first line, below the document's own margin.
        self.glyph.setContentsMargins(left, top + self.document_margin(), right, bottom)
        self.focus_changed(self.editor.hasFocus())
        self.fit_buttons()

    def one_line_box_height(self) -> int:
        """The input box's height holding one line: the editor's one-line height, the box's
        padding, and its border where it draws one."""
        padding = self.frame.layout().contentsMargins()
        border = self.settings.ui.input.box.qt_border_pixels
        return self.editor_height(1) + padding.top() + padding.bottom() + border

    def add_box_button(self, button: QPushButton) -> None:
        """The one way a compact symbol button joins `editor_row` (Send last, Attach before it):
        staying on the editor's own row keeps Attach and Send visible above Android's keyboard."""
        button.setParent(self.frame)
        # Send is added first and stays last; every later button goes before it.
        self.editor_row.insertWidget(self.editor_row.count() - len(self.box_buttons),
                                     button, 0, Qt.AlignmentFlag.AlignBottom)
        self.box_buttons = (*self.box_buttons[:-1], button, *self.box_buttons[-1:]) \
            if self.box_buttons else (button,)
        self.fit_buttons()

    box_buttons: tuple[QPushButton, ...] = ()

    def fit_buttons(self) -> None:
        """Compact square symbol buttons matching one line of the editor."""
        height = max(28, self.fontMetrics().lineSpacing() + 6)
        width = height + 4
        for button in self.box_buttons:
            font = QFont(self.font())
            font.setPointSizeF(font.pointSizeF() * 1.15 if font.pointSizeF() > 0 else 13.0)
            button.setFont(font)
            button.setStyleSheet("QPushButton { padding: 0px 4px; border-radius: 6px; }")
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
        """The area's tone, the muted placeholder, the offer list, the glyph and the frame's
        border, under the renderer's current scheme."""
        # The area, the band its delivery and queue lines sit on, and the field typed into: the
        # shared composer's three tones (Textual paints the same ones through TonePaint).
        queue = self.renderer.theme(self.queue_tone)
        self.setStyleSheet(
            f"#composer {{ background: {self.renderer.theme(self.area_tone)} }}"
            f" #composer-queue, #composer-delivery {{ background: {queue} }}")
        palette = self.editor.palette()
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(self.renderer.colour(MutedRole)))
        self.editor.setPalette(palette)
        self.offers.setStyleSheet(self.host.app.theme.color_scheme.styles.generate_list_widget_style())
        self.glyph.setStyleSheet(f"color: {self.renderer.theme(SecondaryColour)}")
        self.focus_changed(self.editor.hasFocus())

    def focus_changed(self, focused: bool) -> None:
        """The frame's border follows focus (Textual's `PromptContainer.border`), and the
        badge shows the editing mode only while focused."""
        colour = self.renderer.theme(PrimaryColour if focused else MutedColour)
        field = self.renderer.theme(self.input_tone)
        self.renderer.apply_sheet(self.frame, self.settings.ui.input.box.qt_frame_sheet(field, colour))
        self.info_bar.badge.present_editing_mode(self.editor.editing_mode, focused)

    def refresh_editing_mode(self) -> None:
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
        """Grow under the shared viewport limit, then scroll inside the editor."""
        # QPlainTextDocumentLayout's height is the visual line count.  ``blockCount`` is
        # only the number of explicit newlines, so one long phone-width paragraph stayed a
        # one-line editor while Qt wrapped five lines of text underneath it.
        typed = self.editor.visual_line_count()
        margin = 2 * self.document_margin()
        lines = self.visible_editor_lines(
            typed, self.visible_viewport_height(), self.editor.fontMetrics().lineSpacing(), margin
        )
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
            QTimer.singleShot(0, self, self._run_scheduled_fit_height)

    def _run_scheduled_fit_height(self) -> None:
        self._fit_height_pending = False
        self.fit_height()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if watched is self._viewport_window and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.ContentsRectChange,
        ):
            # Run after Qt has propagated the new top-level geometry or safe-area margins.
            self._schedule_fit_height()
        return super().eventFilter(watched, event)

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
        block = self.editor.document().findBlockByNumber(row)
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + start)
        cursor.setPosition(block.position() + end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text)
        self.editor.setTextCursor(cursor)

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
        self.editor.insertPlainText("\n")

    def dismiss_control(self) -> None:
        """What `DismissAction` calls — close the composer without sending.

        Owns the composer's Escape state machine so a single `DismissAction` binding
        does the right thing regardless of offer visibility or vim mode:
          * offers visible → hide them, keep the draft (same as Textual's SlashComplete
            dismiss);
          * vim INSERT with no offers → enter NORMAL instead of blurring;
          * else → clear the draft, hide offers, drop focus (Textual's `DismissAction`
            on a `Prompt`).
        """
        if self.offers.isVisible():
            self.dismiss()
            return
        if self.editor.vim_enabled and self.editor.vim.accepts_text:
            self.editor.vim.enter_normal()
            self.refresh_editing_mode()
            return
        self.editor.clear()
        self.dismissed_text = ""
        self.offers.show_offers("", ())
        self.editor.clearFocus()

    def append_to_draft(self, suffix: str) -> None:
        self.editor.moveCursor(QTextCursor.MoveOperation.End)
        self.editor.insertPlainText(suffix)

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
            QTimer.singleShot(0, self, self._sync_queue)

    def _sync_queue(self) -> None:
        self.queue_sync_pending = False
        self.submitting.refresh(self.queue_summary)
        RowReveal.toggle(self.delivery_controls, self.shows_delivery_controls, self)
        self.held.refresh(self.queue_hint)
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


Composer.action_methods = (
    (SubmitAction, Composer.submit),
    (SubmitNowAction, Composer.submit_now),
    (DismissAction, Composer.dismiss_control),
    (NewlineAction, Composer._insert_newline),
)


class QtAttachedFileChip(AttachedFileChip, QPushButton):
    """An attached file as a button over the editor; tapping it takes the file off."""

    def __init__(self, composer: QtMessageComposer, position: int) -> None:
        super().__init__(composer.attached_row)
        self.show_file(composer, position)
        self.setText(f"{self.caption}  ✕")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("Remove this file")
        self.clicked.connect(self.take_off)


class QtMessageComposer(MessagePromptComposer, Composer):
    """A bus message's composer on Qt: the shared message composer, an Attach button beside
    Send, the attached files as chips over the editor, and Qt's two pickers."""

    action_methods = (*Composer.action_methods, (AttachFileAction, MessagePromptComposer.attach_file))

    def __init__(self, host: ComposerHost, renderer: QtLineRenderer, placeholder: str) -> None:
        super().__init__(host, renderer, placeholder)
        self.attach_button = QPushButton("+", self.frame)
        self.attach_button.setToolTip(AttachFileAction.title)
        self.attach_button.setAccessibleName(AttachFileAction.title)
        self.attach_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # tapping keeps the keyboard up
        self.attach_button.clicked.connect(self.attach_file)
        self.add_box_button(self.attach_button)
        self.attached_row = QWidget(self)
        chips = QHBoxLayout(self.attached_row)
        chips.setContentsMargins(UiGap.frame, 0, UiGap.frame, 0)
        chips.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout = self.layout()
        layout.insertWidget(layout.indexOf(self.frame_row), self.attached_row)
        self.attached_row.hide()

    def pick_in_window(self) -> None:
        open_file_dialog(self, self)

    def pick_by_path_search(self) -> None:
        open_path_search(self, self, self.host.app.project_dir.path, self.host.app.run_operation)

    def show_files_offered(self) -> None:
        self.attach_button.setVisible(self.takes_files)

    def show_attached(self) -> None:
        chips = self.attached_row.layout()
        delete_layout_widgets(chips)
        for position in range(len(self.attached_files)):
            chips.addWidget(QtAttachedFileChip(self, position))
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


class ProjectComposer(Composer):
    """Textual's `Prompt`: input waits on the agent; the info bar shows `PromptPath`."""

    def __init__(self, host: ComposerHost, renderer: QtLineRenderer, placeholder: str = "") -> None:
        super().__init__(host, renderer, placeholder)
        self.info_bar.show_path(home_relative(str(host.project.path)))

    def input_placeholder(self) -> str:
        """Textual's `Prompt`: the kind's own placeholder, else `ui.input.placeholder`."""
        return self.given_placeholder or self.settings.ui.input.placeholder


class MailboxComposer(MessageComposer, ProjectComposer):
    """A CLI thread's composer, Textual's `MailboxPrompt(MessagePrompt)`, with its project path."""


class Receipt(NotificationSubscriber, ElidedLine):
    """Where your last message in this view stands with its recipients, tucked cleanly on
    the left of `QtInfoBar` (`Read 11:40 · 2 read`)."""

    def __init__(self, app: ClientApplication, renderer: QtLineRenderer,
                 info_bar: QtInfoBar | None = None) -> None:
        super().__init__()
        self.app, self.renderer, self._info_bar = app, renderer, info_bar
        self.references: tuple[MessageReference, ...] = ()
        self.status: NotificationStatus = UncheckedNotifications()
        renderer.follows_theme(self, self.paint_colour)
        self.hide()

    def follow(self, root: str, references: tuple[MessageReference, ...],
               display: DisplayIdentity | NoDisplaySelection) -> None:
        """Show these messages' notifications; asking again for the same read changes nothing."""
        access = self.app.coordination_access
        if not references:
            access.stop_notifications(self)
            self.hide()
            if self._info_bar is not None:
                self._info_bar.sync_visibility()
            return
        read = ReadNotifications(root, LiveNotificationRead(references), display=display)
        if references != self.references:
            self.references = references
            self.paint(access.notification_status(read, references))
        access.show_notifications(self, read)

    def stop(self) -> None:
        self.app.coordination_access.stop_notifications(self)

    def paint(self, status: NotificationStatus) -> None:
        self.status = status
        self.setText(status.title)
        self.setToolTip(f"Last message: {status.title}")
        self.paint_colour()
        self.show()
        if self._info_bar is not None:
            self._info_bar.sync_visibility()

    def paint_colour(self) -> None:
        self.renderer.apply_sheet(self, f"{self.renderer.color_style(self.status.role)}; padding: 0 4px 0 0")

    def notifications_observed(self, results) -> None:
        for status in CheckedNotifications.for_references(self.references, results):
            self.app.schedule_ui(lambda status=status: self.paint(status))

    def notifications_failed(self, error: Exception) -> None:
        failed = self.status.failed(UnavailableNotifications(str(error)))
        self.app.schedule_ui(lambda: self.paint(failed))

    def notifications_reload(self) -> None:
        """Core answered that the display cut is gone; the view's next page read asks anew."""
