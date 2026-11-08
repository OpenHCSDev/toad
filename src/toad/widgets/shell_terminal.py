from dataclasses import dataclass
from typing import Iterable

from textual.content import Content
from textual.dom import DOMNode
from textual.message import Message

from toad.menus import FocusBlockCommand, InterruptCommand, MenuCommand
from toad.native_style import (
    AutoHeight,
    FillWidth,
    NoScrollbars,
    RightPadding,
    SpacedAround,
)
from toad.widgets.terminal import Terminal
from textual.events import Mount
from textual import on


class ShellTerminal(
    RightPadding,
    SpacedAround,
    NoScrollbars,
    FillWidth,
    AutoHeight,
    Terminal,
):
    """Subclass of Terminal used in the Shell view."""

    def apply_native_layout(self) -> None:
        super().apply_native_layout()
        self.styles.overflow_x = self.styles.overflow_y = "scroll"

    @dataclass
    class Terminate(Message):
        teminal: ShellTerminal

        @property
        def control(self) -> DOMNode:
            return self.terminal

    @dataclass
    class Interrupt(Message):
        teminal: ShellTerminal

        @property
        def control(self) -> DOMNode:
            return self.terminal

    def get_block_menu(self) -> Iterable[MenuCommand]:
        if not self.is_finalized:
            yield InterruptCommand()
            yield FocusBlockCommand(self)

    def get_clipboard_text(self) -> str:
        return "\n".join(line.content.plain for line in self.state.buffer.lines)

    @on(Mount)
    def on_mount(self) -> None:
        self.border_title = Content(self.name)
