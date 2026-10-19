from toad.block_navigation import CategorizedBlock, ConversationBlock
from toad.setting_widget import SettingVisibility

from toad.widgets.message_filter import ThinkingCategory
from typing import Iterable

from toad.line_blocks import LineBlock
from toad.menus import MenuItem
from toad.widgets.agent_activity import AgentActivityPresentation
from toad.widgets.committed_presentation import SnapshotPresentation
from toad.widgets.line_markdown import LineMarkdown
from toad.widgets.message_filter import MessageCategory


class AgentThought(
    SettingVisibility,
    ConversationBlock,
    SnapshotPresentation,
    CategorizedBlock,
    LineMarkdown,
    can_focus=True,
    setting="agent.thoughts",
):
    """A live thought drawn from the same semantic rows as saved thinking."""

    DEFAULT_CSS = "AgentThought { width: 1fr; height: auto; }"

    @property
    def message_category(self) -> type[MessageCategory]:
        return ThinkingCategory

    def __init__(self, thought: str):
        super().__init__(thought)

    def line_blocks(self, text: str, *, complete: bool = True) -> tuple[LineBlock, ...]:
        return AgentActivityPresentation.thinking(text, complete=complete)

    def on_click(self) -> None:
        self.focus()

    async def append_fragment(self, fragment: str) -> None:
        self.append(fragment)

    async def finish_stream(self) -> None:
        pass

    def get_block_menu(self) -> Iterable[MenuItem]:
        yield MenuItem("Copy thinking", "block.copy", "y")
