"""Vim modal input for Qt's ComposerEditor.

Textual composes its modal keybindings through `formbridge.key_declarations.ModalInputMode`;
Qt has no equivalent until here. The Qt widget is a `QPlainTextEdit`, so the state machine
runs in `keyPressEvent`: NORMAL mode intercepts navigation/edit commands, INSERT mode passes
keys through to the super. Escape toggles into NORMAL; `i`/`a`/`I`/`A`/`o`/`O` enter INSERT.

The capability is the shared `ModalInputMode` from formbridge; this file only owns the Qt
dispatch surface. A Textual composer uses its own `VimMode(EditingMode, ModalInputMode)`
subclass on the same base.
"""

from __future__ import annotations

from formbridge.key_declarations import ModalInputMode
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QTextCursor

from toad.neovim_editing import InsertState, NeovimState, NormalState


class ComposerVimMode(ModalInputMode):
    """Modal command dispatch for Qt's ComposerEditor. Inherits the shared
    `ModalInputMode` contract (modal=True, navigation_spellings, fallback_bindings) so the
    declared-key machinery treats this the same as Textual's VimMode.

    Its state is a member of Textual's `NeovimState` family (`InsertState`,
    `NormalState`, …), so the mode names and `accepts_text` come from the one owner the
    TUI's badge reads; the saved `key_mode` picks the starting member by its first map mode."""

    def __init__(self, key_mode) -> None:
        self.state: NeovimState = NeovimState.for_mode(key_mode.map_modes[0])(blocking=False)
        self._pending: str = ""  # multi-char commands like `dd`, `gg`

    @property
    def label(self) -> str:
        return self.state.label

    @property
    def accepts_text(self) -> bool:
        """The shared `EditingMode.accepts_text`, answered by the current Neovim state."""
        return self.state.accepts_text

    def enter_insert(self) -> None:
        self.state = InsertState(blocking=False)

    def enter_normal(self) -> None:
        self.state = NormalState(blocking=False)


_NORMAL_MOTIONS: dict[int, QTextCursor.MoveOperation] = {
    Qt.Key.Key_H: QTextCursor.MoveOperation.Left,
    Qt.Key.Key_L: QTextCursor.MoveOperation.Right,
    Qt.Key.Key_J: QTextCursor.MoveOperation.Down,
    Qt.Key.Key_K: QTextCursor.MoveOperation.Up,
    Qt.Key.Key_W: QTextCursor.MoveOperation.NextWord,
    Qt.Key.Key_B: QTextCursor.MoveOperation.PreviousWord,
    Qt.Key.Key_E: QTextCursor.MoveOperation.EndOfWord,
    Qt.Key.Key_0: QTextCursor.MoveOperation.StartOfLine,
    Qt.Key.Key_Dollar: QTextCursor.MoveOperation.EndOfLine,
}


def apply_normal_key(editor, mode: ComposerVimMode, event: QKeyEvent) -> bool:
    """NORMAL-mode keypress dispatch. Returns True when the key was consumed; False to
    pass through to the super (which happens for unrecognized keys — they do nothing in
    normal mode rather than inserting text, since text insertion only happens in INSERT)."""
    key = event.key()
    cursor = editor.textCursor()

    if key in _NORMAL_MOTIONS:
        cursor.movePosition(_NORMAL_MOTIONS[key])
        editor.setTextCursor(cursor)
        mode._pending = ""
        return True

    if key == Qt.Key.Key_G:
        if mode._pending == "g":
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            editor.setTextCursor(cursor)
            mode._pending = ""
        elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            cursor.movePosition(QTextCursor.MoveOperation.End)
            editor.setTextCursor(cursor)
            mode._pending = ""
        else:
            mode._pending = "g"
        return True

    if key == Qt.Key.Key_X:
        cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()
        editor.setTextCursor(cursor)
        mode._pending = ""
        return True

    if key == Qt.Key.Key_D:
        if mode._pending == "d":
            cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
            cursor.movePosition(QTextCursor.MoveOperation.EndOfLine, QTextCursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            # Also eat the newline left behind.
            if not cursor.atEnd():
                cursor.deleteChar()
            editor.setTextCursor(cursor)
            mode._pending = ""
        else:
            mode._pending = "d"
        return True

    if key == Qt.Key.Key_I:
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
            editor.setTextCursor(cursor)
        mode.enter_insert()
        mode._pending = ""
        return True

    if key == Qt.Key.Key_A:
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            cursor.movePosition(QTextCursor.MoveOperation.EndOfLine)
        else:
            cursor.movePosition(QTextCursor.MoveOperation.Right)
        editor.setTextCursor(cursor)
        mode.enter_insert()
        mode._pending = ""
        return True

    if key == Qt.Key.Key_O:
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
            cursor.insertText("\n")
            cursor.movePosition(QTextCursor.MoveOperation.Up)
        else:
            cursor.movePosition(QTextCursor.MoveOperation.EndOfLine)
            cursor.insertText("\n")
        editor.setTextCursor(cursor)
        mode.enter_insert()
        mode._pending = ""
        return True

    if key == Qt.Key.Key_U:
        editor.undo()
        mode._pending = ""
        return True

    # Unknown key in normal mode: swallow it so stray letters don't insert text.
    mode._pending = ""
    return True
