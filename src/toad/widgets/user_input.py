from typing import Iterable
from textual.app import ComposeResult
from textual import containers
from toad.conversation_markdown import ConversationMarkdown

from toad.menus import MenuItem
from toad.widgets.non_selectable_label import NonSelectableLabel
from toad.widgets.message_divider import MessageDivider


class UserInput(containers.VerticalGroup):
    def __init__(self, content: str, *, show_divider: bool = True) -> None:
        super().__init__()
        self.content = content
        self.show_divider = show_divider

    def compose(self) -> ComposeResult:
        if self.show_divider:
            yield MessageDivider("User")
        with containers.HorizontalGroup(classes="user-input-body"):
            yield NonSelectableLabel("❯" if self.show_divider else " ", id="prompt")
            yield ConversationMarkdown(self.content, id="content")

    def get_block_menu(self) -> Iterable[MenuItem]:
        yield from ()

    def get_block_content(self, destination: str) -> str | None:
        return self.content
