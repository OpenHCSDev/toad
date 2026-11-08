"""Optional projection of the operational ACP terminal execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar
from rich.style import Style
from textual.content import Content
from textual.css.native import ThemeState, DeclaresTheme, Keyword, NativeDeclaration, Percent, TextVariable, Variable
from textual.css.styles import Styles
from textual.message import Message
from ui_theme.scheme import ErrorColour, PrimaryColour, SuccessColour

from metaclass_registry.mro_dispatch import MroDispatch, handles
from toad.terminal_execution import (
    TerminalExecution, TerminalCompletion, FailedTerminalOutcome,
    RunningTerminalOutcome, UnstartedTerminalOutcome, RetiredTerminalOutcome,
)
from toad.native_style import AutoHeight, FillWidth, NoScrollbars, SpacedAround
from toad.widgets.terminal import Terminal
from textual.events import Mount
from textual import on
from textual.events import Unmount

if TYPE_CHECKING:
    from toad.agent_surface import AttachedSurfaceBinding
    from toad.acp.terminal_controller import TerminalController


class TerminalLook(DeclaresTheme):
    """The panel of a command that has not finished."""

    native_theme: ClassVar[tuple[NativeDeclaration, ...]] = (
        NativeDeclaration.of(Styles.border, Keyword("panel"), Variable(PrimaryColour.name)),
        NativeDeclaration.of(Styles.border_title_color, TextVariable(PrimaryColour.name)),
        NativeDeclaration.of(Styles.background, Variable(PrimaryColour.name), Percent(10)),
    )
    title_style: ClassVar[Style] = Style(bold=True)


class SucceededTerminalLook(TerminalLook):
    native_theme = (
        NativeDeclaration.of(Styles.border, Keyword("panel"), Variable(SuccessColour.name)),
        NativeDeclaration.of(Styles.border_title_color, TextVariable(SuccessColour.name)),
        NativeDeclaration.of(Styles.background, Variable(SuccessColour.name), Percent(7)),
    )
    title_style = Style(bold=False)


class FailedTerminalLook(TerminalLook):
    native_theme = (
        NativeDeclaration.of(Styles.border, Keyword("panel"), Variable(ErrorColour.name)),
        NativeDeclaration.of(Styles.border_title_color, TextVariable(ErrorColour.name)),
        NativeDeclaration.of(Styles.background, Variable(ErrorColour.name), Percent(7)),
    )
    title_style = Style(bold=False)


class TerminalTool(
    SpacedAround,
    NoScrollbars,
    FillWidth,
    AutoHeight,
    Terminal,
    MroDispatch,
):
    @dataclass
    class Projection(Message):
        """A native render request borrows its original acquired resources."""

        binding: AttachedSurfaceBinding
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

    def resize_process(self, width: int, height: int) -> None:
        self.execution.update_size(width, height)

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
