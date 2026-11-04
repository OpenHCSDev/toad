"""Toad modal screens declare their hints key before native binding collection."""
from textual import containers
from textual.css.native import Keyword, NativeDeclaration, Percent, Variable
from textual.css.styles import Styles
from textual.screen import ModalScreen as NativeModalScreen
from ui_theme.scheme import BackgroundColour, PrimaryColour

from toad.native_style import AutoHeight, CenteredChildren, RightPadding, SurfaceBackground
from toad.widget_actions import DismissibleControl, ProfileKeys
from textual.widget import Widget


class ModalScreen[Result](ProfileKeys, NativeModalScreen[Result]):
    """Modal keyboard scope uses the same native declarations as the workspace."""


class DismissibleScreen[Result](DismissibleControl, ModalScreen[Result]):
    def dismiss_control(self) -> None:
        # Textual schedules removal; awaiting from this screen's handler is illegal.
        self.dismiss()


class CenteredScreen(CenteredChildren):
    """A modal whose content sits in the middle of the screen."""



class ShadedScreen(Widget):
    """The screen beneath shows through a light shade of the background."""

    native_theme = (
        NativeDeclaration.of(Styles.background, Variable(BackgroundColour.name), Percent(40)),
    )


class SurfacePanel(SurfaceBackground, containers.Vertical):
    """The surface a modal draws its content on."""


class ModalPanel(SurfacePanel):
    """A nearly full-screen surface framed in the primary colour."""

    native_theme = (NativeDeclaration.of(Styles.border, Keyword("solid"), Variable(PrimaryColour.name)),)

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = "95%"
        self.styles.height = "95%"


class ModalFrame(RightPadding, AutoHeight, containers.VerticalGroup):
    """A dialog's content, framed by a faint thick primary border."""

    native_theme = (
        NativeDeclaration.of(Styles.border, Keyword("thick"), Variable(PrimaryColour.name), Percent(20)),
    )

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.margin = (2, 4, 1, 4)
        self.styles.max_width = 100
