"""Toad modal screens declare their hints key before native binding collection."""
from textual.screen import ModalScreen as NativeModalScreen
from toad.widget_actions import DismissibleControl, ProfileKeys


class ModalScreen[Result](ProfileKeys, NativeModalScreen[Result]):
    """Modal keyboard scope uses the same native declarations as the workspace."""


class DismissibleScreen[Result](DismissibleControl, ModalScreen[Result]):
    def dismiss_control(self) -> None:
        # Textual schedules removal; awaiting from this screen's handler is illegal.
        self.dismiss()
