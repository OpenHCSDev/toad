"""Drive an Action family's declared keys through Qt's `QShortcut`.

An `Action` family declares `keys: Mapping[InputMode, tuple[str, ...]]` toolkit-neutrally.
Textual's path consumes those keys through its Binding/BindingsMap dispatch. Qt doesn't
have that machinery, so we iterate the family here and install one `QShortcut` per
declared key, each firing the action's `.apply(context)` with the passed-in context.

Mode filtering (`VimMode` / `TextEntryMode`) is a Textual input-dispatch concept; Qt's
shortcuts fire on the whole widget scope. We flatten across modes and bind every key
each action declares.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget


def _qt_sequence(key: str) -> QKeySequence:
    """Textual-style key spellings (``ctrl+d``, ``G``, ``escape``) as `QKeySequence`.

    Qt accepts ``Ctrl+D`` style strings directly; a lone capital letter means Shift+<letter>
    in Textual's convention, which Qt reads as the same thing when written ``Shift+G``.
    """
    spelling = key.strip()
    if len(spelling) == 1 and spelling.isalpha() and spelling.isupper():
        return QKeySequence(f"Shift+{spelling}")
    return QKeySequence(spelling)


def bind_action_shortcuts(widget: QWidget, family: type, context: Any,
                          scope: Qt.ShortcutContext = Qt.ShortcutContext.WidgetWithChildrenShortcut,
                          ) -> list[QShortcut]:
    """Install a `QShortcut` for every key every member of `family` declares.

    Each shortcut fires the member's ``.apply(context)``. Returns the shortcut list so
    the caller can keep a reference (Qt disconnects shortcuts whose owner goes).
    """
    shortcuts: list[QShortcut] = []
    for action_cls in family.members_with(family):
        action = action_cls()
        for keys in action_cls.keys.values():
            for key in keys:
                shortcut = QShortcut(_qt_sequence(key), widget)
                shortcut.setContext(scope)
                shortcut.activated.connect(lambda _a=action, _c=context: _a.apply(_c))
                shortcuts.append(shortcut)
    return shortcuts


def flatten_keys(action_cls: type) -> Iterable[str]:
    """Every key string the action declares across every mode."""
    for keys in action_cls.keys.values():
        yield from keys
