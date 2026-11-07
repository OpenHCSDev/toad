"""Which bus this Toad opens: this machine's own, or a remote one it holds a profile for."""

from __future__ import annotations

import time

from textual import on
from textual.app import ComposeResult
from textual.css.native import Keyword, NativeDeclaration, Variable
from textual.css.styles import Styles
from textual.widgets import Select, Static
from ui_theme.scheme import PrimaryColour

from toad.comms_root import BusChoice
from toad.screens.modal import CenteredScreen, DismissibleScreen, SurfacePanel
from toad.widget_actions import PriorityActions


class BusPanel(SurfacePanel):
    native_theme = (NativeDeclaration.of(Styles.border, Keyword("round"), Variable(PrimaryColour.name)),)

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.width = 64
        self.styles.height = "auto"
        self.styles.padding = (1, 2)


class BusPrompt(Static):
    """What the picker is for, above its rows."""


class BusChoices(CenteredScreen, PriorityActions, DismissibleScreen[BusChoice]):
    """The buses this machine can open, dismissed with the one the reader picked.

    The picker does not relaunch: `CoreConnection.select` chooses at the process
    boundary, so its caller ends the application onto the choice. A machine holding no
    remote profile still sees its own bus named, because an empty list would leave the
    reader guessing whether the picker worked.
    """

    def __init__(self, choices: tuple[BusChoice, ...]) -> None:
        super().__init__()
        self.choices = choices

    @classmethod
    def offered(cls) -> BusChoices:
        return cls(BusChoice.offered(time.time()))

    def compose(self) -> ComposeResult:
        with BusPanel():
            yield BusPrompt("Open a bus · Esc returns")
            # Blank until the reader picks: a Select posts Changed when its initial value is
            # set, so starting on a row chose that row before the list had been read.
            yield Select(
                [(choice.label(), index) for index, choice in enumerate(self.choices)],
                allow_blank=True, prompt="Choose a bus",
            )

    @on(Select.Changed)
    def picked(self, event: Select.Changed) -> None:
        """A picked row is the answer; the caller relaunches onto it. Blank is not a pick."""
        match event.value:
            case int() as index:
                self.dismiss(self.choices[index])
