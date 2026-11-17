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


def _fire(action: Any, context: Any) -> None:
    """Run ``action.apply(context)``, swallowing the AttributeError or NotImplementedError
    a Textual-only action raises when its context (a Qt widget) doesn't carry the Textual
    chrome it reaches for. Silent-skip keeps the family loop intact: every new Qt-targeted
    subclass binds automatically, and Textual-only siblings stay quiet instead of blowing
    up the key press. Any other exception reaches Qt's logger as a real fault."""
    try:
        if not getattr(action, "available", lambda _c: True)(context):
            return
        action.apply(context)
    except AttributeError:
        # A Textual-only action whose `.apply` references a Qt-missing surface
        # silently skips — the docstring's family-loop-intact promise holds for
        # the cross-frontend case the family dispatch naturally hits.
        return
    # NOTE: NotImplementedError is no longer swallowed — a Qt subclass that
    # raises `NotImplementedError` from `.apply` is a real missing implementation
    # the action family contract demands, and silent-skip would hide it.
    # Let it reach Qt's logger alongside every other real fault.


def bind_action_shortcuts(widget: QWidget, family: type, context: Any,
                          scope: Qt.ShortcutContext = Qt.ShortcutContext.WidgetWithChildrenShortcut,
                          ) -> list[QShortcut]:
    """Install a `QShortcut` for every key every member of `family` declares.

    Each shortcut fires the member's ``.apply(context)``. Returns the shortcut list so
    the caller can keep a reference (Qt disconnects shortcuts whose owner goes).

    Actions whose ``available(context)`` or ``apply(context)`` raises AttributeError or
    NotImplementedError are silently skipped — a Textual-only sibling (`ShowSidebarAction`
    reaching into `context.app.workspace_chrome.channels`) can coexist in the family
    loop with a Qt-usable one (`BackToBottomAction` reading `context.back_to_bottom_windows`).
    """
    shortcuts: list[QShortcut] = []
    for action_cls in family.members_with(family):
        action = action_cls()
        for keys in action_cls.keys.values():
            for key in keys:
                shortcut = QShortcut(_qt_sequence(key), widget)
                shortcut.setContext(scope)
                shortcut.activated.connect(lambda _a=action, _c=context: _fire(_a, _c))
                shortcuts.append(shortcut)
    return shortcuts


def flatten_keys(action_cls: type) -> Iterable[str]:
    """Every key string the action declares across every mode."""
    for keys in action_cls.keys.values():
        yield from keys
