from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Self

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding

from textual import getters
from textual.message import Message
from textual.reactive import var
from textual import containers
from textual import widgets
from textual.widgets.option_list import Option

from toad.slash_command_results import SlashCommandResults
from toad.slash_command import SlashCommand
from toad.widgets.selection import SelectionOptionList
from toad.widgets.prompt_popup import CompletionPopup


if TYPE_CHECKING:
    from toad.widgets.prompt import Prompt


class SlashCompleteInput(widgets.Input):
    BINDING_GROUP_TITLE = "Fuzzy search slash commands"
    HELP = """\
## Slash command fuzzy search

Search for slash commands by typing a few characters from the command.

- **cursor keys** Navigate list
- **enter** Add command to prompt
- **escape** Dismiss fuzzy search
"""


class SlashComplete(CompletionPopup):
    """A widget to auto-complete slash commands."""

    CURSOR_BINDING_GROUP = Binding.Group(description="Select")
    BINDINGS = [
        Binding(
            "up",
            "cursor_up",
            "Cursor up",
            group=CURSOR_BINDING_GROUP,
            priority=True,
        ),
        Binding(
            "down",
            "cursor_down",
            "Cursor down",
            group=CURSOR_BINDING_GROUP,
            priority=True,
        ),
        Binding("enter", "submit", "Insert /command", priority=True),
        Binding("escape", "dismiss", "Dismiss", priority=True),
    ]

    DEFAULT_CSS = """
    SlashComplete {
        OptionList {
            height: auto;
        }
    }
    """

    input = getters.query_one(widgets.Input)
    option_list = getters.query_one(widgets.OptionList)

    slash_commands: var[list[SlashCommand]] = var(list)

    @dataclass
    class Completed(Message):
        command: str

    def __init__(
        self,
        slash_commands: Iterable[SlashCommand] | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.slash_commands = list(slash_commands) if slash_commands else []


        self.results = SlashCommandResults(case_sensitive=False)

    @classmethod
    def for_prompt(cls, prompt: Prompt) -> Self | None:
        from toad.widgets.prompt import Prompt
        return cls().data_bind(slash_commands=Prompt.slash_commands)

    def admitted(self) -> bool:
        return self.prompt.supports_completion

    def cursor_changed(self, movement) -> None:
        if movement.entered_slash:
            if self.prompt.prompt_text_area.document.get_line(0).startswith("/"):
                self.focus()

    @on(Completed)
    def insert_command(self, event: Completed) -> None:
        event.stop()
        area = self.prompt.prompt_text_area
        area.clear()
        area.insert(f"{event.command} ")
        self.action_dismiss()

    def compose(self) -> ComposeResult:
        yield SlashCompleteInput(compact=True, placeholder="fuzzy search")
        yield SelectionOptionList()

    def focus_content(self, scroll_visible: bool) -> None:
        from toad.widgets.conversation import Conversation
        self.query_ancestor(Conversation).update_slash_commands()
        self.filter_slash_commands("")
        self.input.focus(scroll_visible)

    def on_mount(self) -> None:
        self.filter_slash_commands("")

    @on(widgets.Input.Changed)
    def on_input_changed(self, event: widgets.Input.Changed) -> None:
        event.stop()
        self.filter_slash_commands(event.value)

    async def watch_slash_commands(self, slash_commands: list[SlashCommand]) -> None:
        self.filter_slash_commands(self.input.value)

    def filter_slash_commands(self, prompt: str) -> None:
        """Filter slash commands by the given prompt.

        Args:
            prompt: Text prompt.
        """
        self.option_list.set_options(self.results.options(prompt, self.slash_commands))
        if self.display:
            self.option_list.highlighted = 0
        else:
            with self.option_list.prevent(widgets.OptionList.OptionHighlighted):
                self.option_list.highlighted = 0

    def action_cursor_down(self) -> None:
        self.option_list.action_cursor_down()

    def action_cursor_up(self) -> None:
        self.option_list.action_cursor_up()

    def action_submit(self) -> None:
        option_list = self.option_list
        if (option := option_list.highlighted_option) is not None:
            with self.input.prevent(widgets.Input.Changed):
                self.input.clear()
            self.post_message(self.Completed(option.id or ""))
