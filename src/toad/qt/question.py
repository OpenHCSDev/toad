"""The Qt question widget: a conversation's inline consent prompt.

A conversation asks a question through `Conversation.ask(options, title, callback)`; on the
Textual side the sibling `Question` widget in `toad/widgets/question.py` renders the title
and option rows, and the user's pick fires the `Answer` back. The Qt backend hands the same
Ask to this widget, mounted as the conversation view's bottom-dock over the composer.

`QuestionContext` is the toolkit-neutral owner (plain mixin in `toad/question_actions.py`);
`QuestionAction` and its `SelectKindAction` family declare the keys and `apply()` bodies both
backends share. Qt iterates the family through `ActionKeys.bind_family(SelectKindAction)` —
every `AllowOnceAction` / `AllowAlwaysAction` / `RejectOnceAction` / `RejectAlwaysAction`
member fires on its own declared key, same as Textual, with no hand-rolled roster here.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from toad.answer import Answer
from toad.client.input_attention import InputAttention
from toad.question_actions import ChoiceQuestion, QuestionContext, SelectKindAction
from toad.widget_contracts import DismissibleContract
from toad.qt.metrics import UiGap

if TYPE_CHECKING:
    from toad.answer import Ask


class QtQuestion(QuestionContext, ChoiceQuestion, QFrame, DismissibleContract):
    """Qt's inline question. A hidden panel at the bottom of the conversation view that fills
    with the title and option buttons when the conversation asks, and tucks itself away once
    the user picks or the question is retracted.
    """

    def __init__(self, app, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._ask: Ask | None = None
        # An open question requires input: the window title blinks while one waits, as
        # Textual's prompt question blinks the terminal title (`InputAttention`).
        self.app = app
        self.attention: InputAttention = app.input_attention
        self.destroyed.connect(partial(self.attention.release, self))
        # Parent self — a parentless QLabel on Qt-for-Android becomes a top-level window
        # with its own EGL surface and can recurse into the deadlock protector during
        # the first-paint flush of the conversation view (same shape as PR #1885).
        self._title = QLabel(self)
        self._title.setWordWrap(True)
        self._title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._options_row = QHBoxLayout()
        self._options_row.setContentsMargins(0, UiGap.normal, 0, 0)
        self._options_row.setSpacing(UiGap.loose)
        column = QVBoxLayout(self)
        column.setContentsMargins(UiGap.wide, UiGap.frame, UiGap.wide, UiGap.frame)
        column.setSpacing(UiGap.normal)
        column.addWidget(self._title)
        column.addLayout(self._options_row)
        self._buttons: list[QPushButton] = []
        self._shortcuts: list[QShortcut] = []
        self.hide()

    @property
    def question(self) -> QtQuestion:  # type: ignore[override]
        """The `QuestionContext` contract. The Qt widget is its own question owner."""
        return self

    @property
    def options(self) -> tuple[Answer, ...]:
        """`QuestionContext` contract — the Ask's options or an empty tuple when retracted.
        `SelectKindAction.available` reads this through `context.question.options`."""
        return tuple(self._ask.options) if self._ask is not None else ()

    @property
    def accepts_selection(self) -> bool:
        """`QuestionContext` contract — true while an Ask is unresolved."""
        return self._ask is not None

    @property
    def selection(self) -> int:
        """The currently-focused option's index. `SelectAction` (Enter) commits this one."""
        for index, button in enumerate(self._buttons):
            if button.hasFocus():
                return index
        return 0

    def select_answer(self, index: int) -> None:
        """`QuestionContext` contract — commit the option at `index`. Qt's commit path is
        just `_pick`: fire the Ask's callback and retract. `SelectKindAction.apply` reaches
        here through the declared-key family, same as Textual's post_message path."""
        self._pick(index)

    def update(self, ask: Ask) -> None:
        """Fill in a new question. Called by ConversationView.ask when the conversation asks."""
        self._clear_options()
        self._ask = ask
        self._title.setText(ask.question)
        self._title.setVisible(bool(ask.question))
        for index, answer in enumerate(ask.options):
            button = QPushButton(answer.text)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            button.clicked.connect(lambda _checked=False, idx=index: self._pick(idx))
            self._buttons.append(button)
            self._options_row.addWidget(button)
        # Declared-key family: every SelectKindAction member (AllowOnceAction / AllowAlwaysAction
        # / RejectOnceAction / RejectAlwaysAction) binds its own TextEntryMode keys; `available`
        # silently skips the kinds this Ask doesn't offer. Same source of truth as Textual.
        self._shortcuts = self.app.action_keys.bind_family(
            self, SelectKindAction, self,
            scope=Qt.ShortcutContext.WindowShortcut,
        )
        self.show()
        self.attention.require(self)
        if self._buttons:
            self._buttons[0].setFocus()

    def retract(self) -> None:
        self._clear_options()
        self._ask = None
        self.hide()
        self.attention.release(self)

    def withdraw(self, ask: Ask) -> None:
        """Its asker withdrew `ask`: tuck away only if it is still the one shown."""
        if self._ask is ask:
            self.retract()

    def dismiss_control(self) -> None:
        """A cross-toolkit consumer can dismiss the question panel the same way as any other
        DismissibleContract — retracting the Ask and tucking the panel away."""
        self.retract()

    def _clear_options(self) -> None:
        while self._options_row.count():
            item = self._options_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._buttons.clear()
        for shortcut in self._shortcuts:
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._shortcuts.clear()

    def _pick(self, index: int) -> None:
        if self._ask is None or index < 0 or index >= len(self._ask.options):
            return
        chosen: Answer = self._ask.options[index]
        callback = self._ask.callback
        self.retract()
        if callback is not None:
            callback(chosen)

    @property
    def accepts_selection(self) -> bool:
        """`QuestionAction.available` reads this through `context.question.accepts_selection`."""
        return self._ask is not None
