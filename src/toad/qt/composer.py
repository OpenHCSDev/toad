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
from formbridge.key_declarations import TextEntryMode
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QTextCursor
from pyqt_reactive.widgets.shared.list_item_delegate import LAYOUT_ROLE, MultilinePreviewItemDelegate
from pyqt_reactive.widgets.shared.styled_text_layout import Segment, StyledTextLayout
from PySide6.QtWidgets import (
    QHBoxLayout,
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
from toad.client.notification_status import (
    CheckedNotifications,
    NotificationStatus,
    UnavailableNotifications,
    UncheckedNotifications,
)
from toad.client.subscribers import NotificationSubscriber
from toad.prompt_actions import NewlineAction, SubmitAction, SubmitNowAction
from toad.widget_actions import DismissAction
from toad.widget_contracts import (
    DismissibleContract,
    OpensSelectedContract,
    SelectsContract,
    SubmitsContract,
)
from toad.qt.action_shortcuts import bind_action_shortcuts
from toad.qt.composer_vim import ComposerVimMode, VimState, apply_normal_key
from toad.qt.lines import QtLineRenderer
from toad.slash_command import SlashCommand
from toad.slash_command_results import CommandMatch, SlashCommandResults


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


def _qt_sequence(spelling: str):
    from PySide6.QtGui import QKeySequence
    text = spelling.strip()
    if len(text) == 1 and text.isalpha() and text.isupper():
        return QKeySequence(f"Shift+{text}")
    return QKeySequence(text)


def _bind_composer_shortcuts(composer: Composer):
    """Install one `QShortcut` per declared TextEntryMode key on each composer-action.

    Qt has no Mode/InputDispatch chain like Textual's; every declared key for
    the relevant action fires the composer's own method when the editor (or any
    child) has focus. Textual still reaches these methods through its own
    PromptTextArea action system — the keys live in one place."""
    from PySide6.QtGui import QShortcut
    shortcuts = []
    for action_cls, method_name in _COMPOSER_ACTION_METHODS:
        callback = getattr(composer, method_name)
        for spelling in action_cls.keys.get(TextEntryMode, ()):
            shortcut = QShortcut(_qt_sequence(spelling), composer.editor)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            shortcuts.append(shortcut)
    return shortcuts


class ComposerHost(ConversationCommands):
    """What a composer asks of the conversation view it sits in: the commands it offers
    after a /, and where a typed message goes."""

    app: ClientApplication
    submissions: BusSubmissions

    def submit(self, text: TypedText) -> None:
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
        scheme = composer.host.app.theme.color_scheme
        self.setItemDelegate(MultilinePreviewItemDelegate(
            scheme.to_qcolor(scheme.text_primary), scheme.to_qcolor(scheme.text_secondary),
            scheme.to_qcolor(scheme.selection_text), self))
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.itemClicked.connect(self.take_item)
        self.hide()

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
        # Modal vim input, off by default so non-vim users aren't trapped. A setting toggle
        # (sweep follow-up) will flip this; once on, Esc in INSERT enters NORMAL mode.
        self.vim_enabled = False
        self.vim = ComposerVimMode()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # Vim NORMAL mode intercepts navigation/edit commands before the standard
        # composer bindings; Enter + Ctrl+Enter are owned by SubmitAction/SubmitNowAction
        # on the composer and fire through QShortcut regardless.
        offers = self.composer.offers
        key = event.key()
        if (self.vim_enabled and self.vim.state is VimState.NORMAL
                and not offers.isVisible() and key != Qt.Key.Key_Escape):
            apply_normal_key(self, self.vim, event)
            self.composer.refresh_mode_indicator()
            return
        # Offer navigation stays local — it's widget-scoped, not a declared action family.
        if offers.isVisible() and key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            offers.step(-1 if key == Qt.Key.Key_Up else 1)
            return
        if offers.isVisible() and key == Qt.Key.Key_Tab:
            offers.accept_current()
            return
        # Enter / Ctrl+Enter / Shift+Enter / Escape are all bound as QShortcuts on
        # Composer via `bind_action_shortcuts`; they read the declared keys off
        # `SubmitAction`/`SubmitNowAction`/`NewlineAction`/`DismissAction` so the
        # Qt editor and Textual's PromptTextArea share a single source of truth.
        super().keyPressEvent(event)


class Composer(MentionEditor, SubmitsContract, DismissibleContract, QWidget):
    """A conversation's composer: the offer list, the editor and its send button, then
    what is still submitting, the last send's failure and the delivery of your last message.

    It sets no colours of its own: the application's pyqt-reactive theme styles its button,
    and the theme's input and list styles frame the editor and the offers.

    Inherits `SubmitsContract` + `DismissibleContract` so the shared action families
    (`SubmitAction`, `SubmitNowAction`, `DismissAction`, `NewlineAction` in
    `toad.prompt_actions` / `toad.widget_actions`) bind to this widget without Qt
    restating any key spelling — one declaration in those modules drives both Textual's
    PromptTextArea and the Qt editor."""

    def __init__(self, host: ComposerHost, renderer: QtLineRenderer, placeholder: str) -> None:
        super().__init__()
        self.host, self.renderer = host, renderer
        self.mention_candidates: tuple[MentionCandidate, ...] = ()
        self.commands: list[SlashCommand] = []
        self.ranking = SlashCommandResults(case_sensitive=False)
        self.dismissed_text = ""
        self.offers = OfferList(self)
        self.editor = ComposerEditor(self)
        self.editor.setPlaceholderText(placeholder)
        self.editor.textChanged.connect(self.refresh_offers)
        self.editor.cursorPositionChanged.connect(self.refresh_offers)
        self.editor.textChanged.connect(self.fit_height)
        self.send_button = QPushButton("Send", self)
        self.send_button.clicked.connect(self.send)
        styles = host.app.theme.color_scheme.styles
        self.editor.setStyleSheet(styles.generate_text_input_style())
        self.offers.setStyleSheet(styles.generate_list_widget_style())
        self.submitting = self.line(MutedRole)
        self.failure = self.line(FailureRole)
        self.receipt = Receipt(host.app, renderer)
        # Vim mode indicator — only shown when vim is enabled AND the editor is in NORMAL.
        # INSERT reads as "no indicator" (standard editing); NORMAL reads as "-- NORMAL --".
        self.mode_indicator = self.line(MutedRole)
        row = QHBoxLayout()
        row.setContentsMargins(6, 4, 6, 4)
        row.addWidget(self.editor, 1)
        row.addWidget(self.send_button, 0, Qt.AlignmentFlag.AlignBottom)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.offers)
        layout.addLayout(row)
        for line in (self.mode_indicator, self.submitting, self.failure, self.receipt):
            layout.addWidget(line)
        # Bind the declared prompt-action keys as QShortcuts on the editor. The
        # callbacks target `self` (the composer) so `SubmitAction`/`DismissAction`
        # /`SubmitNowAction`/`NewlineAction` on Qt fire the same contract Textual's
        # Prompt uses — no hand-rolled Enter/Ctrl+Enter/Escape in `keyPressEvent`.
        self._shortcuts = _bind_composer_shortcuts(self)
        self.fit_height()
        self.refresh_mode_indicator()

    def line(self, role: type[LineRole]) -> WrappedText:
        label = WrappedText()
        label.setStyleSheet(self.renderer.color_style(role))
        label.setContentsMargins(8, 0, 8, 0)
        label.hide()
        return label

    def refresh_mode_indicator(self) -> None:
        """Show '-- NORMAL --' whenever vim is on and the editor is not in INSERT."""
        showing = self.editor.vim_enabled and self.editor.vim.state is VimState.NORMAL
        if showing:
            self.mode_indicator.setText("-- NORMAL --")
            self.mode_indicator.show()
        else:
            self.mode_indicator.hide()

    def set_vim_enabled(self, enabled: bool) -> None:
        """Called by the (future) vim-mode setting toggle. Also drives VimWorkspaceAction's
        Qt consumer: when any composer has vim on, the workspace's modal command mode fires."""
        self.editor.vim_enabled = enabled
        self.editor.vim.state = VimState.INSERT
        self.refresh_mode_indicator()

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

    def send(self) -> None:
        text = self.text
        if not text.strip():
            return
        self.editor.clear()
        self.dismissed_text = ""
        self.failure.hide()
        self.host.submit(TypedText(text))

    # Toolkit-neutral action-family contract: Textual's Prompt inherits Submits +
    # DismissibleControl from widget_actions.py; the mixin lift itself is fork
    # a28441d7743dc4abb's work. These methods expose the same contract on Qt so the
    # neutral family, once lifted, binds without changing this widget again.

    def submit(self) -> None:
        """What `SubmitAction` calls — the action-family alias for `send`."""
        self.send()

    def submit_now(self) -> None:
        """What `SubmitNowAction` (Ctrl+Enter, Ctrl+Y) calls; same path as send today —
        the queue-bypass distinction belongs to `BusSubmissions`, not the widget."""
        self.send()

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
        if self.editor.vim_enabled and self.editor.vim.state is VimState.INSERT:
            self.editor.vim.state = VimState.NORMAL
            self.refresh_mode_indicator()
            return
        self.editor.clear()
        self.dismissed_text = ""
        self.offers.show_offers("", ())
        self.editor.clearFocus()

    def restore_draft(self, text: str) -> None:
        """A send that did not land comes back as the draft, in front of anything typed since."""
        typed = self.text
        self.editor.setPlainText(text if not typed.strip() else f"{text}\n{typed}")
        self.editor.moveCursor(QTextCursor.MoveOperation.End)

    def show_failure(self, text: str) -> None:
        self.failure.setText(text)
        self.failure.show()

    def show_submitting(self) -> None:
        summary = self.host.submissions.queue_summary
        self.submitting.setText(summary)
        self.submitting.setVisible(bool(summary))

    def hold(self, reason: str) -> None:
        """A read-only view holds compose and says why; an empty reason opens it."""
        self.editor.setReadOnly(bool(reason))
        self.send_button.setEnabled(not reason)
        self.editor.setToolTip(reason)

    def labelled(self, label: str) -> None:
        """The view's label changed; a channel's composer keeps the placeholder its kind gave it."""


