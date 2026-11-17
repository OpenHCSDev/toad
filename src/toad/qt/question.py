"""The Qt question widget: a conversation's inline consent prompt.

A conversation asks a question through `Conversation.ask(options, title, callback)`; on the
Textual side the sibling `Question` widget in `toad/widgets/question.py` renders the title
and option rows, and the user's pick fires the `Answer` back. The Qt backend hands the same
Ask to this widget, mounted as the conversation view's bottom-dock over the composer.

`QuestionContext` is the toolkit-neutral owner (plain mixin in `toad/question_actions.py`);
`QuestionAction` and its `SelectKindAction` family define the keys, groups and `apply()`
bodies both backends share. Qt binds the option-kind keys (``a``/``A``/``r``/``R``) through
``QShortcut`` so the action family's selected-option-by-kind flow works here too.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from toad.answer import Answer
from toad.question_actions import QuestionContext

if TYPE_CHECKING:
    from toad.widgets.question import Ask


class QtQuestion(QuestionContext, QFrame):
    """Qt's inline question. A hidden panel at the bottom of the conversation view that fills
    with the title and option buttons when the conversation asks, and tucks itself away once
    the user picks or the question is retracted.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._ask: Ask | None = None
        self._title = QLabel()
        self._title.setWordWrap(True)
        self._title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._options_row = QHBoxLayout()
        self._options_row.setContentsMargins(0, 4, 0, 0)
        self._options_row.setSpacing(6)
        column = QVBoxLayout(self)
        column.setContentsMargins(10, 8, 10, 8)
        column.setSpacing(4)
        column.addWidget(self._title)
        column.addLayout(self._options_row)
        self._buttons: list[QPushButton] = []
        self._shortcuts: list[QShortcut] = []
        self.hide()

    @property
    def question(self) -> QtQuestion:  # type: ignore[override]
        """The `QuestionContext` contract. The Qt widget is its own question owner."""
        return self

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
        self._bind_kind_shortcuts()
        self.show()
        if self._buttons:
            self._buttons[0].setFocus()

    def retract(self) -> None:
        self._clear_options()
        self._ask = None
        self.hide()

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

    def _bind_kind_shortcuts(self) -> None:
        """AllowOnce/AllowAlways/RejectOnce/RejectAlways keys. Matches the `SelectKindAction`
        family's declared TextEntryMode keys (a/A/r/R) in `toad/question_actions.py`."""
        if self._ask is None:
            return
        for key_text, kind in (("A", "allow_once"),
                               ("Shift+A", "allow_always"),
                               ("R", "reject_once"),
                               ("Shift+R", "reject_always")):
            match = next(
                (index for index, answer in enumerate(self._ask.options) if answer.kind == kind),
                None,
            )
            if match is None:
                continue
            shortcut = QShortcut(QKeySequence(key_text), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(lambda idx=match: self._pick(idx))
            self._shortcuts.append(shortcut)

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
