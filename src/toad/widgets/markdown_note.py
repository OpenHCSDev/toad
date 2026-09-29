from toad.block_navigation import ConversationBlock
from textual.widgets import Markdown



class MarkdownNote(ConversationBlock, Markdown):
    def get_clipboard_text(self) -> str | None:
        return self.source
