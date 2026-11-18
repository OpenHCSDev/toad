"""Drive declared actions' keys through Qt's `QShortcut`, as Textual's bindings drive them.

An action's keys are the keys it declares for the current `ui.key_mode`
(`DeclaredWidgetActions.mode_bindings`, the keys a Textual context claiming it binds), with
`ui.keymap`'s remap of its row (`Keymap.keys_for`), so no Textual context has to be loaded. `ActionKeys`
installs one `QShortcut` per action with those keys, firing ``.apply(context)`` (or the
callback a composer gives), and sets every live shortcut's keys again when either setting
changes, so a remap or a new key mode reaches Qt at once.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QWidget

from toad.keymap import KeymapRow
from toad.widget_actions import DeclaredWidgetActions


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
    """Run ``action.apply(context)`` when the action is available there. Only actions whose
    declared capability the context has are bound (`ActionKeys.bind_family`), so a failure
    here is a real fault and reaches Qt's logger."""
    if action.available(context):
        action.apply(context)


class ActionKeys:
    """Every live action shortcut and the keys it answers. ``settings`` reads the app's
    settings, whose `ui.key_mode` and `ui.keymap` choose the keys."""

    def __init__(self, settings: Callable[[], Any]) -> None:
        self.settings = settings
        self.bound: dict[int, tuple[QShortcut, object]] = {}

    def keys(self, action: object) -> list[QKeySequence]:
        """``action``'s declared keys in the current key mode, after the user's remap."""
        ui = self.settings().ui
        declared = tuple(dict.fromkeys(
            binding.key for binding in DeclaredWidgetActions.mode_bindings(type(action), ui.key_mode.binding_mode())))
        return [_qt_sequence(key) for key in ui.keymap.keys_for(KeymapRow.of(action, ui.key_mode), declared)]

    def bind(self, widget: QWidget, action: object, fire: Callable[[], None],
             scope: Qt.ShortcutContext = Qt.ShortcutContext.WidgetWithChildrenShortcut) -> QShortcut:
        """One shortcut on ``widget`` answering ``action``'s keys, running ``fire``."""
        shortcut = QShortcut(widget)
        shortcut.setContext(scope)
        shortcut.setKeys(self.keys(action))
        shortcut.activated.connect(fire)
        key = id(shortcut)
        self.bound[key] = (shortcut, action)
        shortcut.destroyed.connect(lambda: self.bound.pop(key))
        return shortcut

    def bind_family(self, widget: QWidget, family: type, context: Any,
                    scope: Qt.ShortcutContext = Qt.ShortcutContext.WidgetWithChildrenShortcut,
                    ) -> list[QShortcut]:
        """A shortcut for every member of ``family`` whose declared capability ``context`` has
        (`DeclaredAction.runs_on`), firing its ``.apply(context)``. A member that reaches another
        toolkit's chrome (`ShowSidebarAction`, Textual's workspace DOM) is not bound here."""
        shortcuts = []
        for action_cls in family.members_with(family):
            if not action_cls.runs_on(context):
                continue
            action = action_cls()
            shortcuts.append(self.bind(widget, action, lambda _a=action: _fire(_a, context), scope))
        return shortcuts

    def follow(self) -> None:
        """`ui.key_mode` or `ui.keymap` changed: every live shortcut answers its new keys."""
        for shortcut, action in tuple(self.bound.values()):
            shortcut.setKeys(self.keys(action))
