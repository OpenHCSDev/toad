from toad.block_navigation import SeparatedBlock
from textual.widgets import Static



class Note(SeparatedBlock, Static):
    def get_clipboard_text(self) -> str:
        return str(self.render())
