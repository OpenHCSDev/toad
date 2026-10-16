from toad.block_navigation import ConversationBlock
from textual.widgets import Static



class Note(ConversationBlock, Static):
    DEFAULT_CLASSES = "block"

    def get_clipboard_text(self) -> str | None:
        return str(self.render())
