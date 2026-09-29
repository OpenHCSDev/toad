"""Editor movement and declared command text own prompt cursor behavior."""
from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING
from weakref import ref

from agent_comms.declared_family import DeclaredFamily
from textual.content import Content
from textual.widgets.text_area import Selection

if TYPE_CHECKING:
    from toad.slash_command import SlashCommand
    from toad.widgets.prompt import PromptTextArea


@dataclass(frozen=True)
class CursorMovement:
    previous: Selection
    current: Selection

    @property
    def moved_cursor(self) -> bool:
        return self.previous != self.current and self.current.is_empty

    @property
    def entered_slash(self) -> bool:
        return (self.previous.end, self.current.end) == ((0, 0), (0, 1))

    @property
    def retreating_first_line(self) -> bool:
        if (self.previous.end[0], self.current.end[0]) != (0, 0):
            return False
        return self.current.end[1] < self.previous.end[1]


class CommandText(DeclaredFamily, affix="Text"):
    """One decode joins actual text to its existing command declaration."""

    requires_agent = True

    def __init__(self, text: str):
        self.text = text

    @classmethod
    def decode_input(cls, text: str, commands: list[SlashCommand]) -> CommandText:
        name, separator, _arguments = text.partition(" ")
        command = next((item for item in commands if item.command == name), None)
        return DeclaredCommandText(text, command, bool(separator)) if command is not None else PlainCommandText(text)

    def highlight(self) -> Content:
        return Content(self.text)

    def retreat(self, editor: PromptTextArea, movement: CursorMovement) -> None:
        pass


class PlainCommandText(CommandText):
    pass


class DeclaredCommandText(CommandText):
    def __init__(self, text: str, command: SlashCommand, arguments_started: bool):
        super().__init__(text)
        self.command = command
        self.arguments_started = arguments_started

    @property
    def requires_agent(self):
        return self.command.requires_agent

    def highlight(self):
        return self.command.highlight_input(self.text, self.arguments_started)

    def retreat(self, editor, movement):
        if self.text == self.command.command and movement.retreating_first_line:
            editor.selection = Selection((0, 0), (0, len(self.text)))


class HistoryCursor(DeclaredFamily, affix="Cursor"):
    direction: int

    @classmethod
    @abstractmethod
    def at_edge(cls, editor: PromptTextArea) -> bool: ...

    @classmethod
    def move(cls, editor: PromptTextArea, select: bool, ordinary) -> None:
        from toad.messages import HistoryMove

        if editor.selection.is_empty and not select:
            if cls.at_edge(editor):
                editor.post_message(HistoryMove.for_mode(cls.direction, editor.shell_mode, editor.text))
                return
        ordinary(select)


class PreviousHistoryCursor(HistoryCursor):
    direction = -1

    @classmethod
    def at_edge(cls, editor):
        return editor.navigator.is_first_wrapped_line(editor.cursor_location)


class NextHistoryCursor(HistoryCursor):
    direction = 1

    @classmethod
    def at_edge(cls, editor):
        return editor.navigator.is_last_wrapped_line(editor.cursor_location)


class PromptCursor:
    def __init__(self, editor: PromptTextArea):
        self._editor = ref(editor)

    def changed(self, previous: Selection, current: Selection) -> None:
        from toad.widgets.prompt import Prompt
        from toad.widgets.prompt_popup import CompletionPopup

        editor = self._editor()
        if editor is None:
            return
        movement = CursorMovement(previous, current)
        prompt = editor.query_ancestor(Prompt)
        if prompt.supports_completion and movement.moved_cursor:
            for popup in prompt.query(CompletionPopup):
                popup.cursor_changed(movement)
            if current.end[0] == 0:
                line = editor.document.get_line(0)
                CommandText.decode_input(line, editor.slash_commands).retreat(editor, movement)
