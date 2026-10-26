"""Toad modal screens declare their hints key before native binding collection."""
from textual.screen import ModalScreen as NativeModalScreen
from toad.widget_actions import DismissibleControl, VimHintsAction


class ModalScreen[Result](NativeModalScreen[Result]):
    BINDINGS = list(VimHintsAction.bindings())


class DismissibleScreen[Result](DismissibleControl, ModalScreen[Result]):
    def dismiss_control(self) -> None:
        # Textual schedules removal; awaiting from this screen's handler is illegal.
        self.dismiss()
