from toad.block_navigation import ConversationBlock
from typing import Iterable
from textual.widgets import Markdown

from toad.menus import MenuItem


class MarkdownNote(ConversationBlock, Markdown):
    def get_block_menu(self) -> Iterable[MenuItem]:
        return
        yield

    def get_block_content(self, destination: str) -> str | None:
        return self.source
