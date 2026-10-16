"""Toad modal screens share opt-in hints without bypassing native input custody."""

from textual.screen import ModalScreen as NativeModalScreen

from toad.application_actions import VimHintsAction


class ModalScreen[Result](NativeModalScreen[Result]):
    BINDINGS = list(VimHintsAction.bindings())
