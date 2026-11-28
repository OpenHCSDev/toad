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
from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QWidget

from toad.keymap import KeymapRow
from toad.widget_actions import DeclaredWidgetActions


def _qt_sequences(key: str) -> tuple[QKeySequence, ...]:
    """Textual-style key spellings (``ctrl+d``, ``G``, ``escape``, ``enter``) as `QKeySequence`s.

    Qt accepts ``Ctrl+D`` style strings directly; a lone capital letter means Shift+<letter>
    in Textual's convention (``Shift+G``). Qt separates main-keyboard ``Return`` from numpad
    ``Enter`` while Textual spells both ``enter``, so any ``enter`` spelling maps to both
    ``Return`` and ``Enter`` (including modified forms like ``ctrl+enter`` / ``shift+enter``).
    """
    spelling = key.strip()
    if len(spelling) == 1 and spelling.isalpha() and spelling.isupper():
        return (QKeySequence(f"Shift+{spelling}"),)
    parts = spelling.split("+")
    tail = parts[-1].lower()
    prefix = "+".join((*parts[:-1], ""))
    if tail == "enter":
        return (QKeySequence(f"{prefix}Return"), QKeySequence(f"{prefix}Enter"))
    if tail == "plus":
        return (QKeySequence(f"{prefix}+"), QKeySequence(f"{prefix}Shift+="))
    return (QKeySequence(spelling),)


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
        self.ran: list[object] = []
        """Every action a key press ran, in order; the shipped gate reads it to require that
        each press runs exactly one."""

    def keys(self, action: object) -> list[QKeySequence]:
        """``action``'s declared keys in the current key mode, after the user's remap."""
        ui = self.settings().ui
        declared = tuple(dict.fromkeys(
            binding.key for binding in DeclaredWidgetActions.mode_bindings(type(action), ui.key_mode.binding_mode())))
        return [seq for key in ui.keymap.keys_for(KeymapRow.of(action, ui.key_mode), declared)
                for seq in _qt_sequences(key)]

    def bind(self, widget: QWidget, action: object, fire: Callable[[], None],
             scope: Qt.ShortcutContext = Qt.ShortcutContext.WidgetWithChildrenShortcut,
             context: Any = None) -> QShortcut:
        """One shortcut on ``widget`` answering ``action``'s keys, running ``fire``."""
        shortcut = QShortcut(widget)
        shortcut.setContext(scope)
        shortcut.setKeys(self.keys(action))
        key = id(shortcut)
        self.bound[key] = BoundAction(shortcut, action, fire, context)
        shortcut.activated.connect(lambda: self.run((self.bound[key],)))
        shortcut.activatedAmbiguously.connect(lambda: self.resolve(shortcut))
        shortcut.destroyed.connect(lambda: self.bound.pop(key))
        return shortcut

    def resolve(self, pressed: QShortcut) -> None:
        """Several live shortcuts on the focus path answer the pressed key: run the one
        Textual's binding order picks (`order`)."""
        self.run(self.order(pressed.keys()))

    def order(self, keys: list[QKeySequence]) -> tuple[BoundAction, ...]:
        """The live shortcuts on the focus path answering ``keys``, in Textual's binding order:
        priority actions from the outermost widget in, then the rest from the focus out."""
        chain: list[QWidget] = []
        widget = QApplication.focusWidget()
        while widget is not None:
            chain.append(widget)
            widget = widget.parentWidget()
        pressed = set(key.toString() for key in keys)
        answering = [bound for bound in self.bound.values()
                     if bound.shortcut.isEnabled() and bound.shortcut.parent() in chain
                     and pressed & set(key.toString() for key in bound.shortcut.keys())]
        depth = {id(widget): index for index, widget in enumerate(chain)}
        priority = sorted((bound for bound in answering if bound.action.priority),
                          key=lambda bound: -depth[id(bound.shortcut.parent())])
        rest = sorted((bound for bound in answering if not bound.action.priority),
                      key=lambda bound: depth[id(bound.shortcut.parent())])
        return (*priority, *rest)

    def claims(self, event: QKeyEvent) -> bool:
        """Whether an available priority action on the focus path answers this key event.
        A text control otherwise takes Enter, Shift+Enter or Ctrl+Y for its own editing before
        any shortcut sees them; Textual's prompt bindings are `priority` and beat its text
        area, so an editor gives such a key up (`ComposerEditor.event`)."""
        pressed = QKeySequence(event.keyCombination())
        return any(bound.action.priority and bound.available() for bound in self.order([pressed]))

    def run(self, candidates: tuple[BoundAction, ...]) -> None:
        """Run the first candidate whose action is available where it is bound. An action
        runs only when available, so its ``apply`` raising is a real fault."""
        for bound in candidates:
            if bound.available():
                self.ran.append(bound.action)
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
            shortcuts.append(self.bind(widget, action, lambda _a=action: _a.apply(context), scope, context))
        return shortcuts

    def follow(self) -> None:
        """`ui.key_mode` or `ui.keymap` changed: every live shortcut answers its new keys."""
        for bound in tuple(self.bound.values()):
            bound.shortcut.setKeys(self.keys(bound.action))
