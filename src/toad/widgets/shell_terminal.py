from typing import Iterable

from textual.content import Content

from toad.menus import FocusBlockCommand, InterruptCommand, MenuCommand
from toad.widgets.terminal import Terminal


class ShellTerminal(Terminal):
    """Subclass of Terminal used in the Shell view."""

    def get_block_menu(self) -> Iterable[MenuCommand]:
        if not self.is_finalized:
            yield InterruptCommand()
            yield FocusBlockCommand(self)

    def get_clipboard_text(self) -> str | None:
        return "\n".join(line.content.plain for line in self.state.buffer.lines)

    def on_mount(self) -> None:
        self.border_title = Content(self.name)
