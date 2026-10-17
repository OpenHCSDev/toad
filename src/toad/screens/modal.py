"""Toad modal screens share opt-in hints without bypassing native input custody."""
from textual.screen import ModalScreen as NativeModalScreen


class ModalScreen[Result](NativeModalScreen[Result]):
    def _init_bindings(self):
        return self._merge_bindings()
