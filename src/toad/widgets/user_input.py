from typing import Iterable
from textual.app import ComposeResult
from textual import containers
from toad.conversation_markdown import ConversationMarkdown

from toad.menus import MenuItem
from toad.widgets.non_selectable_label import NonSelectableLabel
from toad.widgets.message_divider import MessageDivider
from toad.widgets.message_filter import CategorizedBlock, MessageCategory


class UserInput(CategorizedBlock, containers.VerticalGroup):
    @property
    def message_category(self) -> MessageCategory:
        return MessageCategory.USER

    def __init__(self, content: str) -> None:
        super().__init__()
        self.content = content

    def compose(self) -> ComposeResult:
        yield MessageDivider("User")
        with containers.HorizontalGroup():
            yield NonSelectableLabel("❯", id="prompt")
            yield ConversationMarkdown(self.content, id="content")

    def get_block_menu(self) -> Iterable[MenuItem]:
        yield from ()

    def get_block_content(self, destination: str) -> str | None:
        return self.content