class ChannelComposer(Composer):
    """A channel's composer, which offers its members after an @."""


class MessageComposer(Composer):
    """A direct message's composer: it names its peer, as Textual's MessagePrompt does."""

    def __init__(self, host: ComposerHost, renderer: QtLineRenderer) -> None:
        super().__init__(host, renderer, "Message thread")

    def labelled(self, label: str) -> None:
        self.editor.setPlaceholderText(f"Message {label}")


class Receipt(NotificationSubscriber, WrappedText):
    """Where your last message in this view stands with its recipients, from the shared
    notification statuses: Checking, then what Core answers (sent, read, answered)."""

    def __init__(self, app: ClientApplication, renderer: QtLineRenderer) -> None:
        super().__init__()
        self.app, self.renderer = app, renderer
        self.references: tuple[MessageReference, ...] = ()
        self.status: NotificationStatus = UncheckedNotifications()
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
        self.setStyleSheet(f"{self.renderer.color_style(status.role)}; padding: 0 8px 4px 8px")
        self.show()

    def notifications_observed(self, results) -> None:
        for status in CheckedNotifications.for_references(self.references, results):
            self.app.schedule_ui(lambda status=status: self.paint(status))

    def notifications_failed(self, error: Exception) -> None:
        failed = self.status.failed(UnavailableNotifications(str(error)))
        self.app.schedule_ui(lambda: self.paint(failed))

    def notifications_reload(self) -> None:
        """Core answered that the display cut is gone; the view's next page read asks anew."""
