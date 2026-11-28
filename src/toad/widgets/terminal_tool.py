"""Optional projection of the operational ACP terminal execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar
from rich.style import Style
from textual.content import Content
from textual.css.native import ThemeState, DeclaresTheme, Keyword, NativeDeclaration, Percent, TextVariable, Variable
from textual.css.styles import Styles
from textual.message import Message
from toad.surface_binding import ViewSurfaceBinding
from ui_theme.scheme import ErrorColour, PrimaryColour, SuccessColour, ThemeColour

from metaclass_registry.mro_dispatch import MroDispatch, handles
from toad.acp.terminal_controller import TerminalController
from toad.terminal_execution import (
    TerminalExecution, TerminalCompletion, FailedTerminalOutcome,
    RunningTerminalOutcome, UnstartedTerminalOutcome, RetiredTerminalOutcome,
)
from toad.native_style import AutoHeight, FillWidth, NoScrollbars, SpacedAround
from toad.widgets.terminal import ExecutionTerminal
from textual.events import Mount
from textual import on
from textual.events import Unmount

class TerminalLook(DeclaresTheme):
    """The panel of a command that has not finished."""

    tone: ClassVar[type[ThemeColour]] = PrimaryColour
    tint: ClassVar[int] = 10
    title_style: ClassVar[Style] = Style(bold=True)
    native_theme: ClassVar[tuple[NativeDeclaration, ...]] = (
        NativeDeclaration.of(Styles.border, Keyword("panel"), Variable(PrimaryColour.name)),
        NativeDeclaration.of(Styles.border_title_color, TextVariable(PrimaryColour.name)),
        NativeDeclaration.of(Styles.background, Variable(PrimaryColour.name), Percent(10)),
    )

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if "tone" in vars(cls):
            cls.native_theme = (
                NativeDeclaration.of(Styles.border, Keyword("panel"), Variable(cls.tone.name)),
                NativeDeclaration.of(Styles.border_title_color, TextVariable(cls.tone.name)),
                NativeDeclaration.of(Styles.background, Variable(cls.tone.name), Percent(cls.tint)),
            )


class FinishedTerminalLook(TerminalLook):
    """A completed or failed command softens its tint and drops the bold title."""

    tint = 7
    title_style = Style(bold=False)


class SucceededTerminalLook(FinishedTerminalLook):
    tone = SuccessColour


class FailedTerminalLook(FinishedTerminalLook):
    tone = ErrorColour


class TerminalTool(
    SpacedAround,
    NoScrollbars,
    FillWidth,
    AutoHeight,
    ExecutionTerminal,
    MroDispatch,
):
    @dataclass
    class Projection(Message):
        """A native render request borrows its original acquired resources."""

        binding: ViewSurfaceBinding
        controller: TerminalController
        terminal_id: str
        execution: TerminalExecution

    look = ThemeState(TerminalLook)

    def __init__(self, execution: TerminalExecution, *, terminal_id: str) -> None:
        self.execution = execution
        self.terminal_id = terminal_id
        super().__init__(size=(execution.state.width, execution.state.height))
        self.border_title = Content(str(execution.command))

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.padding = (1, 1, 0, 1)
        self.styles.overflow_x = self.styles.overflow_y = "scroll"
        self.styles.border_title_style = self.look.title_style

    def present_look(self, look: type[TerminalLook]) -> None:
        self.look = look
        self.styles.border_title_style = look.title_style

    @on(Mount)
    def on_mount(self) -> None:
        super().on_mount()
        self.execution.attach(self)

    @on(Unmount)
    def on_unmount(self) -> None:
        self.execution.detach(self)

    def present_execution(
        self, scrollback: set[int] | None, alternate: set[int] | None
    ) -> None:
        self.project_state(scrollback, alternate)
        self.dispatch_sync(self.execution.operation.outcome())

    @handles(RunningTerminalOutcome, UnstartedTerminalOutcome, RetiredTerminalOutcome)
    def present_pending(self, outcome) -> None:
        """These original outcomes have no completion border to draw."""

    @handles(TerminalCompletion)
    def present_completion(self, outcome) -> None:
        self.finalize()
        self.present_look((FailedTerminalLook, SucceededTerminalLook)[outcome.successful])
        if not outcome.successful:
            self.border_title = Content(f"{self.execution.command} [{outcome.label}]")

    @handles(FailedTerminalOutcome)
    def present_failure(self, outcome) -> None:
        self.finalize()
        self.present_look(FailedTerminalLook)
        self.border_title = Content(f"{self.execution.command} [{outcome.error}]")
