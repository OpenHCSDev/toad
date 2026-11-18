"""The conversation composer on Qt: Textual's message prompt drawn natively. What it offers
after an @ or a /, what accepting an offer writes, and where a typed message goes all come
from the shared owners (MentionCompletion, SlashCommandResults over the CommandCatalog,
BusSubmissions); this module draws them and reads the keys."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from agent_comms.messaging.mentions import MentionCandidate
from agent_comms.messaging.message_reference import MessageReference
from agent_comms.messaging.notification_reads import LiveNotificationRead
from agent_comms.messaging.read_basis import DisplayIdentity, NoDisplaySelection
from agent_comms.ui_model.observation import ReadNotifications
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QKeyEvent, QPalette, QTextCursor
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
from pyqt_reactive.widgets.fitted_text import WrappedText

from toad.client.application import ClientApplication
from toad.client.bus_submission import BusSubmissions, TypedText
from toad.client.commands import ConversationCommands
from toad.client.line_blocks import FailureRole, LineRole, MutedRole
from toad.client.mention_completion import MentionCompletion, MentionEditor
from toad.client.prompt_composer import MessagePromptComposer, PromptComposer, PromptSettingEffects
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
from toad.prompt_actions import NewlineAction, SubmitAction, SubmitInputAction, SubmitNowAction
from toad.widget_actions import DismissAction
from toad.widget_contracts import (
    DismissibleContract,
    OpensSelectedContract,
    SelectsContract,
    SubmitsContract,
)
from toad.qt.composer_vim import ComposerVimMode, apply_normal_key
from toad.qt.lines import QtLineRenderer
from toad.qt.queue_ui import QtDeliveryControls, QtQueueInspection, QtQueueSummary
from toad.qt.prompt_stack import QtInfoBar
from toad.slash_command import SlashCommand
from toad.slash_command_results import CommandMatch, SlashCommandResults
from toad.qt.metrics import UiGap


# The declared TextEntryMode key spellings each prompt action exposes drive the Qt
# composer's QShortcuts. Keeping the composer method as the callback (not the action's
# own .apply, which expects a Textual `PromptTextArea`) lets both backends consume the
# same key declarations without Qt dragging Textual's PromptSubmission chassis.
_COMPOSER_ACTION_METHODS = (
    (SubmitAction, "submit"),
    (SubmitNowAction, "submit_now"),
    (DismissAction, "dismiss_control"),
    (NewlineAction, "_insert_newline"),
)


def _bind_composer_shortcuts(composer: Composer):
    """One `QShortcut` per composer action on the editor, answering the action's keys in
    the current key mode and keymap (`ActionKeys`) and running the composer's own method
    while the editor (or a child) has focus. Textual reaches these methods through its own
    PromptTextArea action system — the keys live in one place."""
    return [composer.host.app.action_keys.bind(composer.editor, action_cls(), getattr(composer, method_name))
            for action_cls, method_name in _COMPOSER_ACTION_METHODS]


class ComposerHost(ConversationCommands):
    """What a composer asks of the conversation view it sits in: the commands it offers
    after a /, and where a typed message goes."""

    app: ClientApplication
    submissions: BusSubmissions

    def submit(self, text: TypedText, action: SubmitInputAction) -> None:
        raise NotImplementedError


class Offer(ABC):
    """One row of the list over the composer and what tapping it writes."""

    @property
    @abstractmethod
    def layout(self) -> StyledTextLayout: ...

    @abstractmethod
    def accept(self, composer: Composer) -> None: ...


@dataclass(frozen=True)
class CommandOffer(Offer):
    """A slash command: accepting it starts the message with the command, as Textual's
    SlashComplete inserts it."""

    match: CommandMatch

    @property
    def layout(self) -> StyledTextLayout:
        return StyledTextLayout(name=Segment(self.match.command.command), detail_line=self.match.command.help,
                                multiline=True)

    def accept(self, composer: Composer) -> None:
        composer.editor.setPlainText(f"{self.match.command.command} ")
        composer.editor.moveCursor(QTextCursor.MoveOperation.End)


@dataclass(frozen=True)
class MentionOffer(Offer):
    """A thread to mention at the cursor."""

    completion: MentionCompletion
    candidate: MentionCandidate

    @property
    def layout(self) -> StyledTextLayout:
        return StyledTextLayout(name=Segment(MentionCompletion.label(self.candidate)))

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

    def __init__(self, host: ComposerHost, renderer: QtLineRenderer, placeholder: str) -> None:
        super().__init__()
        self.host, self.renderer = host, renderer
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
        self.editor.textChanged.connect(self.refresh_glyph)
        self.editor.setFrameShape(QFrame.Shape.NoFrame)
        self.editor.setStyleSheet("QPlainTextEdit { background: transparent; border: none }")
        self.glyph = QLabel()
        self.frame = QFrame()
        self.frame.setObjectName("prompt-frame")
        frame = QHBoxLayout(self.frame)
        frame.setSpacing(0)
        frame.addWidget(self.glyph, 0, Qt.AlignmentFlag.AlignTop)
        frame.addWidget(self.editor, 1)
        self.info_bar = QtInfoBar(host, renderer, self)
        renderer.themed(self, self.paint_colours)
        # Textual's QueueSummary + DeliveryControls, reading the shared submissions owner.
        self.submitting = QtQueueSummary(self)
        self.delivery_controls = QtDeliveryControls(self)
        self.failure = self.line(FailureRole)
        self.receipt = Receipt(host.app, renderer)
        self.send_button = QPushButton(SubmitAction.title, self)
        self.send_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # tapping keeps the keyboard up
        self.send_button.clicked.connect(self.submit)
        # The row's margins are the input box setting's frame margin (`place_input_box`).
        self.frame_row = frame_row = QHBoxLayout()
        frame_row.addWidget(self.frame, 1)
        frame_row.addWidget(self.send_button, 0, Qt.AlignmentFlag.AlignBottom)
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
        for line in (self.failure, self.receipt):
            layout.addWidget(line)
        # The declared prompt-action keys as QShortcuts: Enter, Ctrl+Enter, Shift+Enter, Escape.
        self._shortcuts = _bind_composer_shortcuts(self)
        self.place_input_box()
        self.refresh_glyph()
        self.fit_height()
        self.show_submitting()

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
        self.frame.layout().setContentsMargins(*cells(box.frame_padding))
        left, top, right, bottom = cells(box.label_padding)
        self.glyph.setContentsMargins(left, top, right, bottom)
        self.focus_changed(self.editor.hasFocus())

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
        """The muted placeholder, the offer list, the glyph and the frame's border, under the
        renderer's current scheme."""
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
        self.frame.setStyleSheet(
            f"#prompt-frame {{ border: 1px solid {colour}; border-radius: 2px }}"
            if self.settings.ui.input.box.bordered
            else "#prompt-frame { border: none }")
        self.info_bar.badge.present_editing_mode(self.editor.editing_mode, focused)

    def refresh_editing_mode(self) -> None:
        self.info_bar.badge.present_editing_mode(self.editor.editing_mode, self.editor.hasFocus())
        self.delivery_controls.setVisible(self.offers_send_now)

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
        """Grow with the message up to five lines, as Textual's prompt grows."""
        typed = self.editor.document().blockCount()
        lines = max(1, min(5, typed))
        self.editor.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if typed > 5 else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.editor.setFixedHeight(self.editor.fontMetrics().lineSpacing() * lines + 24)

    @property
    def text(self) -> str:
        return self.editor.toPlainText()

    # Offers

    def set_mention_candidates(self, candidates: tuple[MentionCandidate, ...]) -> None:
        if candidates != self.mention_candidates:
            self.mention_candidates = candidates
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
        self.host.submit(TypedText(text), action)

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

    def restore_draft(self, text: str) -> None:
        """A send that did not land rejoins the draft as Textual's prompt rejoins it."""
        if suffix := self.restored_suffix(self.text, text):
            self.editor.moveCursor(QTextCursor.MoveOperation.End)
            self.editor.insertPlainText(suffix)

    def show_failure(self, text: str) -> None:
        self.failure.setText(text)
        self.failure.show()

    def show_submitting(self) -> None:
        """The queue summary and delivery controls from the shared submissions, as Textual's
        ``_update_queue_summary`` + ``DeliveryControls`` flip on ``offers_send_now``."""
        self.submitting.refresh(self.queue_summary)
        self.delivery_controls.setVisible(self.offers_send_now)

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


class ChannelComposer(MessagePromptComposer, Composer):
    """A channel's composer, which offers its members after an @."""


class MessageComposer(MessagePromptComposer, Composer):
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


class Receipt(NotificationSubscriber, WrappedText):
    """Where your last message in this view stands with its recipients, from the shared
    notification statuses: Checking, then what Core answers (sent, read, answered)."""

    def __init__(self, app: ClientApplication, renderer: QtLineRenderer) -> None:
        super().__init__()
        self.app, self.renderer = app, renderer
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
        self.setText(f"Your last message: {status.title}")
        self.paint_colour()
        self.show()

    def paint_colour(self) -> None:
        self.setStyleSheet(f"{self.renderer.color_style(self.status.role)}; padding: 0 8px 4px 8px")

    def notifications_observed(self, results) -> None:
        for status in CheckedNotifications.for_references(self.references, results):
            self.app.schedule_ui(lambda status=status: self.paint(status))

    def notifications_failed(self, error: Exception) -> None:
        failed = self.status.failed(UnavailableNotifications(str(error)))
        self.app.schedule_ui(lambda: self.paint(failed))

    def notifications_reload(self) -> None:
        """Core answered that the display cut is gone; the view's next page read asks anew."""
