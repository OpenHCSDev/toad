"""Toad modal screens declare their hints key before native binding collection."""
from textual.screen import ModalScreen as NativeModalScreen
from toad.widget_actions import VimHintsAction


class ModalScreen[Result](NativeModalScreen[Result]):
    BINDINGS = list(VimHintsAction.bindings())
