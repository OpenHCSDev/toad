"""Drive declared actions' keys through Qt's `QShortcut`, as Textual's bindings drive them.

An action's keys are the keys it declares for the current `ui.key_mode`
(`DeclaredWidgetActions.mode_bindings`, the keys a Textual context claiming it binds), with
`ui.keymap`'s remap of its row (`Keymap.keys_for`), so no Textual context has to be loaded. `ActionKeys`
installs one `QShortcut` per action with those keys, firing ``.apply(context)`` (or the
callback a composer gives), and sets every live shortcut's keys again when either setting
changes, so a remap or a new key mode reaches Qt at once.

When more than one live shortcut on the focus path answers a key, Qt fires none of them
(`activatedAmbiguously`). `ActionKeys.resolve` then applies Textual's binding order from the
declarations: `priority` actions first, outermost first, then the focused control's outward;
the first whose action is available there runs. So Escape in a composer jumps a history that
is off its tail (`BackToBottomAction`, priority) and otherwise dismisses the composer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QWidget

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


@dataclass(frozen=True)
class BoundAction:
    """One live shortcut: the action whose keys it answers, what it runs, and the context the
    action's `available` is asked about (none for a composer method, which is always live)."""

    shortcut: QShortcut
    action: Any
    fire: Callable[[], None]
    context: Any = None

    def available(self) -> bool:
        return self.context is None or self.action.available(self.context)


class ActionKeys:
    """Every live action shortcut and the keys it answers. ``settings`` reads the app's
    settings, whose `ui.key_mode` and `ui.keymap` choose the keys."""

    def __init__(self, settings: Callable[[], Any]) -> None:
        self.settings = settings
        self.bound: dict[int, BoundAction] = {}

    def keys(self, action: object) -> list[QKeySequence]:
        """``action``'s declared keys in the current key mode, after the user's remap."""
        ui = self.settings().ui
        declared = tuple(dict.fromkeys(
            binding.key for binding in DeclaredWidgetActions.mode_bindings(type(action), ui.key_mode.binding_mode())))
        return [_qt_sequence(key) for key in ui.keymap.keys_for(KeymapRow.of(action, ui.key_mode), declared)]

    def bind(self, widget: QWidget, action: object, fire: Callable[[], None],
             scope: Qt.ShortcutContext = Qt.ShortcutContext.WidgetWithChildrenShortcut,
             context: Any = None) -> QShortcut:
        """One shortcut on ``widget`` answering ``action``'s keys, running ``fire``."""
        shortcut = QShortcut(widget)
        shortcut.setContext(scope)
        shortcut.setKeys(self.keys(action))
        shortcut.activated.connect(fire)
        shortcut.activatedAmbiguously.connect(lambda: self.resolve(shortcut))
        key = id(shortcut)
        self.bound[key] = BoundAction(shortcut, action, fire, context)
        shortcut.destroyed.connect(lambda: self.bound.pop(key))
        return shortcut

    def resolve(self, pressed: QShortcut) -> None:
        """Several live shortcuts on the focus path answer the pressed key: run the one
        Textual's binding order picks. Priority actions are tried first from the outermost
        widget in, then the rest from the focused widget out; the first available runs."""
        chain: list[QWidget] = []
        widget = QApplication.focusWidget()
        while widget is not None:
            chain.append(widget)
            widget = widget.parentWidget()
        keys = set(key.toString() for key in pressed.keys())
        answering = [bound for bound in self.bound.values()
                     if bound.shortcut.isEnabled() and bound.shortcut.parent() in chain
                     and keys & set(key.toString() for key in bound.shortcut.keys())]
        depth = {id(widget): index for index, widget in enumerate(chain)}
        priority = sorted((bound for bound in answering if bound.action.priority),
                          key=lambda bound: -depth[id(bound.shortcut.parent())])
        rest = sorted((bound for bound in answering if not bound.action.priority),
                      key=lambda bound: depth[id(bound.shortcut.parent())])
        for bound in (*priority, *rest):
            if bound.available():
                bound.fire()
                return

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
            shortcuts.append(self.bind(widget, action, lambda _a=action: _fire(_a, context), scope, context))
        return shortcuts

    def follow(self) -> None:
        """`ui.key_mode` or `ui.keymap` changed: every live shortcut answers its new keys."""
        for bound in tuple(self.bound.values()):
            bound.shortcut.setKeys(self.keys(bound.action))
